"""ContextBuilder: 从一个或多个 prompts/ 目录加载 identity 与 skills,按 skill 组装 OpenAI messages

支持的 skill 布局:
1. 扁平: <prompts_dir>/skills/<skill>.md
2. 嵌套 (Claude Code 风格): <prompts_dir>/skills/<skill>/SKILL.md (或 skill.md)

skill 文件格式 (YAML-like frontmatter + markdown body):

    ---
    name: skill_name
    description: 一句话描述
    include_identity: true|false
    inputs:
      - var1
      - var2
    ---

    Markdown body with {var1} and {var2} placeholders.

多目录加载语义:
- 第一个目录是"基线",其 identity.md 是主身份;后续目录的 identity.md 仅被忽略并 log
- 同名 skill 后加载的覆盖前面,并打 warning
- 核心 skill (CORE_SKILLS) 只允许从基线目录加载,后续目录的同名 skill 被拒绝

调用:
    cb = ContextBuilder(["prompts", "third_party_skills"])
    messages = cb.build_messages("answer_with_context", context=ctx, query=q, history=hist)
    client.chat(messages=messages, model=...)
"""
from __future__ import annotations

import re  # 用于 frontmatter 的正则匹配
from dataclasses import dataclass, field  # Skill 数据类
from pathlib import Path  # 跨平台路径操作
from typing import Iterable, Optional, Union  # 类型提示

from base.logger import logger

# RAG agent 化之后, 答题流程改由 identity + tools 驱动, 没有核心 skill 需要保护
# CORE_SKILLS 是一个空集合, 表示默认没有任何受保护的 skill
# 调用者可在初始化时通过 core_skills 参数传入自定义的受保护 skill 集合
CORE_SKILLS: frozenset = frozenset()


@dataclass
class Skill:
    """表示一个加载完成的 prompt skill。

    每个 Skill 对应 prompts 目录下的一个 .md 文件,
    通过 YAML 风格的 frontmatter 定义元数据, markdown 正文作为模板。
    """
    name: str  # skill 的唯一标识名, 用于检索
    description: str  # 一句话描述该 skill 的用途
    inputs: list  # 模板中需要的变量名列表, 如 ["context", "query"]
    template: str  # markdown 模板正文, 包含 {var_name} 占位符
    include_identity: bool  # 组装消息时是否前置插入 identity (system 消息)
    source: str = ""  # 该 skill 来源文件的绝对路径, 用于调试和冲突提示
    meta: dict = field(default_factory=dict)  # frontmatter 中所有原始字段的完整副本


# 用于匹配 YAML 风格 frontmatter 的正则表达式
# 以 "---" 开头, 捕获中间元数据块 (group 1), 以及后面的正文 (group 2)
# re.DOTALL 使 . 能够匹配换行符, 从而跨行匹配
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _strip_quotes(s: str) -> str:
    """去除字符串两端的引号(单引号或双引号)。

    如果字符串首尾字符相同且为单引号或双引号, 则去除外层引号。
    否则直接返回原字符串。仅处理最外层, 不会递归处理。
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _coerce_bool(s: str):
    """将字符串转换为 Python 的布尔值或数字类型。

    这是手写 YAML 解析器中的类型转换函数:
    - 如果值为 "true"/"yes"/"on"(不区分大小写), 返回 True
    - 如果值为 "false"/"no"/"off"(不区分大小写), 返回 False
    - 尝试转为数字(float 或 int), 如果转换成功则返回数字类型
    - 以上都不满足, 则原样返回字符串

    注意: 此函数不会抛出异常, 保证了 frontmatter 解析的健壮性。
    """
    low = s.strip().lower()
    # 先做布尔关键字的匹配
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    # 尝试转为数字
    try:
        if "." in low:
            return float(low)
        return int(low)
    except (ValueError, TypeError):
        pass
    # 如果以上都不匹配, 保持为字符串原值
    return s


def parse_frontmatter(text: str) -> tuple:
    """解析带有 YAML 风格 frontmatter 的 markdown 文件。

    参数:
        text: 文件的完整文本内容

    返回:
        (meta, body) 的二元组:
        - meta: 解析后的 frontmatter 字典
        - body: frontmatter 之后的 markdown 正文

    如果不存在有效的 frontmatter (没有 "---" 包裹的元数据块),
    则返回 ({}, 原始文本)。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta = m.group(1)  # 提取 "---" 之间的元数据原始字符串
    body = m.group(2).strip("\n")  # frontmatter 之后的正文, 去掉首尾换行
    return _parse_yaml_block(raw_meta), body


