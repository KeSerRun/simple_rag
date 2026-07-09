"""Agent 事件总线：轻量级内部消息传递。

基于 nanobot 的 MessageBus 模式，适配同步 FastAPI 架构。
使用 queue.Queue 替代 asyncio.Queue（无需 async 改造）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue, Empty
from typing import Any, Optional


# ===== 消息类型 =====

@dataclass
class AgentEvent:
    """Agent 内部事件基类。"""
    type: str                    # 事件类型标识
    session_id: str              # 所属会话
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


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

class MessageBus:
    """Agent 内部消息总线。

    双队列模型：
      - inbound:  外部 → Agent 的消息（用户输入、子 agent 结果）
      - outbound: Agent → 外部的消息（LLM 回复、状态更新、错误）
    """

    def __init__(self):
        self.inbound: Queue[AgentEvent] = Queue()
        self.outbound: Queue[AgentEvent] = Queue()

    def publish(self, event: AgentEvent):
        """发布事件到总线。自动根据事件类型路由到对应队列。"""
        self.outbound.put(event)

    def publish_inbound(self, event: AgentEvent):
        """发布外部消息到 inbound 队列。"""
        self.inbound.put(event)

    def consume(self, timeout: float = 0.1) -> Optional[AgentEvent]:
        """从 inbound 消费一条消息。非阻塞。"""
        try:
            return self.inbound.get(timeout=timeout)
        except Empty:
            return None

    def read_outbound(self, timeout: float = 0.1) -> Optional[AgentEvent]:
        """从 outbound 读取一条消息。非阻塞。"""
        try:
            return self.outbound.get(timeout=timeout)
        except Empty:
            return None

    def clear_session_events(self, session_id: str):
        """清空指定会话的所有待处理事件。"""
        for q in (self.inbound, self.outbound):
            remaining = []
            while True:
                try:
                    ev = q.get_nowait()
                    if ev.session_id != session_id:
                        remaining.append(ev)
                except Empty:
                    break
            for ev in remaining:
                q.put(ev)


# ===== 全局实例 =====
# 应用启动时创建，各模块共享
bus = MessageBus()
