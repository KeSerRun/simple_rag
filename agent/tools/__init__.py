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

registry = ToolRegistry()

_HANDLERS_MODULES = []
for _importer, module_name, _ispkg in pkgutil.iter_modules(__path__):
    if module_name.endswith("_handlers") and not module_name.startswith("_"):
        continue
    if module_name.startswith("_") or module_name == "registry":
        continue
    _mod = importlib.import_module(f".{module_name}", __package__)
    _HANDLERS_MODULES.append(_mod)
    logger.debug(f"自动发现工具模块: {module_name}")

from .registry import register_all_builtins
register_all_builtins(registry)

__all__ = []
for _mod in _HANDLERS_MODULES:
    for _name in dir(_mod):
        if _name.startswith("_exec_") or _name.startswith("SYSTEM_") or _name.startswith("format_"):
            globals()[_name] = getattr(_mod, _name)
            __all__.append(_name)

from ._format import SYSTEM_PARTITION, format_retrieved_chunks

TOOL_SCHEMAS = registry.schemas


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """向后兼容的 dispatch 函数。

    封装 registry.dispatch，为旧代码提供无缝过渡接口。

    Args:
        name: 工具名称。
        args_json: JSON 字符串格式的工具参数。
        **kwargs: 额外关键字参数，可包含:
            vector_store: VectorStore 实例。
            partition: 分区标识字符串。

    Returns:
        工具执行结果字符串，失败时返回友好错误提示。
    """
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),
        partition=kwargs.get("partition"),
    )
    return registry.dispatch(name, args_json, ctx=ctx)
