# ===== 模块文档字符串 =====
"""数据存储抽象基类：定义统一接口，确保 json_store 实现一致。"""

from abc import ABC, abstractmethod
from typing import List, Optional


class BaseStore(ABC):
    """数据存储抽象基类，定义统一的持久化接口。"""

    # ─── 用户管理 ─────────────────────────────────────
    @abstractmethod
    def insert_user(self, username: str, password: str, role: str = "user") -> bool:
        """插入用户，已存在返回 False。"""

    @abstractmethod
    def delete_user(self, username: str) -> bool:
        """删除用户，未找到返回 False。"""

    @abstractmethod
    def check_user_credentials(self, username: str, password: str) -> Optional[dict]:
        """验证用户凭据，成功返回用户信息 dict，失败返回 None。"""

    @abstractmethod
    def get_all_users(self) -> list:
        """返回所有用户列表。"""

    @abstractmethod
    def update_user_role(self, username: str, new_role: str) -> bool:
        """更新用户角色。"""

    @abstractmethod
    def update_user_password(self, username: str, new_password: str) -> bool:
        """更新用户密码。"""

    # ─── 会话管理 ─────────────────────────────────────
    @abstractmethod
    def insert_session(self, session_id: str, username: str) -> bool:
        """插入会话。"""

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """删除会话。"""

    @abstractmethod
    def fetch_sessions_by_username(self, username: str) -> list:
        """查询用户的所有会话。"""

    # ─── 对话历史 ─────────────────────────────────────
    @abstractmethod
    def get_session_history(self, session_id: str) -> Optional[list]:
        """读取会话历史，无数据返回 None。"""

    @abstractmethod
    def insert_session_history(self, session_id: str, user: str, assistant: str) -> bool:
        """插入一条对话记录。"""

    @abstractmethod
    def insert_session_event(self, session_id: str, event_type: str, files: list) -> bool:
        """插入会话事件（如上传、删除文件）。"""

    @abstractmethod
    def delete_session_history(self, session_id: str) -> bool:
        """删除整个会话历史。"""

    # ─── 会话任务 ─────────────────────────────────────
    @abstractmethod
    def save_session_tasks(self, session_id: str, tasks: dict):
        """持久化会话任务数据。"""

    @abstractmethod
    def get_session_tasks(self, session_id: str) -> dict:
        """读取会话任务数据，不存在返回 {"short": [], "long": []}。"""

    @abstractmethod
    def delete_session_tasks(self, session_id: str) -> None:
        """删除指定会话的任务数据。"""

    # ─── 归档 ─────────────────────────────────────────
    @abstractmethod
    def insert_archive(self, session_id: str, summary: str, turns: list) -> str:
        """归档对话历史，返回 archive_id。"""

    @abstractmethod
    def get_archive(self, archive_id: str) -> Optional[dict]:
        """读取归档，不存在返回 None。"""

    @abstractmethod
    def format_archive_turns(self, archive_id: str) -> str:
        """将归档对话格式化为文本。"""

    @abstractmethod
    def delete_session_archives(self, session_id: str) -> None:
        """删除指定会话的所有归档文件。"""
