"""会话锁管理器: 为每个 session 提供互斥锁，保证单线程处理。

在 Web 服务或异步并发场景下，不同请求可能同时到达同一会话，
SessionLockManager 通过细粒度的 per-session 锁避免竞态条件。

# ──

设计说明:
  - 每个 session_id 对应一个独立的 threading.Lock
  - 使用全局锁 (self._global_lock) 保护锁字典的并发访问
  - 锁在首次 get_lock 时延迟创建，避免空转资源占用

# ──

使用示例:
    lock_mgr = SessionLockManager()
    with lock_mgr.get_lock(session_id):
        # 处理该会话的消息
        ...
    lock_mgr.remove_lock(session_id)  # 会话结束时清理
"""

from __future__ import annotations

import threading


# ──


class SessionLockManager:
    """会话锁管理器，确保每个 session 在同一时刻只有一个线程在处理。

    典型用法:
        lock_mgr = SessionLockManager()
        with lock_mgr.get_lock(session_id):
            # 安全的会话处理
            ...

    # ──

    注意:
      - 锁在使用完毕后需要显式调用 remove_lock 清理，避免内存泄漏
      - 长时间持有锁会阻塞该 session 的其他请求，业务层需控制处理时长
    """

    def __init__(self):
        """初始化 SessionLockManager，创建空的锁字典和全局锁。

        初始化状态:
          - _locks: 空字典，在 get_lock 调用时延迟创建锁实例
          - _global_lock: 保护锁字典并发访问的全局互斥锁
        """
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, session_id: str) -> threading.Lock:
        """获取或创建指定会话的互斥锁。

        如果会话尚未有锁，则自动创建；否则返回已有的锁实例。
        此操作是线程安全的 (通过 self._global_lock 保护临界区)。

        Args:
            session_id: 会话标识字符串

        Returns:
            对应会话的 threading.Lock 实例
        """
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def remove_lock(self, session_id: str):
        """移除指定会话的锁，释放资源。

        在会话结束后调用此方法清理，避免锁字典无限增长。
        如果会话不存在，静默忽略。

        Args:
            session_id: 要清理的会话标识
        """
        with self._global_lock:
            self._locks.pop(session_id, None)
