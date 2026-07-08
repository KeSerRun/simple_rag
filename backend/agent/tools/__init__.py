"""Agent 工具注册表入口。

工具 handler 实现在 _handlers.py 中，
导入此模块时自动注册所有内建工具。
"""

from __future__ import annotations

from ..registry import ToolContext, ToolRegistry

from base.logger import logger

# 创建全局注册表实例（_handlers.py 中的注册函数会引用此实例）
registry = ToolRegistry()

# 导入 handlers 触发注册（必须先创建 registry，再 import _handlers）
import agent.tools._handlers  # noqa: F401

# 安全导出 handler 函数（此时 _handlers.py 已执行完毕）
from ._handlers import (                            # noqa: E402
    _exec_search_kb, _exec_read_full_document, _exec_web_search,
    _exec_list_documents, _exec_read_archive, _exec_ask_clarification,
    _exec_read_url, _retrieve_and_dedup,
)
from ._format import SYSTEM_PARTITION, format_retrieved_chunks  # noqa: E402

# ── 向后兼容导出 ────────────────────────────────
TOOL_SCHEMAS = registry.schemas


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """向后兼容的 dispatch 函数。"""
    from ._handlers import TOOL_SCHEMAS  # noqa: F811
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),
        partition=kwargs.get("partition"),
    )
    return registry.dispatch(name, args_json, ctx=ctx)
