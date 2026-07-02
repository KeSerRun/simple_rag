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

from rag.core.local_vector_store import VectorStore


@dataclass
class ToolContext:
    """传递给 tool handler 的运行时上下文。"""
    vector_store: VectorStore
    partition: Optional[str] = None


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


class ToolRegistry:
    """工具注册中心。"""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

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

        try:
            result = tool.handler(args, ctx)
            return result or ""
        except Exception as e:
            logger.error(f"工具 {name!r} 执行失败: {e}")
            return f"(工具执行失败: {e})"
