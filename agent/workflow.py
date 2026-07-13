"""WorkflowRouter: 从 prompts/workflow/ 目录加载工作流，供 LLM 按需使用。

工作流文件约定:
  - prompts/workflow/<name>.md — 工作流定义文件 (含 YAML frontmatter + 步骤内容)
  - prompts/workflow/route.md — 路由配置文件 (被 _load_workflows 跳过)

# ──

每个工作流文件支持以下 frontmatter 字段:
  - name: 工作流名称 (不提供则使用文件名)
  - description: 一句话描述，供 LLM 选择工作流时参考
  - max_tool_iter: 该工作流的最大 tool-call 轮次 (可选，覆盖全局配置)
  - always_load: 是否在每次构建 system message 时自动加载 (布尔值)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from base.logger import logger
from .context_builder import parse_frontmatter


# ──


class WorkflowRouter:
    """工作流路由器，管理 prompts/workflow/ 目录下的工作流文件。

    提供三种查询接口:
      - get_workflow_content: 按名称获取工作流模板内容，供 LLM 指令注入
      - get_workflow_summaries: 获取所有工作流的文本摘要，供 LLM 自主选择
      - get_workflow_list: 获取工作流列表，供前端 UI 展示

    # ──

    用法:
        router = WorkflowRouter("prompts")
        content = router.get_workflow_content("research")
        summary = router.get_workflow_summaries()
    """

    def __init__(self, prompts_dir: str):
        """初始化 WorkflowRouter，扫描并加载工作流文件。

        Args:
            prompts_dir: prompts 目录的路径字符串，工作流子目录自动定位为 {prompts_dir}/workflow/

        Raises:
            FileNotFoundError: workflows 目录不存在时，后续方法调用返回空结果
        """
        self.workflow_dir: Path = Path(prompts_dir) / "workflow"
        self._workflows: dict[str, dict] = {}

        self._load_workflows()

    # ──

    def _load_workflows(self):
        """从 workflow/ 目录扫描并加载所有工作流文件。

        扫描逻辑:
          1. 遍历 workflow/ 目录下所有 *.md 文件
          2. 跳过 route.md (路由配置文件，不视为工作流)
          3. 对每个 .md 文件执行 parse_frontmatter 解析 frontmatter + 正文
          4. 从 frontmatter 提取 name / description / max_tool_iter / always_load 等元数据
          5. 解析失败时记录 warning 并跳过该文件

        # ──

        加载后的工作流以字典形式存储在 self._workflows 中，
        键为工作流名称，值为包含 name / description / template / max_tool_iter / always_load 的字典。
        """
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

    # ──

    def get_workflow_content(self, name: str) -> Optional[str]:
        """获取指定工作流的指令模板内容。

        返回的模板字符串可直接注入到 system message 中，
        指导 LLM 按特定工作流步骤执行。

        Args:
            name: 工作流名称

        Returns:
            工作流的模板字符串 (markdown 正文)，如果名称不存在则返回 None。
        """
        wf = self._workflows.get(name)
        if wf is None:
            logger.warning(f"Workflow '{name}' 不存在")
            return None
        return wf["template"]

    def get_workflow_summaries(self) -> str:
        """构建所有工作流的摘要列表文本。

        返回格式:
            Available workflows
            <name1>: <description1>
            <name2>: <description2>
            ...

        该文本通常包含在 system message 中，供 LLM 了解可用工作流选项并自主选择。

        Returns:
            多行字符串，每行一个工作流的名称和描述。
        """
        lines = ["Available workflows"]
        for n, info in self._workflows.items():
            d = info.get("description", "")
            lines.append(f"{n}: {d}" if d else n)
        return "\n".join(lines)

    def get_workflow_list(self) -> list[dict]:
        """返回工作流列表，供前端 UI 使用。

        Returns:
            字典列表，每个字典包含以下字段:
            - name: 工作流名称
            - description: 工作流描述
            - always_load: 是否自动加载
        """
        result = []
        for name, info in self._workflows.items():
            result.append({
                "name": name,
                "description": info.get("description", ""),
                "always_load": info.get("always_load", False),
            })
        return result
