"""Agent 状态机: 封装 tool-calling 循环的运行时状态。

职责:
  - 持有 messages (会话消息列表, 随 tool 调用自动增长)
  - 追踪迭代轮次, 到达上限后自动终结
  - 存储上下文参数 (partition / style)

使用方式:
  state = AgentState(messages, partition=...)
  while state.should_continue():
      resp = client.chat_with_tools(messages=state.messages, ...)
      if not resp["tool_calls"]:
          break
      state.add_assistant_response(resp["content"], resp["tool_calls"])
      for tc in resp["tool_calls"]:
          result = execute_tool(...)
          state.add_tool_result(tc["id"], result)
"""
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
        style: 回答风格 skill 名 (如 style-formal), None 表示默认
    """
    messages: List[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = MAX_TOOL_ITER
    partition: Optional[str] = None
    style: Optional[str] = None

    def should_continue(self) -> bool:
        """循环条件: 未达上限。"""
        return self.iteration < self.max_iterations

    def add_assistant_response(self, content: str, tool_calls: List[dict]):
        """把 LLM 的 content + tool_calls 拼成 assistant message 追加。"""
        self.messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
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
