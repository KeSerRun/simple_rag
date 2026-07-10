"""Agent 工具注册表入口。

handler 实现按职责拆分:
  - _kb_handlers.py    : 知识库检索 / 读全文 / 列文档 / 读归档
  - _web_handlers.py   : 联网搜索 / 读网页全文
  - _infra_handlers.py : 虚拟工具 / 基础设施工具

所有 _handlers.py 模块会被自动扫描发现并注册。
"""
from __future__ import annotations

import pkgutil
import importlib

from .registry import ToolContext, ToolRegistry

from base.logger import logger

# ── 创建全局注册表实例 ──────────────────────────
registry = ToolRegistry()

# ── 自动发现所有 _handlers 模块 ───────────────
_HANDLERS_MODULES = []
for _importer, module_name, _ispkg in pkgutil.iter_modules(__path__):
    if module_name.endswith("_handlers") and not module_name.startswith("_"):
        continue  # 跳过非 handler 模块（如 _format）
    if module_name.startswith("_") or module_name == "registry":
        continue  # 跳过内部模块
    _mod = importlib.import_module(f".{module_name}", __package__)
    _HANDLERS_MODULES.append(_mod)
    logger.debug(f"自动发现工具模块: {module_name}")

# ── 注册所有内建工具 ────────────────────────────
from .registry import register_all_builtins
register_all_builtins(registry)

# ── 自动导出 handler 函数 ─────────────────────────
__all__ = []
for _mod in _HANDLERS_MODULES:
    for _name in dir(_mod):
        if _name.startswith("_exec_") or _name.startswith("SYSTEM_") or _name.startswith("format_"):
            globals()[_name] = getattr(_mod, _name)
            __all__.append(_name)

# ── 显式导出 ─────────────────────────────────────
from ._format import SYSTEM_PARTITION, format_retrieved_chunks  # noqa: E402

TOOL_SCHEMAS = registry.schemas


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """向后兼容的 dispatch 函数。"""
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),
        partition=kwargs.get("partition"),
    )
    return registry.dispatch(name, args_json, ctx=ctx)
