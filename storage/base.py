# ── 数据存储抽象基类 ─────────────────────────────────────────────
"""数据存储抽象基类：定义统一接口，确保 json_store 等实现一致。

所有具体存储后端（JSON、数据库等）需实现此接口，
以保证上层业务逻辑的可替换性。
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class BaseStore(ABC):
    """数据存储抽象基类，定义统一的持久化接口。

    涵盖用户管理、会话管理、对话历史、归档等核心操作的抽象方法。
    """

    # ── 用户管理 ──────────────────────────────────────────────────

    @abstractmethod
    def insert_user(self, username: str, password: str, role: str = "user") -> bool:
        """插入用户。

        Args:
            username: 用户名。
            password: 密码。
            role: 角色，默认 'user'。

        Returns:
            是否成功插入（False 表示用户已存在）。
        """

    @abstractmethod
    def delete_user(self, username: str) -> bool:
        """删除用户。

        Args:
            username: 用户名。

        Returns:
            是否成功删除（False 表示用户未找到）。
        """

    @abstractmethod
    def check_user_credentials(self, username: str, password: str) -> Optional[dict]:
        """验证用户凭据。

        Args:
            username: 用户名。
            password: 密码。

        Returns:
            成功返回用户信息 dict，失败返回 None。
        """

    @abstractmethod
    def get_all_users(self) -> list:
        """返回所有用户列表。

        Returns:
            用户 dict 列表。
        """

    @abstractmethod
    def update_user_role(self, username: str, new_role: str) -> bool:
        """更新用户角色。

        Args:
            username: 用户名。
            new_role: 新角色。

        Returns:
            是否成功更新。
        """

    @abstractmethod
    def update_user_password(self, username: str, new_password: str) -> bool:
        """更新用户密码。

        Args:
            username: 用户名。
            new_password: 新密码。

        Returns:
            是否成功更新。
        """

    # ── 会话管理 ──────────────────────────────────────────────────

    @abstractmethod
    def insert_session(self, session_id: str, username: str) -> bool:
        """插入会话。

        Args:
            session_id: 会话 ID。
            username: 用户名。

        Returns:
            是否成功插入。
        """

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """删除会话。

        Args:
            session_id: 会话 ID。

        Returns:
            是否成功删除。
        """

    @abstractmethod
    def fetch_sessions_by_username(self, username: str) -> list:
        """查询用户的所有会话。

        Args:
            username: 用户名。

        Returns:
            会话 dict 列表。
        """

    # ── 对话历史 ──────────────────────────────────────────────────

    @abstractmethod
    def get_session_history(self, session_id: str) -> Optional[list]:
        """读取会话历史。

        Args:
            session_id: 会话 ID。

        Returns:
            历史消息列表，无数据返回 None。
        """

    @abstractmethod
    def insert_session_history(self, session_id: str, user: str, assistant: str) -> bool:
        """插入一条对话记录。

        Args:
            session_id: 会话 ID。
            user: 用户消息。
            assistant: 助手回复。

        Returns:
            是否成功插入。
        """

    @abstractmethod
    def insert_session_turn(self, session_id: str, messages: list) -> bool:
        """插入一轮完整的对话消息（含工具调用和结果）。

        Args:
            session_id: 会话 ID。
            messages: OpenAI 格式的消息列表。

        Returns:
            是否成功插入。
        """

    @abstractmethod
    def insert_session_event(self, session_id: str, event_type: str, files: list) -> bool:
        """插入会话事件（如上传、删除文件）。

        Args:
            session_id: 会话 ID。
            event_type: 事件类型（如 'upload' / 'delete'）。
            files: 受影响的文件名列表。

        Returns:
            是否成功插入。
        """

    @abstractmethod
    def delete_session_history(self, session_id: str) -> bool:
        """删除整个会话历史。

        Args:
            session_id: 会话 ID。

        Returns:
            是否成功删除。
        """

    # ── 会话任务 ──────────────────────────────────────────────────

    @abstractmethod
    def save_session_tasks(self, session_id: str, tasks: dict):
        """持久化会话任务数据。

        Args:
            session_id: 会话 ID。
            tasks: 任务数据字典。
        """

    @abstractmethod
    def get_session_tasks(self, session_id: str) -> dict:
        """读取会话任务数据。

        Args:
            session_id: 会话 ID。

        Returns:
            任务数据 dict，不存在返回 {}。
        """

    @abstractmethod
    def delete_session_tasks(self, session_id: str) -> None:
        """删除指定会话的任务数据。

        Args:
            session_id: 会话 ID。
        """

    # ── 归档 ──────────────────────────────────────────────────────

    @abstractmethod
    def insert_archive(self, session_id: str, summary: str, turns: list) -> str:
        """归档对话历史。

        Args:
            session_id: 会话 ID。
            summary: 归档摘要。
            turns: 对话轮次列表。

        Returns:
            生成的 archive_id。
        """

    @abstractmethod
    def get_archive(self, archive_id: str) -> Optional[dict]:
        """读取归档。

        Args:
            archive_id: 归档 ID。

        Returns:
            归档内容 dict，不存在返回 None。
        """

    @abstractmethod
    def format_archive_turns(self, archive_id: str) -> str:
        """将归档对话格式化为文本。

        Args:
            archive_id: 归档 ID。

        Returns:
            格式化后的文本字符串。
        """

    @abstractmethod
    def delete_session_archives(self, session_id: str) -> None:
        """删除指定会话的所有归档文件。

        Args:
            session_id: 会话 ID。
        """
