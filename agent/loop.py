"""会话锁管理器：为每个 session 提供互斥锁。"""

from __future__ import annotations

import threading


class SessionLockManager:
    """会话锁管理器，确保每个 session 单线程处理。"""

    def __init__(self):
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, session_id: str) -> threading.Lock:
        """获取或创建指定会话的互斥锁。"""
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def remove_lock(self, session_id: str):
        """移除指定会话的锁（清理用）。"""
        with self._global_lock:
            self._locks.pop(session_id, None)
