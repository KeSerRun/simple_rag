"""检查点系统：工具执行状态的保存与恢复。

基于 nanobot 的 checkpoint 机制:
  - awaiting_tools:  LLM 返回 tool_calls 后，执行前
  - tools_completed: 所有工具执行完毕后
  - final_response:  LLM 生成最终答案时

恢复时，已完成的工具结果保留，未完成的替换为"中断"消息。

检查点存储在内存 dict 中（由 IntegratedSystem 持有），
跨会话持久化使用 session_tasks 或扩展 data_store。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from base.logger import logger


CHECKPOINT_KEY = "_agent_checkpoint"


@dataclass
class Checkpoint:
    """检查点数据。"""
    phase: str                      # awaiting_tools | tools_completed | final_response
    iteration: int                  # 迭代次数
    model: str                      # 模型名称
    assistant_message: Optional[dict] = None   # 含 tool_calls 的助手消息
    completed_results: list[dict] = None       # 已完成的工具结果
    pending_calls: list[dict] = None           # 未完成的工具调用


class CheckpointStore:
    """检查点存储（内存 + data_store 持久化）。"""

    _CHECKPOINT_KEY = "_agent_checkpoint"

    def __init__(self, data_store=None):
        self._store: dict[str, dict] = {}
        self._data_store = data_store

    def _to_payload(self, cp: Checkpoint) -> dict:
        return {
            "phase": cp.phase,
            "iteration": cp.iteration,
            "model": cp.model,
            "assistant_message": cp.assistant_message,
            "completed_results": cp.completed_results or [],
            "pending_calls": cp.pending_calls or [],
        }

    def save(self, session_id: str, cp: Checkpoint) -> None:
        payload = self._to_payload(cp)
        self._store[session_id] = payload
        # 持久化到 data_store
        if self._data_store:
            try:
                tasks = self._data_store.get_session_tasks(session_id) or {}
                tasks[self._CHECKPOINT_KEY] = payload
                self._data_store.save_session_tasks(session_id, tasks)
            except Exception as e:
                logger.warning(f"检查点持久化失败: {e}")
        logger.debug(f"检查点已保存: session={session_id[:8]} phase={cp.phase} iter={cp.iteration}")

    def load(self, session_id: str) -> Optional[Checkpoint]:
        raw = self._store.get(session_id)
        if not raw and self._data_store:
            # 从持久化恢复
            try:
                tasks = self._data_store.get_session_tasks(session_id) or {}
                raw = tasks.get(self._CHECKPOINT_KEY)
                if raw:
                    self._store[session_id] = raw
            except Exception:
                pass
        if not raw:
            return None
        try:
            return Checkpoint(
                phase=raw.get("phase", ""),
                iteration=raw.get("iteration", 0),
                model=raw.get("model", ""),
                assistant_message=raw.get("assistant_message"),
                completed_results=raw.get("completed_results", []),
                pending_calls=raw.get("pending_calls", []),
            )
        except Exception as e:
            logger.warning(f"检查点解析失败: {e}")
            return None

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        if self._data_store:
            try:
                tasks = self._data_store.get_session_tasks(session_id) or {}
                tasks.pop(self._CHECKPOINT_KEY, None)
                self._data_store.save_session_tasks(session_id, tasks)
            except Exception:
                pass


def restore_messages(cp: Checkpoint) -> list[dict]:
    """从检查点恢复消息列表。
    
    支持 phase: awaiting_tools / tools_completed / final_response。
    final_response 阶段时，只恢复 assistant_message（没有待处理的工具）。"""
    restored = []
    if cp.assistant_message:
        restored.append(cp.assistant_message)
    for msg in (cp.completed_results or []):
        restored.append(msg)
    seen_ids = {m.get("tool_call_id") for m in (cp.completed_results or []) if m.get("tool_call_id")}
    for tc in (cp.pending_calls or []):
        tc_id = tc.get("id") or tc.get("tool_call_id")
        if tc_id and tc_id not in seen_ids:
            restored.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": "Error: 任务在工具执行完成前被中断。",
            })
    return restored
