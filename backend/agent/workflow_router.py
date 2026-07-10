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
        # 用于匹配查询到工作流的关键词映射（route.md 已弃用，nanobot 渐进式加载替代）
        self._keywords: dict[str, str] = {}

        # 初始化时立即加载所有工作流
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

    def match(self, query: str) -> Optional[str]:
        """检测用户查询是否匹配某个 workflow（已弃用，使用 nanobot 渐进式加载）。"""
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

