"""WorkflowRouter: 从 route.md 解析路由规则，加载对应 workflow 执行。

架构变更（2026-07-02）：
  路由规则统一收归 route.md 管理，不再从各 workflow 文件的 frontmatter 读取 keywords。
  每个 workflow .md 只负责定义分步指令，route.md 负责定义触发条件。

工作流文件约定:
  - prompts/workflow/route.md  — 路由配置文件（唯一触发入口）
  - prompts/workflow/<name>.md — 工作流定义（仅步骤内容，不声明 keywords）
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from base.logger import logger

from .context_builder import parse_frontmatter


# ─── 正则：匹配 "## 路由规则" 或 "## 路由规则" 区域 ─────
# 第一个正则：定位 route.md 中 "## 路由规则" 这一二级标题所在的区块。
# ^##\s+路由规则\s*\n   — 匹配以 "## 路由规则" 开头的行，标题前后允许空白。
# (.*?)                 — 非贪婪捕获该标题下的所有内容，直到满足后面的断言。
# (?=\n##\s|\Z)         — 前瞻断言：遇到下一个二级标题（\n## ）或文件末尾（\Z）时停止。
# re.MULTILINE          — 使 ^ 匹配每行开头，确保标题定位准确。
# re.DOTALL             — 使 . 匹配换行符，保证跨行捕获。
_SECTION_ROUTING = re.compile(
    r"^##\s+路由规则\s*\n(.*?)(?=\n##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
# 第二个正则：在 "## 路由规则" 区块内，逐行解析路由条目。
# ^-                    — 行首的减号（Markdown 无序列表标记）。
# \s*(\S+?)\s*          — 捕获工作流名称（非空白字符，尽量短匹配）。
# :\s*                  — 冒号分隔符，冒号后允许空白。
# (.+)$                 — 捕获关键词列表（逗号分隔的字符串），直到行尾。
# re.MULTILINE          — 使 ^ 和 $ 匹配每行的开头和结尾。
_RULE_LINE = re.compile(r"^-\s*(\S+?)\s*:\s*(.+)$", re.MULTILINE)


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

    def __init__(self, prompts_dir: str):
        # workflow 文件存放目录：<prompts_dir>/workflow/
        self.workflow_dir: Path = Path(prompts_dir) / "workflow"
        # _workflows: 按工作流名称（即文件名不含 .md）索引，存储每个工作流的完整信息。
        # 每个 value 的格式: {
        #   "template": str,          # workflow 文件 body（去除 frontmatter 后的正文）
        #   "description": str,       # frontmatter 中的 description 字段
        #   "source": str,            # workflow 文件的绝对路径
        #   "max_tool_iter": int|None,        # frontmatter 中的最大工具迭代次数
        #   "max_calls_per_tool": int|None,   # frontmatter 中的单个工具最大调用次数
        # }
        self._workflows: dict[str, dict] = {}
        # _keyword_map: 关键词（小写）→ 工作流名称 的映射表。
        # 用于 match() 方法做快速查找，key 统一小写以实现大小写不敏感匹配。
        self._keyword_map: dict[str, str] = {}

        # 初始化时立即加载所有工作流
        self._load_workflows()

    # ─── 加载 ────────────────────────────────────────

    def _load_workflows(self):
        """从 route.md 解析路由规则 + 加载各 workflow 内容。

        加载策略（route.md → xxx.md）:
          1. 只读取 route.md 这一入口文件，从中解析出所有路由规则。
          2. 每条规则中声明了工作流名称和对应的触发关键词。
          3. 按工作流名称去 workflow 目录下加载同名的 .md 文件。
          4. 这是一种"声明式"路由设计：修改路由只需编辑 route.md，
             无需改动代码，新增工作流也只需新建 .md 文件并在 route.md 加一行。
        """
        route_file = self.workflow_dir / "route.md"
        if not route_file.is_file():
            logger.warning(f"route.md 不存在: {route_file}")
            return

        # 1. 解析路由规则（从 route.md 的 "## 路由规则" 区域）
        #    rules 格式: {"工作流名": ["关键词1", "关键词2", ...]}
        rules: dict[str, list[str]] = self._parse_routing_rules(route_file)
        if not rules:
            logger.warning("route.md 中未解析到任何路由规则")
            return

        # 2. 按规则名称加载对应 workflow 文件
        #    遍历每一条路由规则，找到对应的 .md 文件并加载其内容。
        loaded = 0
        for wf_name, keywords in rules.items():
            # 根据规则中声明的工作流名称拼接文件路径
            wf_file = self.workflow_dir / f"{wf_name}.md"
            if not wf_file.is_file():
                # 如果 route.md 中引用了某个工作流，但实际文件不存在，
                # 记录警告并跳过，避免系统启动时崩溃。
                logger.warning(
                    f"路由规则引用了 '{wf_name}', "
                    f"但文件不存在: {wf_file}"
                )
                continue

            try:
                text = wf_file.read_text(encoding="utf-8")
                # parse_frontmatter 解析 YAML 格式的 frontmatter（--- 包裹的元数据区）
                # 返回 (meta_dict, body_str) 二元组：
                #   - meta: frontmatter 中的键值对（description, max_tool_iter 等）
                #   - body: 去除 frontmatter 后的剩余正文（即工作流的分步指令）
                meta, body = parse_frontmatter(text)
                # 如果 frontmatter 中显式声明了 name 则使用，否则以文件名（不含 .md）作为名称
                name = meta.get("name") or wf_file.stem

                # 用文件名做 key，确保与路由规则一致
                # 注意：这里使用 wf_name（来自 route.md 规则中的名称）作为 key，
                # 而不是 meta.get("name")，以保证路由规则和 _workflows 字典的 key 一致。
                self._workflows[wf_name] = {
                    "template": body.strip(),
                    "description": str(meta.get("description", "")),
                    "source": str(wf_file.resolve()),
                    # 从 frontmatter 中读取 max_tool_iter 和 max_calls_per_tool，
                    # 这两个参数控制 LLM 在本次工作流中可以执行多少轮工具调用。
                    # 如果 frontmatter 中未定义，则值为 None，由调用方决定默认值。
                    "max_tool_iter": meta.get("max_tool_iter"),
                    "max_calls_per_tool": meta.get("max_calls_per_tool"),
                }

                # 注册关键词：将 route.md 中该规则声明的所有关键词
                # 逐一添加到 _keyword_map 中，供后续 match() 匹配使用。
                _added = 0
                for kw in keywords:
                    # 统一转为小写，实现大小写不敏感的匹配
                    kw_lower = kw.strip().lower()
                    if not kw_lower:
                        continue
                    # 检查关键词冲突：如果同一个关键词已经被映射到另一个工作流，
                    # 则记录警告，并用当前工作流覆盖。这意味着 route.md 中
                    # 后定义的同名关键词会覆盖先定义的。
                    if kw_lower in self._keyword_map:
                        logger.warning(
                            f"关键词 '{kw}' 已映射到 '{self._keyword_map[kw_lower]}', "
                            f"被 '{wf_name}' 覆盖"
                        )
                    self._keyword_map[kw_lower] = wf_name
                    _added += 1

                loaded += 1
                logger.info(
                    f"已加载 workflow [{wf_name}] {_added} 个关键词"
                    f" ({wf_file.name})"
                )
            except Exception as e:
                logger.error(f"加载 workflow 失败 {wf_file}: {e}")

        logger.info(
            f"WorkflowRouter 就绪: {loaded} 个工作流, "
            f"{len(self._keyword_map)} 个路由关键词"
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
        text = route_file.read_text(encoding="utf-8")

        # 找到 "## 路由规则" 区域
        # _SECTION_ROUTING 会匹配到第一个 "## 路由规则" 标题及其下方内容，
        # 直到遇到下一个二级标题或文件末尾。
        m = _SECTION_ROUTING.search(text)
        if not m:
            logger.warning("route.md 中未找到 '## 路由规则' 区域")
            return {}

        # m.group(1) 是标题下的正文内容（不含标题行本身）
        section_body = m.group(1)

        # 在区块内逐行解析路由条目
        rules: dict[str, list[str]] = {}
        for match in _RULE_LINE.finditer(section_body):
            # group(1) — 工作流名称（如 "USstocks"）
            wf_name = match.group(1).strip()
            # group(2) — 逗号分隔的关键词列表（如 "美股, 纳斯达克, 道琼斯"）
            kw_raw = match.group(2).strip()
            # 分割关键词（按逗号，支持中文逗号）
            # re.split(r"[,，]", kw_raw) 同时支持英文逗号 "," 和中文逗号 "，"
            keywords = [
                k.strip()
                for k in re.split(r"[,，]", kw_raw)
                if k.strip()
            ]
            if not keywords:
                logger.warning(f"路由规则 '{wf_name}' 没有关键词，跳过")
                continue
            rules[wf_name] = keywords

        logger.info(f"从 route.md 解析到 {len(rules)} 条路由规则")
        return rules

    # ─── 匹配 ────────────────────────────────────────

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
        if not query or not self._keyword_map:
            return None

        query_lower = query.lower()

        # 按关键词长度降序匹配（长关键词优先，避免短词误触）
        # sorted(..., key=lambda x: -len(x[0])) 对 (keyword, workflow_name) 对
        # 按 keyword 的长度取负值排序，即最长的 keyword 排在最前面。
        # 这样遍历时先检查长关键词，命中后立即返回，不再检查短关键词。
        for kw, wf_name in sorted(
            self._keyword_map.items(),
            key=lambda x: -len(x[0]),
        ):
            # 子串匹配：检查关键词是否出现在用户查询中
            if kw in query_lower:
                logger.info(
                    f"Workflow 路由匹配: 关键词={kw!r} → 工作流={wf_name}"
                )
                return wf_name

        return None

    # ─── 查询 ────────────────────────────────────────

    def get_workflow_content(self, name: str) -> Optional[str]:
        """获取工作流的指令模板（注入到 system message 的正文部分）。

        这个方法在 rag_system.py 中被调用，获取到的 template 会被拼接到
        system prompt 中，作为 LLM 执行该工作流时的分步指令。
        """
        wf = self._workflows.get(name)
        if wf is None:
            logger.warning(f"Workflow '{name}' 不存在")
            return None
        return wf["template"]

    def get_workflow_config(self, name: str) -> dict:
        """获取工作流的特殊配置参数（如最大调用次数等）。

        该方法被 rag_system.py 消费，用于获取工作流级别的覆盖配置。
        返回值中的 max_tool_iter 和 max_calls_per_tool 会覆盖系统默认值，
        允许每个工作流独立控制 LLM 工具调用的轮次上限。

        消费方（rag_system.py）典型用法:
            config = router.get_workflow_config(wf_name)
            max_iter = config.get("max_tool_iter") or DEFAULT_MAX_TOOL_ITER
            max_calls = config.get("max_calls_per_tool") or DEFAULT_MAX_CALLS_PER_TOOL

        如果工作流 frontmatter 中未定义这些字段，对应值为 None，
        消费方应使用自己的默认值兜底。
        """
        wf = self._workflows.get(name)
        if not wf:
            return {}
        return {
            "max_tool_iter": wf.get("max_tool_iter"),
            "max_calls_per_tool": wf.get("max_calls_per_tool"),
        }

    def list_workflows(self) -> dict:
        """列出所有已加载的工作流及其元信息。

        反向查询 _keyword_map，找出每个工作流注册了哪些关键词。
        用于管理后台或调试接口展示当前路由规则。
        """
        return {
            name: {
                "description": info["description"],
                # 从 _keyword_map 中反向查找属于当前工作流的所有关键词
                "keywords": [
                    kw for kw, wf in self._keyword_map.items()
                    if wf == name
                ],
                "source": info["source"],
            }
            for name, info in self._workflows.items()
        }
