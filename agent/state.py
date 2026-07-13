"""Agent 运行时状态：tool-calling 循环的 AgentState。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from base.config import conf

MAX_TOOL_ITER = conf.max_tool_iter


@dataclass
class AgentState:
    """Agent 状态, 在 tool-calling 循环中逐步累积。

    Attributes:
        messages: OpenAI 格式的 messages 列表 (system + history + user + assistant + tool)
        iteration: 当前已完成的 tool-call 轮次
        max_iterations: 最多允许的 tool-call 轮数
        partition: 向量检索分区 (用户名)
        style: 回答风格 skill 名
        tool_exhausted: 是否因达上限而非正常结束
        system_msg: 当前回合的 system message
    """
    messages: List[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = MAX_TOOL_ITER
    session_id: str = "default"
    partition: Optional[str] = None
    style: Optional[str] = None
    tool_exhausted: bool = False
    system_msg: str = ""

    def should_continue(self) -> bool:
        return self.iteration < self.max_iterations

    def add_assistant_response(self, content: str, tool_calls: List[dict]):
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
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
