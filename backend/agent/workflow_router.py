# ===== 文件说明：WorkflowRouter 工作流路由器 =====
# 这个文件的功能是：从 route.md 文件中读取路由规则，根据用户输入的关键词，
# 找到对应的工作流（workflow），然后把工作流的内容返回给调用方。
"""WorkflowRouter: 从 route.md 解析路由规则，加载对应 workflow 执行。

架构变更（2026-07-02）：
  路由规则统一收归 route.md 管理，不再从各 workflow 文件的 frontmatter 读取 keywords。
  每个 workflow .md 只负责定义分步指令，route.md 负责定义触发条件。

工作流文件约定:
  - prompts/workflow/route.md  — 路由配置文件（唯一触发入口）
  - prompts/workflow/<name>.md — 工作流定义（仅步骤内容，不声明 keywords）
"""

# ===== 导入 Python 标准库模块 =====
# 从 __future__ 导入 annotations，作用是让所有类型注解都变成字符串形式（延迟求值），
# 这样在类方法中引用自身类型时就不会报错（比如 def foo(self) -> Foo 这种写法）。
from __future__ import annotations

# 导入 Python 的正则表达式模块，用来在字符串中做模式匹配和提取。
import re
# 从 pathlib 导入 Path 类，Path 是用来处理文件和目录路径的现代化工具，
# 比 os.path.join 更直观、更跨平台。
from pathlib import Path
# 从 typing 模块导入 Optional 类型提示，表示一个变量可以是某个类型，也可以是 None。
# 例如 Optional[str] 表示这个变量要么是字符串，要么是 None。
from typing import Optional

# ===== 导入项目内部模块 =====
# 从 base.logger 导入 logger 对象，这是项目统一的日志记录器，
# 用来在控制台或日志文件中输出信息、警告和错误。
from base.logger import logger

# 从当前目录下的 context_builder 模块，导入 parse_frontmatter 函数。
# 这个函数的作用是解析 Markdown 文件中 "---" 包裹的 YAML 元数据区（frontmatter），
# 返回元数据字典和去除元数据后的正文内容。
from .context_builder import parse_frontmatter


# ===== 定义正则表达式常量 =====
# 这是第一个正则表达式，用来从 route.md 文件中找到 "## 路由规则" 这个二级标题所在的区域。
# ─── 正则：匹配 "## 路由规则" 或 "## 路由规则" 区域 ─────
# 第一个正则：定位 route.md 中 "## 路由规则" 这一二级标题所在的区块。
# ^##\s+路由规则\s*\n   — 匹配以 "## 路由规则" 开头的行，标题前后允许空白。
# (.*?)                 — 非贪婪捕获该标题下的所有内容，直到满足后面的断言。
# (?=\n##\s|\Z)         — 前瞻断言：遇到下一个二级标题（\n## ）或文件末尾（\Z）时停止。
# re.MULTILINE          — 使 ^ 匹配每行开头，确保标题定位准确。
# re.DOTALL             — 使 . 匹配换行符，保证跨行捕获。
_SECTION_ROUTING = re.compile(
    # 正则表达式字符串：匹配 "## 路由规则" 标题，然后捕获其下的所有内容，
    # 直到遇到下一个 "## " 开头的二级标题或者文件末尾才停止。
    r"^##\s+路由规则\s*\n(.*?)(?=\n##\s|\Z)",
    # 启用 MULTILINE 模式让 ^ 匹配每行的开头，启用 DOTALL 模式让 . 匹配换行符。
    re.MULTILINE | re.DOTALL,
)
# 第二个正则：在 "## 路由规则" 区块内，逐行解析路由条目。
# 第二个正则表达式，用来逐行解析路由规则中的每一行条目。
# ^-                    — 行首的减号（Markdown 无序列表标记）。
# \s*(\S+?)\s*          — 捕获工作流名称（非空白字符，尽量短匹配）。
# :\s*                  — 冒号分隔符，冒号后允许空白。
# (.+)$                 — 捕获关键词列表（逗号分隔的字符串），直到行尾。
# re.MULTILINE          — 使 ^ 和 $ 匹配每行的开头和结尾。
_RULE_LINE = re.compile(r"^-\s*(\S+?)\s*:\s*(.+)$", re.MULTILINE)


