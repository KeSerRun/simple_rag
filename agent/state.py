"""Agent 运行时状态: tool-calling 循环的 AgentState 数据结构。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from base.config import conf

MAX_TOOL_ITER = conf.max_tool_iter


@dataclass
class AgentState:
    """Agent 工具调用循环的运行时状态。

    Attributes:
        messages: OpenAI 格式的 messages 列表。
        iteration: 当前已完成的 tool-call 轮次数。
        max_iterations: 允许的最大 tool-call 轮数。
        session_id: 当前会话的标识符。
        partition: 向量检索的分区键。
        style: 回答风格 skill 名称。
        system_msg: 当前回合的 system message 内容。
    """
    messages: List[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = MAX_TOOL_ITER
    session_id: str = "default"
    partition: Optional[str] = None
    style: Optional[str] = None
    system_msg: str = ""

    def should_continue(self) -> bool:
        """判断是否应继续 tool-calling 循环。

        检查迭代次数和消息总字符数是否仍在限制之内。

        Returns:
            未达任何限制返回 True，否则返回 False。
        """
        if self.iteration >= self.max_iterations:
            return False
        total = sum(
            len(str(m.get("content", "") or ""))
            for m in self.messages
            if m.get("role") != "system"
        )
        if total > conf.context_window_chars:
            return False
        return True

    def add_assistant_response(self, content: str, tool_calls: List[dict]):
        """记录 LLM 返回的 assistant 响应。"""
        self.messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls
            ],
        })
        self.iteration += 1

    def add_tool_result(self, tool_call_id: str, content: str):
        """记录单个工具执行结果。"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
