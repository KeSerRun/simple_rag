"""Agent 状态机：显式的回合处理状态转换。

基于 nanobot 的 TurnState 模式，使用同步实现适配当前架构。
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Optional


class TurnState(Enum):
    """代理回合状态枚举。"""
    RESTORE = auto()    # 恢复/加载会话
    COMPACT = auto()    # 压缩/归档旧历史
    COMMAND = auto()    # 命令分发
    BUILD = auto()      # 构建 prompt
    RUN = auto()        # LLM + 工具循环
    SAVE = auto()       # 保存回合到历史
    RESPOND = auto()    # 组装响应
    DONE = auto()       # 完成


# 状态转换表
# 格式: {(当前状态, 事件): 下一状态}
TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
    (TurnState.RESTORE, "ok"): TurnState.COMPACT,
    (TurnState.COMPACT, "ok"): TurnState.COMMAND,
    (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
    (TurnState.COMMAND, "shortcut"): TurnState.DONE,
    (TurnState.BUILD, "ok"): TurnState.RUN,
    (TurnState.RUN, "ok"): TurnState.SAVE,
    (TurnState.RUN, "empty_response"): TurnState.RUN,     # 空响应重试（仍在 RUN 内）
    (TurnState.RUN, "length_recovery"): TurnState.RUN,    # 长度截断恢复
    (TurnState.RUN, "clarification"): TurnState.SAVE,     # 需要澄清，提前保存
    (TurnState.SAVE, "ok"): TurnState.RESPOND,
    (TurnState.RESPOND, "ok"): TurnState.DONE,
}


class StateMachine:
    """回合状态机。

    驱动循环:
      while ctx.state is not TurnState.DONE:
          handler = self._handlers[ctx.state]
          event = handler(ctx)
          ctx.state = TRANSITIONS[(ctx.state, event)]
    """

    def __init__(self):
        self._handlers: dict[TurnState, Callable] = {}

    def register(self, state: TurnState, handler: Callable):
        """注册状态处理器。"""
        self._handlers[state] = handler

    def run(self, ctx: StateContext) -> str:
        """驱动状态机运行。返回最终输出。"""
        while ctx.state is not TurnState.DONE:
            handler = self._handlers.get(ctx.state)
            if handler is None:
                raise RuntimeError(f"未注册状态处理器: {ctx.state}")

            event = handler(ctx)
            next_state = TRANSITIONS.get((ctx.state, event))
            if next_state is None:
                raise RuntimeError(
                    f"无效状态转换: {ctx.state.name} + event={event!r}"
                )

            ctx.state = next_state

        return ctx.output

    def step(self, ctx: StateContext) -> bool:
        """单步执行（用于流式/异步场景）。返回 True 表示仍在运行。"""
        if ctx.state is TurnState.DONE:
            return False

        handler = self._handlers.get(ctx.state)
        if handler is None:
            raise RuntimeError(f"未注册状态处理器: {ctx.state}")

        event = handler(ctx)
        next_state = TRANSITIONS.get((ctx.state, event))
        if next_state is None:
            raise RuntimeError(
                f"无效状态转换: {ctx.state.name} + event={event!r}"
            )

        ctx.state = next_state
        return ctx.state is not TurnState.DONE


class StateContext:
    """状态机上下文，在各状态之间传递数据。"""

    def __init__(self, session_id: str, question: str, **kwargs):
        self.session_id = session_id
        self.question = question
        self.state: TurnState = TurnState.RESTORE
        self.partition: Optional[str] = kwargs.get("partition")
        self.style: Optional[str] = kwargs.get("style")
        self.history: list = kwargs.get("history") or []

        # 状态间共享数据
        self.messages: list = []
        self.system_msg: str = ""
        self.answer: str = ""
        self.output: str = ""
        self.tool_results: list = []
        self.error: Optional[str] = None
        self.is_cancelled: bool = False

        # 运行时数据
        self.short_term_tasks: list = kwargs.get("short_term_tasks") or []
        self.long_term_tasks: list = kwargs.get("long_term_tasks") or []
        self.metadata: dict = {}  # 供 checkpoint 等使用
