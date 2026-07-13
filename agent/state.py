"""Agent 运行时状态: tool-calling 循环的 AgentState 数据结构。

维护 tool-calling 循环中的核心状态:
  - messages 列表: 累积所有对话消息 (system / user / assistant / tool)
  - iteration 计数器: 跟踪已执行的 tool-call 轮次
  - should_continue: 边界检查，判断是否达到最大轮次

# ──

依赖:
  - base.config.conf.max_tool_iter: 全局最大 tool-call 轮次配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from base.config import conf

MAX_TOOL_ITER = conf.max_tool_iter


# ──


@dataclass
class AgentState:
    """Agent 工具调用循环的运行时状态。

    在 tool-calling 循环中逐步累积消息和迭代信息，
    每次 LLM 调用和工具执行都会更新此状态。

    # ──

    Attributes:
        messages: OpenAI 格式的 messages 列表，按顺序包含 system / history / user / assistant / tool
        iteration: 当前已完成的 tool-call 轮次数
        max_iterations: 允许的最大 tool-call 轮数，默认从全局配置读取
        session_id: 当前会话的标识符
        partition: 向量检索的分区键 (通常为用户标识，用于多租户隔离)
        style: 回答风格 skill 名称 (由路由阶段决定)
        tool_exhausted: 是否因达到上限而提前终止 (非正常结束标志)
        system_msg: 当前回合的 system message 内容
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

        检查当前 iteration 是否仍在 max_iterations 限制之内，
        用于循环条件判断和 while 循环终止。

        Returns:
            如果当前 iteration 未达到 max_iterations，返回 True；否则返回 False。
        """
        return self.iteration < self.max_iterations

    # ──

    def add_assistant_response(self, content: str, tool_calls: List[dict]):
        """记录 LLM 返回的 assistant 响应到消息列表。

        将 LLM 返回的内容和工具调用列表格式化为 OpenAI 标准的 assistant 消息，
        同时自动递增 iteration 计数器。

        # ──

        消息格式:
            {
                "role": "assistant",
                "content": <文本>,
                "tool_calls": [
                    {
                        "id": "...",
                        "type": "function",
                        "function": {"name": "...", "arguments": "..."}
                    }
                ]
            }

        Args:
            content: LLM 返回的文本内容 (可能为空字符串)
            tool_calls: 工具调用列表，每个元素需包含 id / name / arguments 字段
        """
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
        """记录单个工具执行结果到消息列表。

        将工具的执行结果格式化为 OpenAI 标准的 tool 消息，
        插入到 messages 列表尾部，与对应的 tool_call_id 匹配。

        Args:
            tool_call_id: 对应的工具调用 ID (与 assistant message 中的 tool_calls.id 匹配)
            content: 工具执行的返回内容 (字符串格式)
        """
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
