"""检查点系统: 工具执行状态的保存与恢复。

基于 nanobot 的 checkpoint 机制，支持三个保存时机:
  - awaiting_tools:  LLM 返回 tool_calls 后，执行前
  - tools_completed: 所有工具执行完毕后
  - final_response:  LLM 生成最终答案时

# ──

恢复逻辑:
  已完成的工具结果保留在列表中，未完成的工具调用替换为"中断"消息，
  确保 LLM 不会因缺失 tool result 而报错。

# ──

存储策略:
  检查点优先存储在内存 dict 中 (由 IntegratedSystem 持有)，
  跨会话持久化使用 data_store 的 session_tasks 机制。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from base.logger import logger


# ──


@dataclass
class Checkpoint:
    """单个检查点的数据结构。

    Attributes:
        phase: 保存阶段的标识 (awaiting_tools / tools_completed / final_response)
        iteration: 当前的 tool-call 轮次
        model: 使用的 LLM 模型名称
        assistant_message: LLM 返回的 assistant 消息 (含 tool_calls)
        completed_results: 已完成的工具执行结果列表
        pending_calls: 尚未执行的工具调用列表
    """
    phase: str
    iteration: int
    model: str
    assistant_message: Optional[dict] = None
    completed_results: list[dict] = None
    pending_calls: list[dict] = None


# ──


class CheckpointStore:
    """检查点存储管理器，提供内存 + data_store 双层持久化。

    用法示例:
        store = CheckpointStore(data_store)
        cp = Checkpoint(phase="awaiting_tools", iteration=1, model="gpt-4")
        store.save(session_id, cp)
        restored = store.load(session_id)

    # ──

    设计说明:
      - 内存 store 作为 L1 缓存，避免高频操作对 data_store 的压力
      - data_store 作为 L2 持久层，支持跨会话恢复
      - save / load / clear 三个操作在两层间保持一致性
    """

    _CHECKPOINT_KEY = "_agent_checkpoint"

    def __init__(self, data_store=None):
        """初始化 CheckpointStore。

        Args:
            data_store: 可选的数据存储后端，需要提供 get_session_tasks / save_session_tasks 接口。
                        传入 None 时只使用内存存储。
        """
        self._store: dict[str, dict] = {}
        self._data_store = data_store

    def _to_payload(self, cp: Checkpoint) -> dict:
        """将 Checkpoint 对象转换为可序列化的字典。

        Args:
            cp: 要转换的 Checkpoint 对象。

        Returns:
            包含检查点所有字段的普通字典，适用于 JSON 序列化及持久化存储。
        """
        return {
            "phase": cp.phase,
            "iteration": cp.iteration,
            "model": cp.model,
            "assistant_message": cp.assistant_message,
            "completed_results": cp.completed_results or [],
            "pending_calls": cp.pending_calls or [],
        }

    # ──

    def save(self, session_id: str, cp: Checkpoint) -> None:
        """保存检查点到内存和持久化存储。

        两步写入策略:
          1. 写入内存 store (L1 缓存，保证快速读写)
          2. 如果 data_store 可用，写入持久层 (L2，支持跨会话恢复)

        # ──

        持久化写入失败不会影响内存写入，仅记录 warning 日志。

        Args:
            session_id: 会话标识，作为检查点的键
            cp: 要保存的 Checkpoint 对象
        """
        payload = self._to_payload(cp)
        self._store[session_id] = payload
        if self._data_store:
            try:
                tasks = self._data_store.get_session_tasks(session_id) or {}
                tasks[self._CHECKPOINT_KEY] = payload
                self._data_store.save_session_tasks(session_id, tasks)
            except Exception as e:
                logger.warning(f"检查点持久化失败: {e}")
        logger.debug(f"检查点已保存: session={session_id[:8]} phase={cp.phase} iter={cp.iteration}")

    def load(self, session_id: str) -> Optional[Checkpoint]:
        """从内存或持久化存储中加载检查点。

        加载优先级:
          1. 优先从内存 store 读取 (L1，最高效)
          2. 内存未命中且 data_store 可用时，从持久层恢复 (L2)
          3. 如果持久层命中，自动回填到内存 store

        Args:
            session_id: 会话标识

        Returns:
            反序列化后的 Checkpoint 对象；如果不存在或解析失败则返回 None。
        """
        raw = self._store.get(session_id)
        if not raw and self._data_store:
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
        """清除指定会话的检查点 (内存 + 持久化)。

        Args:
            session_id: 要清除的会话标识。
                        同时从内存 store 和 data_store 中移除。
        """
        self._store.pop(session_id, None)
        if self._data_store:
            try:
                tasks = self._data_store.get_session_tasks(session_id) or {}
                tasks.pop(self._CHECKPOINT_KEY, None)
                self._data_store.save_session_tasks(session_id, tasks)
            except Exception:
                pass


# ──


def restore_messages(cp: Checkpoint) -> list[dict]:
    """从检查点恢复消息列表，供 LLM 继续推理。

    支持三种阶段的恢复:
      - awaiting_tools:  assistant 消息 + 已完成工具结果 + 未完成工具替换为"中断"消息
      - tools_completed: assistant 消息 + 所有工具结果
      - final_response:  只恢复 assistant 消息 (没有待处理的工具)

    # ──

    关键逻辑:
      pending_calls 中已被 completed_results 覆盖的 tool_call_id 不会重复添加，
      通过 seen_ids 集合去重，避免 LLM 收到重复的 tool result 导致协议错误。

    Args:
        cp: 要恢复的检查点对象

    Returns:
        恢复后的消息列表，可直接追加到 messages 序列中供 LLM 继续推理。
    """
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
