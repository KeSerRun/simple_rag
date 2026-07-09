"""工具注册中心: ToolRegistry + ToolContext + ToolDef

设计目标:
  - 工具通过 registry.register() 注册，不再写 if/elif 链
  - 前后端兼容: registry.schemas 替代 TOOL_SCHEMAS, registry.dispatch 替代 execute_tool
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Optional

from base.logger import logger
from rag.vector_store import VectorStore


# ===== ToolContext：工具调用的运行时上下文 =====

@dataclass
class ToolContext:
    """传递给 tool handler 的运行时上下文。"""
    vector_store: VectorStore
    partition: Optional[str] = None
    data_store: Optional[object] = None
    session_id: str = ""  # 当前会话 ID，供 subagent 等使用


# ===== ToolDef：单个工具的定义 =====

@dataclass
class ToolDef:
    """单个工具的定义。"""
    name: str
    description: str
    parameters: dict
    handler: Callable
    source: str = ""

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ===== ToolRegistry：工具注册中心 =====

class ToolRegistry:
    """工具注册中心。"""

    # 并发安全的白名单（只读操作，可同时执行）
    _CONCURRENT_SAFE = {
        "search_knowledge_base", "read_chunk_context",
        "read_document_titles", "list_documents", "read_archive",
    }

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self.call_counts: dict[str, int] = {}  # 各工具累计调用次数

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[dict, ToolContext], str],
        source: str = "",
    ) -> ToolDef:
        if name in self._tools:
            logger.warning(f"工具 {name!r} 被覆盖注册")
        tool = ToolDef(name=name, description=description,
                       parameters=parameters, handler=handler, source=source)
        self._tools[name] = tool
        return tool

    @property
    def schemas(self) -> List[dict]:
        return [t.schema for t in self._tools.values()]

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    @classmethod
    def is_concurrent_safe(cls, tool_name: str) -> bool:
        """工具是否可以与其他工具并行执行。"""
        return tool_name in cls._CONCURRENT_SAFE

    @classmethod
    def partition_tool_batches(cls, tool_calls: list[dict]) -> list[list[dict]]:
        """将工具调用分批：并发安全的一批，不安全的一个一个来。

        对应 nanobot 的 _partition_tool_batches 模式。
        """
        concurrent = []
        sequential = []
        for tc in tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else ""
            if cls.is_concurrent_safe(name):
                concurrent.append(tc)
            else:
                sequential.append(tc)

        batches = []
        if concurrent:
            batches.append(concurrent)
        for tc in sequential:
            batches.append([tc])
        return batches

    def dispatch(self, name: str, args_json: str, *, ctx: ToolContext) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError as e:
            logger.warning(f"tool {name!r} 参数 JSON 解析失败 ({e})")
            return f"(工具调用失败: 参数 JSON 解析错误 {e})"

        tool = self._tools.get(name)
        if tool is None:
            logger.warning(f"未注册的工具: {name!r}, 已注册: {sorted(self._tools.keys())}")
            return f"(未知工具: {name})"

        # 参数校验
        error = self._validate_params(args, tool.parameters)
        if error:
            logger.warning(f"工具 {name!r} 参数校验失败: {error}")
            return f"(工具 {name!r} 参数错误: {error})"

        # 累计调用次数
        self.call_counts[name] = self.call_counts.get(name, 0) + 1

        logger.info(f"工具调用: {name} (累计: {self.call_counts[name]})")

        try:
            result = tool.handler(args, ctx)
            return result or ""
        except Exception as e:
            logger.error(f"工具 {name!r} 执行失败: {e}")
            return f"(工具执行失败: {e}。请尝试其他工具或根据已有信息回答。)"

    @staticmethod
    def _validate_params(args: dict, schema: dict) -> str | None:
        """轻量参数校验。返回错误消息或 None。"""
        props = schema.get("properties", {})
        required = schema.get("required", [])

        # 检查必填参数
        for key in required:
            if key not in args or args[key] is None:
                return f"缺少必填参数: {key}"
            val = args[key]
            if isinstance(val, str) and not val.strip():
                return f"参数 {key} 不能为空"

        # 检查参数类型（只校验 JSON Schema 中的 type）
        for key, val in args.items():
            if key in props:
                expected = props[key].get("type", "")
                if expected == "array" and not isinstance(val, (list, tuple)):
                    return f"参数 {key} 应为数组"
                elif expected == "integer" and not isinstance(val, int):
                    return f"参数 {key} 应为整数"
                elif expected == "boolean" and not isinstance(val, bool):
                    return f"参数 {key} 应为布尔值"

        return None


# ===== 内建工具注册入口 =====

def register_all_builtins(reg: ToolRegistry) -> None:
    """注册全部内建工具。由 __init__.py 在导入所有 handler 模块后调用。"""
    # 延迟导入 handler 函数（避免循环导入：registry → handler → __init__")
    from ._kb_handlers import (
        _exec_search_kb, _exec_read_full_document,
        _exec_list_documents, _exec_read_archive, _exec_read_chunk_context,
        _exec_read_document_titles, _exec_read_section,
    )
    from ._web_handlers import _exec_web_search, _exec_read_url
    from ._infra_handlers import (
        _exec_ask_clarification,
        _exec_spawn_subagent,
        _exec_set_goal,
        _exec_complete_goal,
    )

    # --- ask_user_for_clarification（虚拟工具） ---
    reg.register(
        name="ask_user_for_clarification",
        description=(
            "当用户请求模糊（指代不清、未指定具体文档）、且已有检索结果不足以推断时调用此工具。"
            "调用后对话中断，将你设置的 question 抛给用户等待补充。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "你需要向用户询问的具体问题，比如'请问您指的是本季度的哪一份财报？'",
                },
            },
            "required": ["question"],
        },
        handler=_exec_ask_clarification,
        source=__name__,
    )

    # --- spawn_subagent ---
    reg.register(
        name="spawn_subagent",
        description=(
            "将子任务派发给后台 sub-agent 并行执行。"
            "sub-agent 完成后结果会自动注入当前对话。"
            "适用于需要独立搜索、计算、比较、多角度分析的任务。"
            "task 是子任务的详细指令，allowed_tools 可选限制子 agent 可用的工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "子任务的完整指令，包括目标、要求和输出格式。",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：限制子 agent 可使用的工具列表，不传则可用全部工具。",
                },
            },
            "required": ["task"],
        },
        handler=_exec_spawn_subagent,
        source=__name__,
    )

    # --- set_goal ---
    reg.register(
        name="set_goal",
        description=(
            "设置当前会话的持续目标。目标信息会持续注入 system prompt 供后续对话参考。"
            "当用户交代了一个多轮对话才能完成的目标时调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "目标的详细描述，LLM 应该努力完成的目标。",
                },
            },
            "required": ["goal"],
        },
        handler=_exec_set_goal,
        source=__name__,
    )

    # --- complete_goal ---
    reg.register(
        name="complete_goal",
        description=(
            "标记当前目标已完成。当用户确认目标已完成时调用。"
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_exec_complete_goal,
        source=__name__,
    )

    # --- search_knowledge_base（首选检索工具） ---
    reg.register(
        name="search_knowledge_base",
        description=(
            "知识库检索，覆盖文本、表格、图片图表。"
            "支持多 query 并行检索；set search_system=false 仅搜用户文档。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "检索查询列表。简单问题 1 个；多焦点问题拆 2-5 个子查询。"
                        "用名词短语而非完整问句。"
                    ),
                },
                "search_system": {
                    "type": "boolean",
                    "description": "是否同时搜索系统公开文档。默认为 true（搜索全部）。设为 false 则只搜索用户自己的文档。",
                    "default": True,
                },
            },
            "required": ["queries"],
        },
        handler=_exec_search_kb,
        source=__name__,
    )

    # --- read_full_document ---
    reg.register(
        name="read_full_document",
        description=(
            "读取某篇文档的完整全文（Markdown 格式）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "要读取的文档文件名（含扩展名）。"
                        "必须是文档清单中出现的完整文件名，如 KD指标.pdf"
                    ),
                }
            },
            "required": ["filename"],
        },
        handler=_exec_read_full_document,
        source=__name__,
    )

    # --- read_url ---
    reg.register(
        name="read_url",
        description=(
            "读取指定网页的完整文字内容。仅限公开可访问的网页。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的网页完整 URL（必须以 http:// 或 https:// 开头）",
                },
            },
            "required": ["url"],
        },
        handler=_exec_read_url,
        source=__name__,
    )

    # --- web_search ---
    reg.register(
        name="web_search",
        description=(
            "搜索互联网获取最新信息（实时新闻、数据等知识库未覆盖的内容）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，用名词短语或简洁问句。",
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量（1-10）。",
                },
            },
            "required": ["query"],
        },
        handler=_exec_web_search,
        source=__name__,
    )

    # --- list_documents ---
    reg.register(
        name="list_documents",
        description=(
            "列出知识库中的文档清单。支持 pattern 过滤，list_system=false 仅列用户文档。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "可选的文件名关键词（如「KD」「财报」），不传则列出全部。",
                },
                "list_system": {
                    "type": "boolean",
                    "description": "是否同时列出系统公开文档。默认为 true（列出全部）。设为 false 则只列用户自己的文档。",
                    "default": True,
                },
            },
            "required": [],
        },
        handler=_exec_list_documents,
        source=__name__,
    )

    # --- read_archive ---
    reg.register(
        name="read_archive",
        description=(
            "读取被压缩归档的历史对话记录。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "archive_id": {
                    "type": "string",
                    "description": "归档 ID，格式如 arch_xxx。从历史摘要标记 #[archive_id] 中提取。",
                },
            },
            "required": ["archive_id"],
        },
        handler=_exec_read_archive,
        source=__name__,
    )

    # --- read_chunk_context ---
    reg.register(
        name="read_chunk_context",
        description=(
            "读取某一片段前后的相邻文档内容。"
            "片段内容不完整、图表标题需查看正文、同主题片段分散时使用。"
            "chunk_id 从检索结果标头 [id=] 获取。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "目标片段的 ID，从检索结果标头 [id=] 字段获取。",
                },
                "before": {
                    "type": "integer",
                    "default": 3,
                    "description": "向前取多少块（默认 3，最大 10）。",
                },
                "after": {
                    "type": "integer",
                    "default": 3,
                    "description": "向后取多少块（默认 3，最大 10）。",
                },
            },
            "required": ["chunk_id"],
        },
        handler=_exec_read_chunk_context,
        source=__name__,
    )

    # --- read_document_titles ---
    reg.register(
        name="read_document_titles",
        description=(
            "读取某篇文档的标题目录结构。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "文档文件名（含扩展名），如 KD指标.pdf",
                },
            },
            "required": ["source"],
        },
        handler=_exec_read_document_titles,
        source=__name__,
    )

    # --- read_section ---
    reg.register(
        name="read_section",
        description=(
            "根据文档名和标题关键词，读取该标题下的正文内容。"
            "heading 支持模糊匹配。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "文档文件名（含扩展名），如 KD指标.pdf",
                },
                "heading": {
                    "type": "string",
                    "description": "标题关键词，匹配任意级别的标题。如「第一章」「1.1 背景」「风险收益」",
                },
            },
            "required": ["source", "heading"],
        },
        handler=_exec_read_section,
        source=__name__,
    )
