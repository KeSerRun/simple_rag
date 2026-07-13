"""ContextBuilder: 从一个或多个 prompts/ 目录加载 identity 与 skills，按 skill 组装 OpenAI messages。

支持的 skill 布局:
  1. 扁平: <prompts_dir>/skills/<skill>.md
  2. 嵌套 (Claude Code 风格): <prompts_dir>/skills/<skill>/SKILL.md (或 skill.md)

# ──

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

# ──

多目录加载语义:
  - 第一个目录是"基线"，其 identity.md 是主身份；后续目录的 identity.md 仅被忽略并 log
  - 同名 skill 后加载的覆盖前面，并打 warning
  - 核心 skill (CORE_SKILLS) 只允许从基线目录加载，后续目录的同名 skill 被拒绝

# ──

调用示例:
    cb = ContextBuilder(["prompts", "third_party_skills"])
    messages = cb.build_messages("answer_with_context", context=ctx, query=q, history=hist)
    client.chat(messages=messages, model=...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from base.logger import logger

CORE_SKILLS: frozenset = frozenset()


# ──


@dataclass
class Skill:
    """表示一个加载完成的 prompt skill。

    每个 Skill 对应 prompts 目录下的一个 .md 文件，
    通过 YAML 风格的 frontmatter 定义元数据，markdown 正文作为模板。

    Attributes:
        name: skill 名称，用于在 build_messages 中引用
        description: 一句话描述，说明 skill 的用途
        inputs: 模板变量名列表，调用 build_messages 时必须提供这些变量
        template: markdown 正文模板，支持 {variable} 占位符替换
        include_identity: 是否在组装消息时自动包含 identity system message
        source: skill 文件来源路径 (绝对路径)，便于调试和溯源
        meta: frontmatter 中的原始元数据字典，保留所有自定义字段
    """
    name: str
    description: str
    inputs: list
    template: str
    include_identity: bool
    source: str = ""
    meta: dict = field(default_factory=dict)


# ──

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


# ──


def _strip_quotes(s: str) -> str:
    """去除字符串两端的引号 (单引号或双引号)。

    处理规则:
      如果字符串首尾字符相同且为单引号或双引号，则去除外层引号。
      否则直接返回原字符串。仅处理最外层，不会递归处理。

    Args:
        s: 原始字符串

    Returns:
        去除外层引号后的字符串
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


# ──


def _coerce_bool(s: str):
    """将字符串转换为 Python 的布尔值或数字类型。

    这是手写 YAML 解析器中的类型转换函数，用于将 frontmatter 中的
    字符串值转换为强类型:
      - "true"/"yes"/"on" (不区分大小写) → True
      - "false"/"no"/"off" (不区分大小写) → False
      - 数字字符串 → int 或 float
      - 其他 → 原样返回字符串

    Args:
        s: 输入字符串

    Returns:
        转换后的 Boolean / int / float 或原始字符串。
        此函数不会抛出异常，保证了 frontmatter 解析的健壮性。
    """
    low = s.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        if "." in low:
            return float(low)
        return int(low)
    except (ValueError, TypeError):
        pass
    return s


# ──


