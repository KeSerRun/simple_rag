"""Agent 主循环：状态机编排层。

基于 nanobot 的 AgentLoop 模式，在现有 RAGSystem 之上实现：
  RESTORE → COMPACT → COMMAND → BUILD → RUN → SAVE → RESPOND → DONE

RUN 状态内部仍使用现有的 _run_tool_loop_stream 工具循环，
但增加了检查点保存/恢复、事件发布和中断检测。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from base.config import conf
from base.logger import logger

from .state_machine import StateMachine, StateContext, TurnState
from .checkpoint import CheckpointStore, Checkpoint, restore_messages
from .bus import bus, AgentEvent, StateChangeEvent, ToolCallEvent, ErrorEvent


class AgentLoop:
    """Agent 主循环。

    编排状态机，管理会话生命周期。
    每个 session 对应一个 AgentLoop 实例。
    """

    def __init__(
        self,
        rag_system,
        data_store,
        checkpoints: CheckpointStore,
        session_id: str,
    ):
        self.rag = rag_system
        self.data_store = data_store
        self.checkpoints = checkpoints
        self.session_id = session_id

        # 状态机
        self.sm = StateMachine()
        self.sm.register(TurnState.RESTORE, self._state_restore)
        self.sm.register(TurnState.COMPACT, self._state_compact)
        self.sm.register(TurnState.COMMAND, self._state_command)
        self.sm.register(TurnState.BUILD, self._state_build)
        self.sm.register(TurnState.RUN, self._state_run)
        self.sm.register(TurnState.SAVE, self._state_save)
        self.sm.register(TurnState.RESPOND, self._state_respond)

        # 运行时数据
        self.ctx: Optional[StateContext] = None
        self._cancel_event = threading.Event()

    # ===== 公开接口 =====

    def run(self, question: str, **kwargs) -> str:
        """运行完整状态机，返回最终答案（非流式）。"""
        ctx = StateContext(
            session_id=self.session_id,
            question=question,
            **kwargs,
        )
        self.ctx = ctx
        result = self.sm.run(ctx)
        return result

    def run_stream(self, question: str, **kwargs):
        """运行状态机，逐事件 yield（流式）。

        Yield 格式与 _run_tool_loop_stream 兼容:
          {"type": "token", "text": "..."}
          {"type": "status", ...}
        """
        ctx = StateContext(
            session_id=self.session_id,
            question=question,
            **kwargs,
        )
        self.ctx = ctx
        self.sm.step(ctx)  # RESTORE
        self.sm.step(ctx)  # COMPACT
        self.sm.step(ctx)  # COMMAND → BUILD or DONE

        if ctx.state is TurnState.DONE:
            return

        self.sm.step(ctx)  # BUILD 已完成

        # RUN 状态：流式执行
        while ctx.state is TurnState.RUN:
            # 这里由外部驱动事件，每次 yield 后检查状态
            yield from self._run_stream_iteration(ctx)

    def cancel(self):
        """中断当前执行。"""
        self._cancel_event.set()
        if self.ctx:
            self.ctx.is_cancelled = True

    # ===== 状态处理器 =====

    def _state_restore(self, ctx: StateContext) -> str:
        """RESTORE：恢复会话状态和检查点。"""
        logger.debug(f"[RESTORE] session={self.session_id[:8]}")

        # 恢复检查点
        cp = self.checkpoints.load(self.session_id)
        if cp:
            logger.info(f"发现检查点: phase={cp.phase} iter={cp.iteration}, 尝试恢复")
            restored = restore_messages(cp)
            if restored:
                # 恢复的消息会在 BUILD 阶段追加
                ctx.metadata["restored_messages"] = restored
                logger.info(f"已恢复 {len(restored)} 条消息")

        # 发布状态事件
        bus.publish(StateChangeEvent(
            type="state_change",
            session_id=self.session_id,
            from_state="init",
            to_state="restore",
        ))
        return "ok"

    def _state_compact(self, ctx: StateContext) -> str:
        """COMPACT：检查是否需要压缩历史。"""
        return "ok"  # 暂不实现自动压缩

    def _state_command(self, ctx: StateContext) -> str:
        """COMMAND：检查是否为特殊命令。"""
        q = ctx.question.strip()
        if q in ("/exit", "/new", "/clear"):
            return "shortcut"
        if q.startswith("/"):
            return "shortcut"
        return "dispatch"

    def _state_build(self, ctx: StateContext) -> str:
        """BUILD：构建 system message + 消息列表。"""
        logger.debug(f"[BUILD] session={self.session_id[:8]}")
        return "ok"

    def _state_run(self, ctx: StateContext) -> str:
        """RUN：执行 LLM + 工具循环（非流式）。"""
        logger.debug(f"[RUN] session={self.session_id[:8]}")

        # 由外部 _run_tool_loop 实际执行
        return "ok"

    def _state_save(self, ctx: StateContext) -> str:
        """SAVE：保存回合到历史，清除检查点。"""
        self.checkpoints.clear(self.session_id)
        return "ok"

    def _state_respond(self, ctx: StateContext) -> str:
        """RESPOND：组装最终输出。"""
        ctx.output = ctx.answer
        return "ok"

    # ===== 流式迭代 =====

    def _run_stream_iteration(self, ctx: StateContext):
        """流式模式下的单次 RUN 迭代。"""
        # 流式执行委托给 RAGSystem
        # 使用现有的 _run_tool_loop_stream
        answer_iter = self.rag.generate_answer(
            ctx.question,
            stream=True,
            history=ctx.history or [],
            partition=ctx.partition,
            style=ctx.style,
            short_term_tasks=ctx.short_term_tasks,
            long_term_tasks=ctx.long_term_tasks,
            cancel_check=lambda: self._cancel_event.is_set(),
        )

        accumulated = []
        for event in answer_iter:
            if self._cancel_event.is_set():
                yield {"type": "status", "status": "cancelled"}
                # 保存检查点
                self._save_checkpoint_after_tools(ctx)
                return

            if event.get("type") == "token":
                accumulated.append(event.get("text", ""))
            yield event

        ctx.answer = "".join(accumulated)
        ctx.state = TurnState.SAVE
        self.sm.step(ctx)  # SAVE → RESPOND
        ctx.state = TurnState.RESPOND
        self.sm.step(ctx)  # RESPOND → DONE

    def _save_checkpoint_after_tools(self, ctx: StateContext):
        """在工具执行完毕后保存检查点。"""
        cp = Checkpoint(
            phase="tools_completed",
            iteration=0,
            model=conf.chat_model,
            completed_results=[],
        )
        self.checkpoints.save(self.session_id, cp)


# ===== 会话管理器 =====

class SessionManager:
    """会话管理器：追踪活跃会话的 AgentLoop 实例。

    对应 nanobot 的 self._active_tasks + self._pending_queues。
    """

    def __init__(self):
        self._loops: dict[str, AgentLoop] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_or_create(self, session_id: str, **kwargs) -> AgentLoop:
        """获取或创建会话的 AgentLoop。"""
        if session_id not in self._loops:
            from .integrated_system import IntegratedSystem
            # kwargs 应包含 rag_system, data_store, checkpoints
            loop = AgentLoop(
                rag_system=kwargs["rag_system"],
                data_store=kwargs["data_store"],
                checkpoints=kwargs["checkpoints"],
                session_id=session_id,
            )
            self._loops[session_id] = loop
            self._locks[session_id] = threading.Lock()
        return self._loops[session_id]

    def get_lock(self, session_id: str) -> threading.Lock:
        """获取会话锁（确保单线程处理）。"""
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def cancel_session(self, session_id: str) -> bool:
        """中断会话的当前执行。"""
        loop = self._loops.get(session_id)
        if loop:
            loop.cancel()
            return True
        return False

    def remove_session(self, session_id: str):
        """清理会话。"""
        self._loops.pop(session_id, None)
        self._locks.pop(session_id, None)