def _parse_yaml_block(text: str) -> dict:
    """手动解析 YAML 风格的键值对块(不使用 PyYAML 依赖)。

    这是一个轻量级的 key-value 解析器, 支持以下格式:
    1. 简单键值: key: value
    2. 列表键值: key:\n  - item1\n  - item2
    3. 多行字面块: key: |\n  line1\n  line2
    4. 注释: 以 # 开头的行会被跳过
    5. 空行: 作为分隔符处理

    不依赖 PyYAML 的目的是避免引入额外依赖,
    并且对于 prompt 管理这种简单场景已足够使用。
    """
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 跳过空行和注释行
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # 跳过不包含 ":" 的行(不是有效的键值对)
        if ":" not in line:
            i += 1
            continue
        # 以第一个 ":" 为分隔, 分割 key 和 value
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "|":
            # 多行字面块 (literal block): key: |\n  line1\n  line2
            # 这种格式用于多行字符串场景,
            # 后续行以相同的缩进级别延续, 最终合并为一个字符串
            lines_joined = []
            i += 1  # 移动到字面块的第一个内容行
            if i < len(lines):
                # 通过第一个内容行的缩进量来确定字面块的缩进基准
                indent = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines):
                    nxt = lines[i]
                    stripped = nxt.strip()
                    if stripped == "":
                        # 保留空行作为分隔(但不会保留精确的换行数)
                        lines_joined.append("")
                        i += 1
                        continue
                    # 如果当前行的缩进 >= 基准缩进, 则属于字面块的一部分
                    if len(nxt) - len(nxt.lstrip()) >= indent:
                        lines_joined.append(stripped)
                        i += 1
                    else:
                        # 缩进回退, 表示字面块结束
                        break
            # 将所有行合并为一个字符串, 用空格连接
            result[key] = " ".join(lines_joined)

        elif value:
            # 简单键值对: key: value
            # 对值进行类型转换(布尔/数字)并去除外层引号
            result[key] = _coerce_bool(_strip_quotes(value))
            i += 1

        else:
            # 值为空的情况, 尝试解析为列表: key:\n  - item1\n  - item2
            # 以 "- " 开头的连续行会被解析为列表
            items: list = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt.lstrip().startswith("-"):
                    # 提取 "- " 之后的内容, 并去除外层引号
                    items.append(_strip_quotes(nxt.lstrip()[1:].strip()))
                    i += 1
                else:
                    break
            result[key] = items
    return result


