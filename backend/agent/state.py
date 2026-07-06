"""Agent 状态机: 封装 tool-calling 循环的运行时状态。

职责:
  - 持有 messages (会话消息列表, 随 tool 调用自动增长)
  - 追踪迭代轮次, 到达上限后自动终结
  - 存储上下文参数 (partition / style)
  - 追踪短期/长期任务 (跨提问轮次持久化)

使用方式:
  state = AgentState(messages, partition=..., short_term_tasks=[...])
  while state.should_continue():
      ...
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
        short_term_tasks: 当前会话的短期任务列表（本轮对话的核心目标）
        long_term_tasks: 当前会话的长期任务列表（多轮对话中持续追踪的目标）
    """
    messages: List[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = MAX_TOOL_ITER
    max_calls_per_tool: int = None
    partition: Optional[str] = None
    style: Optional[str] = None
    short_term_tasks: List[str] = field(default_factory=list)
    long_term_tasks: List[str] = field(default_factory=list)
    _called_tools_history: set = field(default_factory=set)
    _tool_call_counts: dict = field(default_factory=dict)

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

    def check_and_record_tool_call(self, name: str, arguments: str) -> tuple[bool, str]:
        """检查工具调用是否合法。
        返回: (是否被拦截, 拦截原因或空字符串)
        """
        import json
        limit = self.max_calls_per_tool if self.max_calls_per_tool is not None else conf.max_calls_per_tool

        try:
            parsed_args = json.loads(arguments) if arguments else {}
            norm_args = json.dumps(parsed_args, sort_keys=True)
        except Exception:
            norm_args = arguments

        # 1. 检查调用次数上限 (防换词死循环)
        self._tool_call_counts.setdefault(name, 0)
        self._tool_call_counts[name] += 1
        if self._tool_call_counts[name] > limit:
            return True, f"(系统警告：为了防止死循环，工具 {name} 在本轮回答中已达到最大调用次数 {limit} 次上限。请停止搜索，立刻根据已有信息进行总结作答，若无答案请直接承认。)"

        # 2. 检查完全重复调用 (防原地打转)
        sig = f"{name}::{norm_args}"
        if sig in self._called_tools_history:
            return True, "(系统警告：您刚刚已经使用过完全相同的参数调用了此工具并获得了相同结果。请停止尝试，直接进行总结回答。)"

        self._called_tools_history.add(sig)
        return False, ""
