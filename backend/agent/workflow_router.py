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
_SECTION_ROUTING = re.compile(
    r"^##\s+路由规则\s*\n(.*?)(?=\n##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
# 匹配规则行: "- <name>: <kw1>, <kw2>, ..."
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
        self.workflow_dir: Path = Path(prompts_dir) / "workflow"
        # name → {"template": str, "description": str, "source": str}
        self._workflows: dict[str, dict] = {}
        # keyword (lower) → workflow_name
        self._keyword_map: dict[str, str] = {}

        self._load_workflows()

    # ─── 加载 ────────────────────────────────────────

    def _load_workflows(self):
        """从 route.md 解析路由规则 + 加载各 workflow 内容。"""
        route_file = self.workflow_dir / "route.md"
        if not route_file.is_file():
            logger.warning(f"route.md 不存在: {route_file}")
            return

        # 1. 解析路由规则（从 route.md 的 "## 路由规则" 区域）
        rules: dict[str, list[str]] = self._parse_routing_rules(route_file)
        if not rules:
            logger.warning("route.md 中未解析到任何路由规则")
            return

        # 2. 按规则名称加载对应 workflow 文件
        loaded = 0
        for wf_name, keywords in rules.items():
            wf_file = self.workflow_dir / f"{wf_name}.md"
            if not wf_file.is_file():
                logger.warning(
                    f"路由规则引用了 '{wf_name}', "
                    f"但文件不存在: {wf_file}"
                )
                continue

            try:
                text = wf_file.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                name = meta.get("name") or wf_file.stem

                # 用文件名做 key，确保与路由规则一致
                self._workflows[wf_name] = {
                    "template": body.strip(),
                    "description": str(meta.get("description", "")),
                    "source": str(wf_file.resolve()),
                }

                # 注册关键词
                _added = 0
                for kw in keywords:
                    kw_lower = kw.strip().lower()
                    if not kw_lower:
                        continue
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

        Returns:
            {workflow_name: [keyword1, keyword2, ...]}
        """
        text = route_file.read_text(encoding="utf-8")

        # 找到 "## 路由规则" 区域
        m = _SECTION_ROUTING.search(text)
        if not m:
            logger.warning("route.md 中未找到 '## 路由规则' 区域")
            return {}

        section_body = m.group(1)

        rules: dict[str, list[str]] = {}
        for match in _RULE_LINE.finditer(section_body):
            wf_name = match.group(1).strip()
            kw_raw = match.group(2).strip()
            # 分割关键词（按逗号，支持中文逗号）
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

        Args:
            query: 用户输入的查询文本。

        Returns:
            匹配的 workflow 名称；无匹配时返回 None。
        """
        if not query or not self._keyword_map:
            return None

        query_lower = query.lower()

        # 按关键词长度降序匹配（长关键词优先，避免短词误触）
        for kw, wf_name in sorted(
            self._keyword_map.items(),
            key=lambda x: -len(x[0]),
        ):
            if kw in query_lower:
                logger.info(
                    f"Workflow 路由匹配: 关键词={kw!r} → 工作流={wf_name}"
                )
                return wf_name

        return None

    # ─── 查询 ────────────────────────────────────────

    def get_workflow_content(self, name: str) -> Optional[str]:
        """获取工作流的指令模板（注入到 system message 的正文部分）。"""
        wf = self._workflows.get(name)
        if wf is None:
            logger.warning(f"Workflow '{name}' 不存在")
            return None
        return wf["template"]

    def list_workflows(self) -> dict:
        """列出所有已加载的工作流及其元信息。"""
        return {
            name: {
                "description": info["description"],
                "keywords": [
                    kw for kw, wf in self._keyword_map.items()
                    if wf == name
                ],
                "source": info["source"],
            }
            for name, info in self._workflows.items()
        }