class ContextBuilder:
    """核心类: 从 prompts 目录加载 identity 和 skills, 组装 LLM 消息。

    支持多目录叠加加载:
    - 第一个目录是基线目录(base directory), 必须存在
    - 后续目录作为增量/覆盖目录, 可选的(不存在只打 warning)
    - identity.md 只从基线目录加载, 后续目录的 identity.md 被忽略
    - 同名 skill 后加载覆盖前面加载的
    - 核心 skill (core_skills) 只允许从基线目录加载
    """

    def __init__(
        self,
        prompts_dirs: Union[str, Path, Iterable[Union[str, Path]]],
        core_skills: frozenset = CORE_SKILLS,
    ):
        """初始化 ContextBuilder。

        参数:
            prompts_dirs: 一个或多个 prompts 目录路径。
                         第一个是基线目录(必须存在),
                         后续为增量覆盖目录(可选)。
            core_skills: 受保护的核心 skill 集合, 默认空集。
        """
        # 统一转换为 Path 列表
        if isinstance(prompts_dirs, (str, Path)):
            dirs = [Path(prompts_dirs)]
        else:
            dirs = [Path(d) for d in prompts_dirs]
        if not dirs:
            raise ValueError("prompts_dirs 不能为空")
        if not dirs[0].is_dir():
            raise FileNotFoundError(f"基线 prompts 目录不存在: {dirs[0]}")
        self.prompts_dirs = dirs
        self.core_skills = core_skills

        # 第一步: 从基线目录加载 identity (系统提示词的基础)
        self.identity: str = self._load_identity()

        # 第二步: 检查后续目录, 仅记录它们是否包含被忽略的 identity.md
        for d in self.prompts_dirs[1:]:
            if not d.is_dir():
                logger.warning(f"prompts 目录不存在,跳过: {d}")
                continue
            if (d / "identity.md").exists():
                logger.info(f"第三方目录 {d} 中的 identity.md 被忽略(只允许基线目录定义身份)")

        # 第三步: 按顺序加载所有 skills (后加载的覆盖前面的)
        self.skills: dict = {}
        for idx, d in enumerate(self.prompts_dirs):
            if not d.is_dir():
                continue
            is_baseline = idx == 0  # 是否是第一个(基线)目录
            self._load_skills_from(d, is_baseline)

        logger.debug(
            f"ContextBuilder 就绪: identity={'是' if self.identity else '否'}, "
            f"skills={sorted(self.skills.keys())}"
        )

    def _load_identity(self) -> str:
        """从基线目录加载身份文件。

        identity.md 位于 prompts_dirs[0]/identity.md,
        如果文件不存在则返回空字符串。
        这个文件的内容会作为 system message 的基础身份定义。
        """
        f = self.prompts_dirs[0] / "identity.md"
        if not f.exists():
            return ""
        return f.read_text(encoding="utf-8").strip()

    def _load_skills_from(self, prompts_dir: Path, is_baseline: bool):
        """从 prompts_dir 加载技能。

        旧布局: prompts_dir/skills/ 下存放 skill 目录
        新布局: 非基线目录自身就是 skill 集合（如 prompts/style/）

        设计说明:
        - 基线目录使用旧布局, 即 skills 子目录形式
        - 非基线目录(第三方/增量目录)支持两种布局:
          1) 也有 skills 子目录 -> 旧布局
          2) 目录本身直接包含 .md 文件 -> 新布局
          这种设计使第三方扩展更灵活, 无需强制创建 skills 子目录
        """
        skills_dir = prompts_dir / "skills"
        if skills_dir.is_dir():
            # 旧布局: prompt_dir/skills/ 下存放所有 skill 文件/子目录
            for file, fallback in self._scan_skills(skills_dir):
                self._register(self._load_one(file, fallback_name=fallback), is_baseline)
        elif not is_baseline:
            # 新布局：非基线目录本身是 skill 集合
            # 直接扫描该目录下的所有 .md 文件
            for file, fallback in self._scan_skills(prompts_dir):
                self._register(self._load_one(file, fallback_name=fallback), is_baseline)

    def _scan_skills(self, root: Path):
        """递归扫描目录树, 查找所有 skill 定义文件。

        支持两种文件布局, 按优先级处理:
        1. 扁平布局: 根目录下的 *.md 文件(排除 SKILL.md/README.md 等约定文件)
           - 每个 .md 文件作为一个 skill, 文件名(不含扩展名)作为 skill 名称
        2. 嵌套布局: 子目录中包含 SKILL.md 或 skill.md
           - 目录名作为 skill 名称, 目录内的 SKILL.md/skill.md 作为 skill 内容
           - 子目录中其他 .md 文件会被忽略(只有约定的文件名才被识别)
        3. 如果子目录既不是嵌套布局也不包含可识别的 skill 文件,
           则递归进入该子目录继续搜索(深度优先)

        Yields:
            (file_path, fallback_name) 元组:
            - file_path: 找到的 skill 文件路径
            - fallback_name: 如果 frontmatter 中没有 name 字段时的默认 skill 名
        """
        # 先查找根目录下的扁平布局 .md 文件
        for f in sorted(root.glob("*.md")):
            # 排除嵌套布局的入口文件(SKILL.md/skill.md)和 readme 文件
            # 这些文件会在子目录遍历时被处理
            if f.name.lower() in ("skill.md", "readme.md"):
                continue
            yield f, f.stem

        # 遍历子目录, 查找嵌套布局
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            # 先检查是否是嵌套布局(子目录内有 SKILL.md 或 skill.md)
            skill_file = self._find_skill_file(sub)
            if skill_file is not None:
                # 嵌套布局: 子目录名作为 fallback skill 名称
                yield skill_file, sub.name
            else:
                # 既不是扁平也不是嵌套, 递归进入子目录继续搜索
                yield from self._scan_skills(sub)

    @staticmethod
    def _find_skill_file(directory: Path) -> Optional[Path]:
        """在目录中查找 skill 定义文件。

        按照约定, 优先查找 SKILL.md, 其次 skill.md(不区分大小写)。
        这是为了支持 Claude Code 风格的 skill 目录布局:
            skills/my_skill/SKILL.md
        其中 SKILL.md 是该 skill 的入口文件。
        如果两个文件都不存在, 返回 None。
        """
        for name in ("SKILL.md", "skill.md"):
            f = directory / name
            if f.exists():
                return f
        return None

    def _load_one(self, file: Path, fallback_name: str) -> Optional[Skill]:
        """从单个 .md 文件加载一个 skill。

        参数:
            file: skill markdown 文件的路径
            fallback_name: 如果文件中 frontmatter 没有指定 name 字段时使用的默认名称

        返回:
            解析成功返回 Skill 实例, 解析失败返回 None

        解析逻辑:
        1. 读取文件内容
        2. 解析 frontmatter (YAML 风格键值对) 和 markdown 正文
        3. 从 frontmatter 中提取 name, description, inputs, include_identity 等字段
        4. 如果 frontmatter 不提供 name, 则使用 fallback_name(通常是文件名或目录名)
        5. inputs 必须是列表类型, 如果不是则自动包装为单元素列表
        """
        try:
            text = file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            # name: 优先使用 frontmatter 中的 name, 否则用 fallback_name
            name = meta.get("name") or fallback_name
            # inputs: 模板变量列表, 确保是 list 类型
            inputs = meta.get("inputs") or []
            if not isinstance(inputs, list):
                inputs = [inputs]
            return Skill(
                name=str(name),
                description=str(meta.get("description", "")),
                inputs=list(inputs),
                template=body,
                include_identity=bool(meta.get("include_identity", False)),
                source=str(file.resolve()),  # 记录绝对路径, 便于调试
                meta=meta,  # 保留原始元数据的完整副本
            )
        except Exception as e:
            logger.error(f"加载 skill 失败 {file}: {e}")
            return None

    def _register(self, skill: Optional[Skill], is_baseline: bool):
        """注册一个 skill 到技能字典中。

        处理覆盖逻辑:
        1. 如果 skill 为 None (加载失败), 直接跳过
        2. 如果技能名已存在且名为核心 skill (core_skills):
           - 仅当是从基线目录加载时才允许覆盖
           - 从非基线目录加载时拒绝覆盖并打 warning
        3. 普通同名 skill: 后加载的覆盖前面的, 并打 warning (提醒用户注意覆盖行为)
        4. 新 skill: 直接注册到 skills 字典中
        """
        if skill is None:
            return
        existing = self.skills.get(skill.name)
        if existing is not None:
            # 核心 skill 保护: 只有基线目录才能定义/覆盖核心 skill
            if skill.name in self.core_skills and not is_baseline:
                logger.warning(
                    f"拒绝覆盖核心 skill '{skill.name}': 仅基线目录可定义, "
                    f"忽略 {skill.source}(已存在: {existing.source})"
                )
                return
            # 普通 skill 覆盖: 后加载覆盖前加载, 记录日志以便排查
            logger.warning(f"skill '{skill.name}' 被覆盖: {skill.source} 覆盖 {existing.source}")
        self.skills[skill.name] = skill

    def build_messages(
        self, skill: str, *, include_identity: Optional[bool] = None,
        history: Optional[list] = None, **variables,
    ) -> list:
        """根据指定的 skill 组装 OpenAI 消息格式的消息列表。

        参数:
            skill: 要使用的 skill 名称, 必须是已加载的 skill
            include_identity: 是否包含 identity (覆盖 skill 自身的 include_identity 设置)
            history: 可选的历史消息列表, 会插入在 system 和 user 消息之间
            **variables: 用于填充 skill 模板的变量, 必须包含 skill.inputs 中的所有键

        返回:
            符合 OpenAI Chat API 格式的消息列表:
            [
                {"role": "system", "content": identity} (可选),
                ...history (可选),
                {"role": "user", "content": filled_template}
            ]

        异常:
            KeyError: skill 名称不存在
            ValueError: 缺少必要的模板变量, 或模板中存在未提供的占位符
        """
        # 验证 skill 是否存在
        if skill not in self.skills:
            raise KeyError(f"未知 skill: {skill}。已加载: {sorted(self.skills.keys())}")
        s = self.skills[skill]

        # 检查是否提供了所有需要的变量
        missing = [k for k in s.inputs if k not in variables]
        if missing:
            raise ValueError(f"skill '{skill}' 缺少变量: {missing}")

        # 执行模板替换
        try:
            user_content = s.template.format(**variables)
        except KeyError as e:
            raise ValueError(f"skill '{skill}' 模板中存在未提供的占位符 {e}") from None

        # 决定是否包含 identity (system message)
        # 调用者可通过 include_identity 参数覆盖 skill 自身的设置
        use_identity = s.include_identity if include_identity is None else include_identity

        # 组装消息列表
        messages: list = []
        if use_identity and self.identity:
            messages.append({"role": "system", "content": self.identity})
        if history:
            messages.extend(history)
        # user 消息放在最后
        messages.append({"role": "user", "content": user_content})
        return messages

    def list_skills(self) -> dict:
        """返回当前已加载的所有 skill 的概览信息。

        返回值:
            {skill名称: 来源文件路径} 的字典
        用于调试和查询当前系统中可用的 skill。
        """
        return {name: s.source for name, s in self.skills.items()}
