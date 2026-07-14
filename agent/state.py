"""Agent 运行时状态: tool-calling 循环的 AgentState 数据结构。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from base.config import conf
from base.logger import logger

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
        workflow: 回答工作流 workflow 名称。
        system_msg: 当前回合的 system message 内容。
    """
    messages: List[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = MAX_TOOL_ITER
    session_id: str = "default"
    partition: Optional[str] = None
    style: Optional[str] = None
    workflow: Optional[str] = None
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

    def add_user_query(self, content: str):
        """记录用户查询。"""
        self.messages.append({
            "role": "user",
            "content": content
        })

    def add_assistant_response(self, content: str, tool_calls: List[dict] = None):
        """记录 LLM 返回的 assistant 响应。"""
        if tool_calls:
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
        else:
            self.messages.append({
                "role": "assistant",
                "content": content,
            })
        self.iteration += 1

    def add_tool_result(self, tool_call_id: str, content: str):
        """记录单个工具执行结果。"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })


    # ── 对话历史持久化 ──
    def _save_turn_messages(self, session_id: str, data_store=None, start: int = 0) -> None:
        """保存本轮完整消息序列（含工具调用和结果）到历史记录。

        跳过 system 消息（由后续回合重建）和 start 之前的消息（已持久化的历史），
        只保存本轮新增的 user / assistant / tool 消息。

        注意：同一轮对话中可能被多次调用（每次工具迭代后保存一次），
        内部通过 _last_saved_idx 追踪已持久化的位置，避免重复保存。

        Args:
            session_id: 会话 ID。
            data_store: 数据存储实例。
            start: 本轮起始索引，之前的消息被视为已持久化的历史。
                   仅在首次保存时使用，后续调用使用内部追踪的 _last_saved_idx。
        """
        if data_store is None:
            return
        try:
            # 首次保存使用传入的 start，之后使用内部追踪的已保存位置
            save_from = getattr(self, '_last_saved_idx', start)
            # 确保 save_from 不小于 start（防止 start 被外部更新后倒退）
            save_from = max(save_from, start)
            turn_msgs = [m for m in self.messages[save_from:] if m.get("role") != "system"]
            if not turn_msgs:
                return
            data_store.insert_session_turn(session_id, turn_msgs)
            # 记录已保存到的位置，下次只保存新增的消息
            self._last_saved_idx = len(self.messages)
            logger.debug(f"已保存完整对话回合: session={session_id[:8]}, "
                         f"{len(turn_msgs)} 条消息, idx={self._last_saved_idx}")
        except Exception as e:
            logger.warning(f"保存完整对话回合失败: {e}")