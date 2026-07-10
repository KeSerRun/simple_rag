"""Agent 生命周期钩子系统。

基于 nanobot 的 AgentHook 模式：
  - AgentHook: 抽象基类，定义生命周期事件
  - CompositeHook: 组合模式，按序派发事件

所有钩子方法都有默认空实现，子类只需重写需要的。
"""
from __future__ import annotations

from typing import Any, Optional
from base.logger import logger


class AgentHook:
    """Agent 生命周期钩子基类。

    子类重写感兴趣的事件方法即可。
    """

    def on_turn_start(self, session_id: str, question: str, **kwargs):
        """回合开始（收到用户问题时）。"""

    def on_turn_end(self, session_id: str, question: str, answer: str, **kwargs):
        """回合结束（生成答案后）。"""

    def on_tool_call(self, session_id: str, tool_name: str, args: dict):
        """工具被调用时。"""

    def on_tool_result(self, session_id: str, tool_name: str, result: str):
        """工具返回结果时。"""

    def on_error(self, session_id: str, error: str, recoverable: bool = False):
        """发生错误时。"""

    def on_state_change(self, session_id: str, from_state: str, to_state: str):
        """状态机状态变化时。"""

    def on_checkpoint(self, session_id: str, phase: str, iteration: int):
        """检查点保存时。"""


class CompositeHook(AgentHook):
    """组合钩子：将多个钩子组合成一个。

    按注册顺序依次调用每个钩子的方法。
    单个钩子抛异常不影响其他钩子。
    """

    def __init__(self):
        self._hooks: list[AgentHook] = []

    def add(self, hook: AgentHook) -> AgentHook:
        """注册一个钩子。"""
        if hook not in self._hooks:
            self._hooks.append(hook)
        return hook

    def remove(self, hook: AgentHook):
        """移除一个钩子。"""
        self._hooks.remove(hook)

    def _foreach(self, method_name: str, *args, **kwargs):
        """安全地遍历所有钩子调用方法。"""
        for hook in self._hooks:
            try:
                method = getattr(hook, method_name, None)
                if method:
                    method(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Hook {type(hook).__name__}.{method_name} 异常: {e}")

    # ── 代理方法 ──
    def on_turn_start(self, session_id: str, question: str, **kwargs):
        self._foreach("on_turn_start", session_id, question, **kwargs)

    def on_turn_end(self, session_id: str, question: str, answer: str, **kwargs):
        self._foreach("on_turn_end", session_id, question, answer, **kwargs)

    def on_tool_call(self, session_id: str, tool_name: str, args: dict):
        self._foreach("on_tool_call", session_id, tool_name, args)

    def on_tool_result(self, session_id: str, tool_name: str, result: str):
        self._foreach("on_tool_result", session_id, tool_name, result)

    def on_error(self, session_id: str, error: str, recoverable: bool = False):
        self._foreach("on_error", session_id, error, recoverable)

    def on_state_change(self, session_id: str, from_state: str, to_state: str):
        self._foreach("on_state_change", session_id, from_state, to_state)

    def on_checkpoint(self, session_id: str, phase: str, iteration: int):
        self._foreach("on_checkpoint", session_id, phase, iteration)


# ===== 内置日志钩子 =====

class LoggingHook(AgentHook):
    """日志钩子：将关键事件记录到日志。"""

    def on_turn_start(self, session_id: str, question: str, **kwargs):
        logger.info(f"[Hook] 回合开始 session={session_id[:8]} question={question[:40]}")

    def on_turn_end(self, session_id: str, question: str, answer: str, **kwargs):
        logger.info(f"[Hook] 回合结束 session={session_id[:8]} answer_len={len(answer)}")

    def on_tool_call(self, session_id: str, tool_name: str, args: dict):
        logger.debug(f"[Hook] 工具调用 {tool_name} session={session_id[:8]}")

    def on_tool_result(self, session_id: str, tool_name: str, result: str):
        logger.debug(f"[Hook] 工具结果 {tool_name} session={session_id[:8]} len={len(result)}")

    def on_checkpoint(self, session_id: str, phase: str, iteration: int):
        logger.debug(f"[Hook] 检查点 {phase} iter={iteration} session={session_id[:8]}")

    def on_error(self, session_id: str, error: str, recoverable: bool = False):
        logger.warning(f"[Hook] 错误 session={session_id[:8]} recoverable={recoverable}: {error[:60]}")

    def on_state_change(self, session_id: str, from_state: str, to_state: str):
        logger.debug(f"[Hook] 状态变化 {from_state} → {to_state} session={session_id[:8]}")
