"""Agent 事件总线：轻量级内部消息传递。

基于 nanobot 的 MessageBus 模式，适配同步 FastAPI 架构。
使用 queue.Queue 替代 asyncio.Queue（无需 async 改造）。
"""
from __future__ import annotations

import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ===== 消息类型 =====

@dataclass
class AgentEvent:
    """Agent 内部事件基类。"""
    type: str                    # 事件类型标识
    session_id: str              # 所属会话
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


@dataclass
class InboundMessage(AgentEvent):
    """进入 Agent 的用户消息。"""
    content: str = ""


@dataclass
class ToolCallEvent(AgentEvent):
    """工具调用事件。"""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)


@dataclass
class ToolResultEvent(AgentEvent):
    """工具结果事件。"""
    tool_name: str = ""
    result: str = ""


@dataclass
class LLMEvent(AgentEvent):
    """LLM 响应事件（token 或最终结果）。"""
    content: str = ""
    is_final: bool = False


@dataclass
class StateChangeEvent(AgentEvent):
    """状态变更事件。"""
    from_state: str = ""
    to_state: str = ""


@dataclass
class ErrorEvent(AgentEvent):
    """错误事件。"""
    error: str = ""
    recoverable: bool = False


# ===== 消息总线 =====
import threading
import queue

class MessageBus:
    """Agent 内部消息总线（基于 nanobot 模型，采用线程安全队列）。

    双队列模型：
      - inbound: 外部 → Agent 的消息（用户请求）
      - outbound: 按会话隔离的输出队列（LLM 事件流 → API 响应流）
    """

    def __init__(self):
        self.inbound: queue.Queue[dict] = queue.Queue()
        self._outbound_queues: dict[str, queue.Queue[AgentEvent]] = {}
        self._lock = threading.Lock()

    def get_outbound(self, session_id: str) -> queue.Queue[AgentEvent]:
        """获取指定会话的输出队列。"""
        with self._lock:
            if session_id not in self._outbound_queues:
                self._outbound_queues[session_id] = queue.Queue()
            return self._outbound_queues[session_id]

    def remove_outbound(self, session_id: str):
        """清理指定会话的输出队列。"""
        with self._lock:
            self._outbound_queues.pop(session_id, None)

    def publish(self, session_id: str, event: dict):
        """发布事件到指定会话的 outbound 队列。"""
        q = self.get_outbound(session_id)
        q.put(event)

    def publish_inbound(self, request: dict):
        """发布外部请求到 inbound 队列。"""
        self.inbound.put(request)

    def consume_inbound(self, timeout: float = 0.5) -> Optional[dict]:
        """从 inbound 消费一个请求。阻塞带超时。"""
        try:
            return self.inbound.get(timeout=timeout)
        except queue.Empty:
            return None


# ===== 全局实例 =====
# 应用启动时创建，各模块共享
agent_bus = MessageBus()
