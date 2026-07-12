"""WorkflowRouter: 从 prompts/workflow/ 目录加载工作流，供 LLM 按需使用。

工作流文件约定:
  - prompts/workflow/<name>.md — 工作流定义（步骤内容）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from base.logger import logger
from .context_builder import parse_frontmatter


class WorkflowRouter:
    """工作流路由器。

    加载 prompts/workflow/ 目录下的工作流文件，
    提供按名称获取内容和摘要的能力。
    """

    def __init__(self, prompts_dir: str):
        self.workflow_dir: Path = Path(prompts_dir) / "workflow"
        self._workflows: dict[str, dict] = {}

        self._load_workflows()

    def _load_workflows(self):
        """从 workflow/ 目录扫描加载所有工作流。"""
        for fpath in sorted(self.workflow_dir.glob("*.md")):
            if fpath.name == "route.md":
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
                meta, template = parse_frontmatter(text)
                wf_name = meta.get("name") or fpath.stem
                desc = meta.get("description") or ""

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

    def get_workflow_content(self, name: str) -> Optional[str]:
        """获取工作流的指令模板。"""
        wf = self._workflows.get(name)
        if wf is None:
            logger.warning(f"Workflow '{name}' 不存在")
            return None
        return wf["template"]

    def get_workflow_summaries(self) -> str:
        """构建工作流摘要列表。"""
        lines = ["Available workflows"]
        for n, info in self._workflows.items():
            d = info.get("description", "")
            lines.append(f"{n}: {d}" if d else n)
        return "\n".join(lines)

    def get_workflow_list(self) -> list[dict]:
        """返回工作流列表（前端用）。"""
        result = []
        for name, info in self._workflows.items():
            result.append({
                "name": name,
                "description": info.get("description", ""),
                "always_load": info.get("always_load", False),
            })
        return result
