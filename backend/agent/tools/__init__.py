"""Agent 工具注册表入口。

handler 实现按职责拆分:
  - _kb_handlers.py    : 知识库检索 / 读全文 / 列文档 / 读归档
  - _web_handlers.py   : 联网搜索 / 读网页全文
  - _infra_handlers.py : 虚拟工具 / 基础设施工具

所有工具的注册集中管理在 registry.py 的 register_all_builtins() 中。
"""
from __future__ import annotations

from .registry import ToolContext, ToolRegistry

from base.logger import logger

# ── 创建全局注册表实例 ──────────────────────────
registry = ToolRegistry()

# ── 导入 handler 模块（先只加载函数，不注册） ──
import agent.tools._infra_handlers  # noqa: F401
import agent.tools._kb_handlers     # noqa: F401
import agent.tools._web_handlers    # noqa: F401

# ── 注册所有内建工具 ────────────────────────────
from .registry import register_all_builtins
register_all_builtins(registry)

# ── 安全导出 handler 函数 ───────────────────────
from ._infra_handlers import _exec_ask_clarification, _exec_spawn_subagent  # noqa: E402
from ._kb_handlers import (                            # noqa: E402
    _exec_search_kb, _exec_read_full_document,
    _exec_list_documents, _exec_read_archive,
    _exec_read_chunk_context, _exec_read_document_titles,
    _exec_read_section, _retrieve_and_dedup,
)
from ._web_handlers import (                       # noqa: E402
    _exec_web_search, _exec_read_url,
)

from ._format import SYSTEM_PARTITION, format_retrieved_chunks  # noqa: E402

# ── 向后兼容导出 ────────────────────────────────
TOOL_SCHEMAS = registry.schemas


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """向后兼容的 dispatch 函数。"""
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),
        partition=kwargs.get("partition"),
    )
    return registry.dispatch(name, args_json, ctx=ctx)