# ===== 定义 WorkflowRouter 类 =====
class WorkflowRouter:
    """工作流路由器。

    加载 prompts/workflow/route.md 中的路由规则，
    按关键词匹配将用户查询路由到对应的工作流。

    Usage:
        router = WorkflowRouter("backend/prompts")
        wf_name = router.match("纳斯达克今天怎么样")
        if wf_name:
            content = router.get_workflow_content(wf_name)
            # → 注入到 system message
    """

    # ===== 初始化方法 =====
    def __init__(self, prompts_dir: str):
        # workflow 文件存放目录：<prompts_dir>/workflow/
        # 把传入的 prompts_dir 目录路径加上 "/workflow" 子目录，作为工作流文件存放的根目录。
        # 例如 prompts_dir = "backend/prompts"，那么 workflow_dir 就是 "backend/prompts/workflow"。
        self.workflow_dir: Path = Path(prompts_dir) / "workflow"
        # _workflows: 按工作流名称（即文件名不含 .md）索引，存储每个工作流的完整信息。
        # 每个 value 的格式: {
        #   "template": str,          # workflow 文件 body（去除 frontmatter 后的正文）
        #   "description": str,       # frontmatter 中的 description 字段
        #   "source": str,            # workflow 文件的绝对路径
        #   "max_tool_iter": int|None,        # frontmatter 中的最大工具迭代次数
        # }
        # 初始化一个空字典，用来存储所有加载的工作流信息。
        # 字典的 key 是工作流名称（字符串），value 是包含模板内容、描述、来源路径等信息的字典。
        self._workflows: dict[str, dict] = {}
        # _keyword_map: 关键词（小写）→ 工作流名称 的映射表。
        # 用于 match() 方法做快速查找，key 统一小写以实现大小写不敏感匹配。
        # 初始化一个空字典，用来存储关键词到工作流名称的映射关系。
        # 例如 {"美股": "USstocks", "纳斯达克": "USstocks", "A股": "CNstocks"}
        self._keyword_map: dict[str, str] = {}

        # 初始化时立即加载所有工作流
        # 在构造方法最后一步，立即调用 _load_workflows() 方法，
        # 这样创建 WorkflowRouter 对象时就会自动加载所有工作流，不需要手动调用。
        self._load_workflows()

    # ─── 加载 ────────────────────────────────────────

    # ===== 加载工作流的方法 =====
    def _load_workflows(self):
        """从 workflow/ 目录扫描加载所有工作流（nanobot 模式）。

        扫描 workflow/ 目录下所有 .md 文件（排除 route.md），
        解析 frontmatter，注册工作流。
        """
        # 扫描目录下所有 .md 文件
        for fpath in sorted(self.workflow_dir.glob("*.md")):
            if fpath.name == "route.md":
                continue
            try:
                # 读取文件内容并解析 frontmatter
                text = fpath.read_text(encoding="utf-8")
                meta, template = parse_frontmatter(text)
                wf_name = meta.get("name") or fpath.stem
                desc = meta.get("description") or ""

                # 注册工作流
                self._workflows[wf_name] = {
                    "name": wf_name,
                    "description": desc,
                    "template": template,
                    "max_tool_iter": meta.get("max_tool_iter"),
                    "always_load": meta.get("always_load", False),
                }
            except Exception as e:
                logger.warning(f"工作流加载失败 {fpath.name}: {e}")
                continue

        logger.info(
            f"WorkflowRouter 就绪: {len(self._workflows)} 个工作流"
        )
    def _parse_routing_rules(self, route_file: Path) -> dict[str, list[str]]:
        """解析 route.md 中 '## 路由规则' 区域的路由条目。

        格式:
            - <workflow_name>: <keyword1>, <keyword2>, ...

        解析过程:
          1. 用 _SECTION_ROUTING 正则提取 "## 路由规则" 标题下的整个区块。
          2. 用 _RULE_LINE 正则逐行匹配该区块中的无序列表项。
          3. 每行按 ": " 分割出工作流名称和关键词列表。
          4. 关键词列表按逗号（支持英文逗号和中文逗号）分割为单个关键词。

        Returns:
            {workflow_name: [keyword1, keyword2, ...]}
        """
        # 读取 route.md 文件的全部内容，使用 UTF-8 编码以支持中文。
        text = route_file.read_text(encoding="utf-8")

        # 找到 "## 路由规则" 区域
        # _SECTION_ROUTING 会匹配到第一个 "## 路由规则" 标题及其下方内容，
        # 直到遇到下一个二级标题或文件末尾。
        # 使用 _SECTION_ROUTING 正则表达式在全文搜索 "## 路由规则" 区域。
        m = _SECTION_ROUTING.search(text)
        # 检查是否找到了匹配的区域。
        if not m:
            # 如果没有找到 "## 路由规则" 区域，记录一条警告日志。
            logger.warning("route.md 中未找到 '## 路由规则' 区域")
            # 返回空字典，表示没有解析到任何路由规则。
            return {}

        # m.group(1) 是标题下的正文内容（不含标题行本身）
        # 获取正则匹配结果中的第一个捕获组，也就是 "## 路由规则" 标题下的正文内容。
        section_body = m.group(1)

        # 在区块内逐行解析路由条目
        # 初始化一个空字典，用来存储解析出的路由规则。
        rules: dict[str, list[str]] = {}
        # 使用 _RULE_LINE 正则表达式在区块内容中逐行匹配路由条目。
        for match in _RULE_LINE.finditer(section_body):
            # group(1) — 工作流名称（如 "USstocks"）
            # 从正则匹配结果中提取第一个捕获组：工作流名称，并去除两端空白字符。
            wf_name = match.group(1).strip()
            # group(2) — 逗号分隔的关键词列表（如 "美股, 纳斯达克, 道琼斯"）
            # 从正则匹配结果中提取第二个捕获组：关键词列表字符串，并去除两端空白字符。
            kw_raw = match.group(2).strip()
            # 分割关键词（按逗号，支持中文逗号）
            # re.split(r"[,，]", kw_raw) 同时支持英文逗号 "," 和中文逗号 "，"
            # 使用列表推导式，将原始关键词字符串按逗号（英文和中文都支持）分割，
            # 每个关键词去除两端空白，并且过滤掉空字符串。
            keywords = [
                k.strip()
                for k in re.split(r"[,，]", kw_raw)
                if k.strip()
            ]
            # 检查分割后的关键词列表是否为空。
            if not keywords:
                # 如果当前路由规则没有定义任何有效关键词，记录一条警告日志。
                logger.warning(f"路由规则 '{wf_name}' 没有关键词，跳过")
                # 跳过当前这条规则，继续处理下一条。
                continue
            # 将工作流名称和对应的关键词列表存入 rules 字典。
            rules[wf_name] = keywords

        # 记录一条 info 日志，说明从 route.md 解析出了多少条路由规则。
        logger.debug(f"从 route.md 解析到 {len(rules)} 条路由规则")
        # 返回解析出的路由规则字典。
        return rules

    # ─── 匹配 ────────────────────────────────────────

    # ===== 匹配用户查询的方法 =====
    def match(self, query: str) -> Optional[str]:
        """检测用户查询是否匹配某个 workflow 的领域。

        匹配策略 — 长词优先（Long-Word-First Matching）:
          1. 将用户查询转为小写。
          2. 将 _keyword_map 中所有关键词按长度降序排列。
          3. 逐个检查：如果关键词是查询字符串的子串，则视为匹配。
          4. 优先匹配更长的关键词，避免短关键词误触。
             例如：查询 "纳斯达克综合指数" 同时包含 "纳斯达克"（3字）和
             "纳斯达克综合"（5字），长词优先保证匹配更精确的工作流。

        这种简单子串匹配的优缺点：
          - 优点：速度快（O(n*k)），无需 NLP 模型，适合关键词路由场景。
          - 缺点：无法处理同义词、语义相似度等，规则完全依赖 route.md 中的关键词定义。

        Args:
            query: 用户输入的查询文本。

        Returns:
            匹配的 workflow 名称；无匹配时返回 None。
        """
        # 检查查询字符串是否为空，或者 _keyword_map 字典是否为空（没有注册任何关键词）。
        if not query or not self._keyword_map:
            # 如果查询为空或者没有关键词可匹配，直接返回 None。
            return None

        # 将用户输入的查询文本全部转换为小写，实现大小写不敏感的匹配。
        query_lower = query.lower()

        # 按关键词长度降序匹配（长关键词优先，避免短词误触）
        # sorted(..., key=lambda x: -len(x[0])) 对 (keyword, workflow_name) 对
        # 按 keyword 的长度取负值排序，即最长的 keyword 排在最前面。
        # 这样遍历时先检查长关键词，命中后立即返回，不再检查短关键词。
        # 遍历 _keyword_map 中的每一对（关键词, 工作流名称），
        # 并且按关键词长度从长到短排序（key=lambda x: -len(x[0]) 表示按关键词长度取负数排序）。
        for kw, wf_name in sorted(
            self._keyword_map.items(),
            key=lambda x: -len(x[0]),
        ):
            # 子串匹配：检查关键词是否出现在用户查询中
            # 判断关键词（小写）是否作为子串出现在用户查询（小写）中。
            if kw in query_lower:
                # 如果匹配成功，记录一条 info 日志，说明关键词匹配到了哪个工作流。
                logger.debug(
                    f"Workflow 路由匹配: 关键词={kw!r} → 工作流={wf_name}"
                )
                # 返回匹配到的工作流名称，结束匹配过程。
                return wf_name

        # 如果遍历完所有关键词都没有匹配到，返回 None，表示没有找到匹配的工作流。
        return None

    # ─── 查询 ────────────────────────────────────────

    # ===== 获取工作流模板内容的方法 =====
    def get_workflow_content(self, name: str) -> Optional[str]:
        """获取工作流的指令模板（注入到 system message 的正文部分）。

        这个方法在 rag_system.py 中被调用，获取到的 template 会被拼接到
        system prompt 中，作为 LLM 执行该工作流时的分步指令。
        """
        # 从 _workflows 字典中根据工作流名称获取对应的工作流信息字典。
        wf = self._workflows.get(name)
        # 检查是否找到了对应的工作流（如果 name 不存在，get 方法返回 None）。
        if wf is None:
            # 如果工作流不存在，记录一条警告日志。
            logger.warning(f"Workflow '{name}' 不存在")
            # 返回 None，表示没有找到对应的模板内容。
            return None
        # 返回工作流信息字典中的 "template" 字段，也就是工作流的分步指令正文。
        return wf["template"]

    # ===== 获取工作流配置参数的方法 =====
    def get_workflow_config(self, name: str) -> dict:
        """获取工作流的特殊配置参数（如最大调用次数等）。

        该方法被 rag_system.py 消费，用于获取工作流级别的覆盖配置。
        允许每个工作流独立控制 LLM 工具调用的轮次上限。

        消费方（rag_system.py）典型用法:
            config = router.get_workflow_config(wf_name)
            max_iter = config.get("max_tool_iter") or DEFAULT_MAX_TOOL_ITER

        如果工作流 frontmatter 中未定义这些字段，对应值为 None，
        消费方应使用自己的默认值兜底。
        """
        # 从 _workflows 字典中根据工作流名称获取对应的工作流信息字典。
        wf = self._workflows.get(name)
        # 检查是否找到了对应的工作流（如果 name 不存在，get 方法返回 None 或字典为空时也返回 None）。
        if not wf:
            # 如果工作流不存在，返回一个空字典，避免调用方拿到 None 后报错。
            return {}
        return {
            # 最大工具迭代轮数，如果 frontmatter 中没定义就是 None。
            "max_tool_iter": wf.get("max_tool_iter"),
            # 每个工具的最大调用次数，如果 frontmatter 中没定义就是 None。
        }

    # ===== 列出所有工作流的方法 =====
    # ===== get_workflow_summaries =====
    def get_workflow_summaries(self) -> str:
        """Build workflow summary for progressive loading."""
        lines = ["Available workflows"]
        for n, info in self._workflows.items():
            d = info.get("description", "")
            if d:
                lines.append(n + ": " + d)
            else:
                lines.append(n)
        return "\n".join(lines)

    def list_workflows(self) -> dict:
        """列出所有已加载的工作流及其元信息。

        反向查询 _keyword_map，找出每个工作流注册了哪些关键词。
        用于管理后台或调试接口展示当前路由规则。
        """
        # 使用字典推导式，遍历 _workflows 中所有已加载的工作流，构建返回结果。
        return {
            # key 是工作流名称，value 是该工作流的详细信息字典。
            name: {
                # description：工作流的描述信息（来自 frontmatter）。
                "description": info["description"],
                # 从 _keyword_map 中反向查找属于当前工作流的所有关键词
                # keywords：通过列表推导式从 _keyword_map 中反向查找，
                # 找出所有映射到当前工作流名称的关键词。
                "keywords": [
                    kw for kw, wf in self._keyword_map.items()
                    if wf == name
                ],
                # source：工作流文件的绝对路径，方便定位文件位置。
                "source": info["source"],
            }
            # 遍历 _workflows 字典，name 是工作流名称，info 是工作流信息字典。
            for name, info in self._workflows.items()
        }