def parse_frontmatter(text: str) -> tuple:
    """解析带有 YAML 风格 frontmatter 的 markdown 文件。

    Args:
        text: 文件的完整文本内容

    Returns:
        (meta, body) 的二元组:
        - meta: 解析后的 frontmatter 字典 (键值对或列表)
        - body: frontmatter 之后的 markdown 正文

        如果不存在有效的 frontmatter (没有 "---" 包裹的元数据块)，
        则返回 ({}, 原始文本)。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta = m.group(1)
    body = m.group(2).strip("\n")
    return _parse_yaml_block(raw_meta), body


# ──


def _parse_yaml_block(text: str) -> dict:
    """手动解析 YAML 风格的键值对块 (不使用 PyYAML 依赖)。

    这是一个轻量级的 key-value 解析器，支持以下格式:
      1. 简单键值: key: value
      2. 列表键值: key:\n  - item1\n  - item2
      3. 多行字面块: key: |\n  line1\n  line2
      4. 注释: 以 # 开头的行会被跳过
      5. 空行: 作为分隔符处理

    # ──

    设计说明:
      不依赖 PyYAML 的目的是避免引入额外依赖，
      并且对于 prompt 管理这种简单场景已足够使用。
      如果 frontmatter 变得更加复杂，建议迁移到 PyYAML。

    Args:
        text: YAML 风格键值对的纯文本

    Returns:
        解析后的字典
    """
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "|":
            lines_joined = []
            i += 1
            if i < len(lines):
                indent = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines):
                    nxt = lines[i]
                    stripped = nxt.strip()
                    if stripped == "":
                        lines_joined.append("")
                        i += 1
                        continue
                    if len(nxt) - len(nxt.lstrip()) >= indent:
                        lines_joined.append(stripped)
                        i += 1
                    else:
                        break
            result[key] = " ".join(lines_joined)

        elif value:
            result[key] = _coerce_bool(_strip_quotes(value))
            i += 1

        else:
            items: list = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt.lstrip().startswith("-"):
                    items.append(_strip_quotes(nxt.lstrip()[1:].strip()))
                    i += 1
                else:
                    break
            result[key] = items
    return result


# ──


class ContextBuilder:
    """核心类：从 prompts 目录加载 identity 和 skills，组装 LLM 消息。

    支持多目录叠加加载:
      - 第一个目录是基线目录 (base directory)，必须存在
      - 后续目录作为增量/覆盖目录，可选的 (不存在只打 warning)
      - identity.md 只从基线目录加载，后续目录的 identity.md 被忽略
      - 同名 skill 后加载覆盖前面加载的
      - 核心 skill (core_skills) 只允许从基线目录加载

    # ──

    使用示例:
        cb = ContextBuilder("prompts")
        cb = ContextBuilder(["prompts", "team_skills"])
        messages = cb.build_messages("my_skill", query="你好", history=[])
    """

    def __init__(
        self,
        prompts_dirs: Union[str, Path, Iterable[Union[str, Path]]],
        core_skills: frozenset = CORE_SKILLS,
    ):
        """初始化 ContextBuilder。

        Args:
            prompts_dirs: 一个或多个 prompts 目录路径。
                          第一个是基线目录 (必须存在)，
                          后续为增量覆盖目录 (可选，不存在只打 warning)。
            core_skills: 受保护的核心 skill 集合，默认空集。
                         只有基线目录可以定义这些 skill。

        Raises:
            ValueError: prompts_dirs 为空列表
            FileNotFoundError: 基线目录不存在
        """
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

        self.identity: str = self._load_identity()

        for d in self.prompts_dirs[1:]:
            if not d.is_dir():
                logger.warning(f"prompts 目录不存在,跳过: {d}")
                continue
            if (d / "identity.md").exists():
                logger.info(f"第三方目录 {d} 中的 identity.md 被忽略(只允许基线目录定义身份)")

        self.skills: dict = {}
        for idx, d in enumerate(self.prompts_dirs):
            if not d.is_dir():
                continue
            is_baseline = idx == 0
            self._load_skills_from(d, is_baseline)

        logger.debug(
            f"ContextBuilder 就绪: identity={'是' if self.identity else '否'}, "
            f"skills={sorted(self.skills.keys())}"
        )

    # ──

    def _load_identity(self) -> str:
        """从基线目录加载身份文件 (identity.md)。

        identity.md 位于 prompts_dirs[0]/identity.md，
        如果文件不存在则返回空字符串。
        这个文件的内容会作为 system message 的基础身份定义。

        Returns:
            identity.md 的文本内容，文件不存在时返回空字符串。
        """
        f = self.prompts_dirs[0] / "identity.md"
        if not f.exists():
            return ""
        return f.read_text(encoding="utf-8").strip()

    def _load_skills_from(self, prompts_dir: Path, is_baseline: bool):
        """从 prompts_dir 加载技能 (skill) 到 self.skills 字典。

        目录布局:
          - 基线目录使用旧布局: prompts_dir/skills/ 下存放 .md 文件
          - 非基线目录 (第三方/增量目录) 支持两种布局:
            1) 也有 skills 子目录 → 旧布局
            2) 目录本身直接包含 .md 文件 → 新布局 (更灵活)

        # ──

        设计说明:
          这种设计使第三方扩展更灵活，无需强制创建 skills 子目录。
          如果目录既有 skills 子目录又有直接 .md 文件，优先使用 skills 子目录。

        Args:
            prompts_dir: 要加载的 prompts 目录路径
            is_baseline: 是否为基线目录 (影响 skill 覆盖规则)
        """
        skills_dir = prompts_dir / "skills"
        if skills_dir.is_dir():
            for file, fallback in self._scan_skills(skills_dir):
                self._register(self._load_one(file, fallback_name=fallback), is_baseline)
        elif not is_baseline:
            for file, fallback in self._scan_skills(prompts_dir):
                self._register(self._load_one(file, fallback_name=fallback), is_baseline)

    def _scan_skills(self, root: Path):
        """递归扫描目录树，查找所有 skill 定义文件。

        支持两种文件布局，按优先级处理:
          1. 扁平布局: 根目录下的 *.md 文件 (排除 SKILL.md/README.md 等约定文件)
             - 每个 .md 文件作为一个 skill，文件名 (不含扩展名) 作为 skill 名称
          2. 嵌套布局: 子目录中包含 SKILL.md 或 skill.md
             - 目录名作为 skill 名称，目录内的 SKILL.md/skill.md 作为 skill 内容
             - 子目录中其他 .md 文件会被忽略 (只有约定的文件名才被识别)
          3. 如果子目录既不是嵌套布局也不包含可识别的 skill 文件，
             则递归进入该子目录继续搜索 (深度优先)

        Yields:
            (file_path, fallback_name) 元组:
            - file_path: 找到的 skill 文件路径
            - fallback_name: 如果 frontmatter 中没有 name 字段时的默认 skill 名
        """
        for f in sorted(root.glob("*.md")):
            if f.name.lower() in ("skill.md", "readme.md"):
                continue
            yield f, f.stem

        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            skill_file = self._find_skill_file(sub)
            if skill_file is not None:
                yield skill_file, sub.name
            else:
                yield from self._scan_skills(sub)

    @staticmethod
    def _find_skill_file(directory: Path) -> Optional[Path]:
        """在目录中查找 skill 定义文件。

        按照约定，优先查找 SKILL.md，其次 skill.md (不区分大小写)。
        这是为了支持 Claude Code 风格的 skill 目录布局:
            skills/my_skill/SKILL.md
        其中 SKILL.md 是该 skill 的入口文件。

        Args:
            directory: 要搜索的目录

        Returns:
            找到的 skill 文件路径，如果都不存在则返回 None。
        """
        for name in ("SKILL.md", "skill.md"):
            f = directory / name
            if f.exists():
                return f
        return None

    def _load_one(self, file: Path, fallback_name: str) -> Optional[Skill]:
        """从单个 .md 文件加载一个 skill。

        Args:
            file: skill markdown 文件的路径
            fallback_name: 如果文件中 frontmatter 没有指定 name 字段时使用的默认名称

        Returns:
            解析成功返回 Skill 实例，解析失败返回 None。

        # ──

        解析逻辑:
          1. 读取文件内容
          2. 解析 frontmatter (YAML 风格键值对) 和 markdown 正文
          3. 从 frontmatter 中提取 name / description / inputs / include_identity 等字段
          4. 如果 frontmatter 不提供 name，则使用 fallback_name (通常是文件名或目录名)
          5. inputs 必须是列表类型，如果不是则自动包装为单元素列表
        """
        try:
            text = file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            name = meta.get("name") or fallback_name
            inputs = meta.get("inputs") or []
            if not isinstance(inputs, list):
                inputs = [inputs]
            return Skill(
                name=str(name),
                description=str(meta.get("description", "")),
                inputs=list(inputs),
                template=body,
                include_identity=bool(meta.get("include_identity", False)),
                source=str(file.resolve()),
                meta=meta,
            )
        except Exception as e:
            logger.error(f"加载 skill 失败 {file}: {e}")
            return None

    def _register(self, skill: Optional[Skill], is_baseline: bool):
        """注册一个 skill 到技能字典中。

        处理覆盖逻辑:
          1. 如果 skill 为 None (加载失败)，直接跳过
          2. 如果技能名已存在且名为核心 skill (core_skills):
             - 仅当是从基线目录加载时才允许覆盖
             - 从非基线目录加载时拒绝覆盖并打 warning
          3. 普通同名 skill: 后加载的覆盖前面的，并打 warning (提醒用户注意覆盖行为)
          4. 新 skill: 直接注册到 skills 字典中

        Args:
            skill: 要注册的 Skill 实例，None 时静默跳过
            is_baseline: 是否为基线目录加载 (影响核心 skill 的保护规则)
        """
        if skill is None:
            return
        existing = self.skills.get(skill.name)
        if existing is not None:
            if skill.name in self.core_skills and not is_baseline:
                logger.warning(
                    f"拒绝覆盖核心 skill '{skill.name}': 仅基线目录可定义, "
                    f"忽略 {skill.source}(已存在: {existing.source})"
                )
                return
            logger.warning(f"skill '{skill.name}' 被覆盖: {skill.source} 覆盖 {existing.source}")
        self.skills[skill.name] = skill

    # ──

    def build_messages(
        self, skill: str, *, include_identity: Optional[bool] = None,
        history: Optional[list] = None, **variables,
    ) -> list:
        """根据指定的 skill 组装 OpenAI 格式的消息列表。

        组装顺序:
          1. system 消息 (如果启用 identity)
          2. history 消息 (如果提供)
          3. user 消息 (模板填充后的结果)

        Args:
            skill: 要使用的 skill 名称，必须是已加载的 skill
            include_identity: 是否包含 identity (覆盖 skill 自身的 include_identity 设置)
            history: 可选的历史消息列表，会插入在 system 和 user 消息之间
            **variables: 用于填充 skill 模板的变量，必须包含 skill.inputs 中的所有键

        Returns:
            符合 OpenAI Chat API 格式的消息列表:
            [
                {"role": "system", "content": identity} (可选),
                ...history (可选),
                {"role": "user", "content": filled_template}
            ]

        Raises:
            KeyError: skill 名称不存在
            ValueError: 缺少必要的模板变量，或模板中存在未提供的占位符
        """
        if skill not in self.skills:
            raise KeyError(f"未知 skill: {skill}。已加载: {sorted(self.skills.keys())}")
        s = self.skills[skill]

        missing = [k for k in s.inputs if k not in variables]
        if missing:
            raise ValueError(f"skill '{skill}' 缺少变量: {missing}")

        try:
            user_content = s.template.format(**variables)
        except KeyError as e:
            raise ValueError(f"skill '{skill}' 模板中存在未提供的占位符 {e}") from None

        use_identity = s.include_identity if include_identity is None else include_identity

        messages: list = []
        if use_identity and self.identity:
            messages.append({"role": "system", "content": self.identity})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages

    def list_skills(self) -> dict:
        """返回当前已加载的所有 skill 的概览信息。

        Returns:
            {skill名称: 来源文件路径} 的字典。
            用于调试和查询当前系统中可用的 skill。
        """
        return {name: s.source for name, s in self.skills.items()}
