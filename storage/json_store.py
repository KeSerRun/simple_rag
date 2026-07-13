# ── JSON 文件持久化存储 ──────────────────────────────────────────
"""基于 JSON 文件的持久化存储，覆盖用户/会话/对话历史三张表。

文件结构：
    data/json_store/users.json              - 用户表
    data/json_store/sessions.json           - 会话表
    data/json_store/history/                - 对话历史目录
        {session_id}.json                   -   每个会话一个文件
    data/json_store/archives/               - 归档目录
        {archive_id}.json                   -   归档文件
"""

import json

import os

import tempfile

import threading

from datetime import datetime


from base.config import conf
from base.logger import logger
from .base import BaseStore


class JSONFileStore(BaseStore):
    """基于 JSON 文件的持久化存储实现。

    提供用户管理、会话管理、对话历史 CRUD、任务持久化与归档功能。
    使用线程锁保证并发安全，采用原子写入策略避免数据损坏。

    Attributes:
        data_dir: 数据根目录。
        _json_dir: JSON 存储目录。
        _users_file: 用户表文件路径。
        _sessions_file: 会话表文件路径。
        _history_dir: 对话历史目录。
        _archive_dir: 归档目录。
        _lock: 线程锁。
    """

    def __init__(self, data_dir=None):
        """初始化 JSON 文件存储。

        Args:
            data_dir: 数据根目录；默认使用 conf.data_dir。
        """
        self.data_dir = data_dir or conf.data_dir

        self._json_dir = os.path.join(self.data_dir, 'json_store')

        self._users_file = os.path.join(self._json_dir, 'users.json')

        self._sessions_file = os.path.join(self._json_dir, 'sessions.json')

        self._history_dir = os.path.join(self._json_dir, 'history')

        self._archive_dir = os.path.join(self._json_dir, 'archives')

        self._lock = threading.Lock()

        self._migrate_from_old()

        self._ensure_dirs()

        self._init_files()

    # ── 目录与文件初始化 ──────────────────────────────────────────

    def _ensure_dirs(self):
        """确保所有必需的数据目录存在。"""
        os.makedirs(self._json_dir, exist_ok=True)

        os.makedirs(self._history_dir, exist_ok=True)

        os.makedirs(self._archive_dir, exist_ok=True)

    def _init_files(self):
        """确保 JSON 数据文件存在，不存在则创建空数组。"""
        for filepath in [self._users_file, self._sessions_file]:
            if not os.path.exists(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)

    def _migrate_from_old(self):
        """从旧的 data/ 平铺结构迁移到 data/json_store/ 目录。

        在 _ensure_dirs 之前调用，确保新空目录不会妨碍迁移。
        """
        migrated = False

        def _is_empty_dir(path):
            return os.path.isdir(path) and len(os.listdir(path)) == 0

        def _move(src, dst):

            nonlocal migrated

            if not os.path.exists(src):
                return

            if not os.path.exists(dst) or \
               (os.path.isfile(dst) and os.path.getsize(dst) <= 2) or \
               _is_empty_dir(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)

                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        os.rmdir(dst)
                    else:
                        os.remove(dst)
                os.rename(src, dst)

                logger.info(f"迁移 {src} → {dst}")
                migrated = True

        _move(os.path.join(self.data_dir, 'users.json'), self._users_file)

        _move(os.path.join(self.data_dir, 'sessions.json'), self._sessions_file)

        _move(os.path.join(self.data_dir, 'history'), self._history_dir)

        _move(os.path.join(self.data_dir, 'archives'), self._archive_dir)

        if migrated:
            logger.info("旧文件迁移完成，后续数据将写入新路径")

    # ── JSON 读写工具 ─────────────────────────────────────────────

    def _read_json(self, filepath):
        """读取 JSON 文件，返回 Python 对象。

        Args:
            filepath: JSON 文件路径。

        Returns:
            解析后的 Python 对象，文件不存在或为空时返回空列表。
        """
        with self._lock:
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                return []
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)

    def _write_json(self, filepath, data):
        """原子写入 JSON 文件（先写临时文件再替换）。

        Args:
            filepath: 目标文件路径。
            data: 要写入的 Python 对象。
        """
        with self._lock:
            dirname = os.path.dirname(filepath)
            os.makedirs(dirname, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, filepath)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise

    def _update_json(self, filepath, updater):
        """原子地读取 → 更新 → 写入 JSON 文件。整个过程中持锁。

        Args:
            filepath: 目标文件路径。
            updater: 接收当前数据并返回是否变更的回调函数。

        Returns:
            updater 的返回值。
        """
        with self._lock:
            dirname = os.path.dirname(filepath)
            os.makedirs(dirname, exist_ok=True)
            data = []
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            result = updater(data)
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, filepath)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
            return result

    def _get_next_id(self, items):
        """计算列表中下一个可用的 ID。

        Args:
            items: 包含 'id' 键的字典列表。

        Returns:
            当前最大 ID + 1，列表为空时返回 1。
        """
        ids = [item['id'] for item in items if 'id' in item]
        return max(ids, default=0) + 1

    # ── 用户管理 ──────────────────────────────────────────────────

    def insert_user(self, username, password, role='user'):
        """插入用户，已存在返回 False。

        Args:
            username: 用户名。
            password: 密码。
            role: 角色，默认 'user'。

        Returns:
            是否成功插入。
        """
        def updater(users):

            if any(u['username'].lower() == username.lower() for u in users):
                logger.debug(f"用户 '{username}' 已存在,跳过插入")
                return False

            users.append({
                'id': self._get_next_id(users),
                'username': username,
                'password': password,
                'role': role,
                'created_at': datetime.now().isoformat()
            })
            logger.info(f"成功插入用户: {username}")
            return True

        return self._update_json(self._users_file, updater)

    def delete_user(self, username):
        """删除用户，未找到返回 False。

        Args:
            username: 用户名。

        Returns:
            是否成功删除。
        """
        def updater(users):

            orig = list(users)

            users[:] = [u for u in users if u['username'] != username]

            if len(users) == len(orig):
                return False

            logger.info(f"成功删除用户: {username}")
            return True

        return self._update_json(self._users_file, updater)

    def check_user_credentials(self, username, password):
        """验证用户凭据。

        Args:
            username: 用户名。
            password: 密码。

        Returns:
            成功返回用户信息 dict，失败返回 False。
        """
        users = self._read_json(self._users_file)

        for u in users:
            if u['username'].lower() == username.lower() and u['password'] == password:
                logger.info(f"成功验证用户凭据: {username}")
                return {'username': u['username'], 'role': u['role']}
        return False

    def get_all_users(self, page=1, page_size=20):
        """分页查询所有用户。

        Args:
            page: 页码，从 1 开始。
            page_size: 每页数量。

        Returns:
            包含 {"items": [...], "total": N} 的字典。
        """
        users = self._read_json(self._users_file)

        total = len(users)

        start = (page - 1) * page_size

        end = start + page_size

        items = users[start:end]

        return {"items": items, "total": total}

    def update_user_role(self, username, new_role):
        """更新用户角色。

        Args:
            username: 用户名。
            new_role: 新角色。

        Returns:
            是否成功更新。
        """
        def updater(users):
            for u in users:
                if u['username'] == username:
                    u['role'] = new_role
                    logger.info(f"用户角色变更: {username} -> {new_role}")
                    return True
            return False

        return self._update_json(self._users_file, updater)

    def update_user_password(self, username, new_password):
        """更新用户密码。

        Args:
            username: 用户名。
            new_password: 新密码。

        Returns:
            是否成功更新。
        """
        def updater(users):
            for u in users:
                if u['username'] == username:
                    u['password'] = new_password
                    logger.info(f"用户密码已重置: {username}")
                    return True
            return False

        return self._update_json(self._users_file, updater)

    # ── 会话管理 ──────────────────────────────────────────────────

    def insert_session(self, session_id, username):
        """插入会话。

        Args:
            session_id: 会话 ID。
            username: 用户名。

        Returns:
            是否成功插入（False 表示已存在）。
        """
        def updater(sessions):

            if any(s['session_id'] == session_id for s in sessions):
                return False

            sessions.append({
                'session_id': session_id,
                'username': username,
                'created_at': datetime.now().isoformat()
            })
            logger.debug(f"成功插入用户会话: session_id={session_id}, username={username}")
            return True

        return self._update_json(self._sessions_file, updater)

    def delete_session(self, session_id):
        """删除会话。

        Args:
            session_id: 会话 ID。

        Returns:
            是否成功删除。
        """
        def updater(sessions):
            orig = list(sessions)

            sessions[:] = [s for s in sessions if s['session_id'] != session_id]

            if len(sessions) == len(orig):
                return False

            logger.debug(f"成功删除用户会话: session_id={session_id}")
            return True

        return self._update_json(self._sessions_file, updater)

    def fetch_sessions_by_username(self, username):
        """查询用户的所有会话，包含首条消息预览。

        Args:
            username: 用户名。

        Returns:
            会话 dict 列表，每项包含 id / created_at / first_msg；无数据返回 None。
        """
        sessions = self._read_json(self._sessions_file)

        result = []

        for s in sessions:
            if s['username'] == username:
                first_msg = ''

                history = self.get_session_history(s['session_id'])

                if history and len(history) > 0:
                    first_entry = history[0]
                    if first_entry.get('type') == 'turn':
                        msgs = first_entry.get('messages', [])
                        for m in msgs:
                            if m.get('role') == 'user' and m.get('content'):
                                first_msg = m['content'][:40]
                                break
                    else:
                        first_msg = first_entry.get('user', '')[:40]

                result.append({
                    'id': s['session_id'],
                    'created_at': s.get('created_at', ''),
                    'first_msg': first_msg,
                })

        return result if result else None

    # ── 对话历史 ──────────────────────────────────────────────────

    def get_session_history(self, session_id):
        """读取会话历史。

        Args:
            session_id: 会话 ID。

        Returns:
            历史消息列表，无数据返回 None。
        """
        history_file = os.path.join(self._history_dir, f'{session_id}.json')

        if not os.path.exists(history_file):
            return None

        history = self._read_json(history_file)

        logger.debug(f"session_id={session_id}, 成功查询对话历史")

        return history

    def insert_session_history(self, session_id, user, assistant):
        """插入一条对话记录。

        Args:
            session_id: 会话 ID。
            user: 用户消息。
            assistant: 助手回复。

        Returns:
            是否成功插入。
        """
        def updater(history):

            history.append({
                'id': self._get_next_id(history),
                'type': 'qa',
                'user': user,
                'assistant': assistant,
                'timestamp': datetime.now().isoformat()
            })
            logger.debug(f"session_id={session_id}, 成功插入对话历史")
            return True

        return self._update_json(
            os.path.join(self._history_dir, f'{session_id}.json'), updater)

    def insert_session_turn(self, session_id, messages: list) -> bool:
        """插入一轮完整的对话消息（含工具调用和结果）。

        Args:
            session_id: 会话 ID。
            messages: OpenAI 格式的消息列表。

        Returns:
            是否成功插入。
        """
        if not session_id:
            return False

        def updater(history):
            history.append({
                'id': self._get_next_id(history),
                'type': 'turn',
                'messages': messages,
                'timestamp': datetime.now().isoformat()
            })
            return True

        return self._update_json(
            os.path.join(self._history_dir, f'{session_id}.json'), updater)

    def insert_session_event(self, session_id, event_type, files):
        """记录会话级操作事件（上传/删除文件等）。

        Args:
            session_id: 会话 ID。
            event_type: 事件类型（'upload' / 'delete' / 'delete_all'）。
            files: 受影响的文件名列表。

        Returns:
            是否成功记录。
        """
        if not session_id:
            return False

        history_file = os.path.join(self._history_dir, f'{session_id}.json')

        history = []

        if os.path.exists(history_file):
            history = self._read_json(history_file)

        history.append({
            'id': self._get_next_id(history),
            'type': 'event',
            'event_type': event_type,
            'files': list(files or []),
            'timestamp': datetime.now().isoformat()
        })

        self._write_json(history_file, history)

        logger.debug(f"session_id={session_id}, 记录事件: {event_type} -> {files}")

        return True

    def delete_session_history(self, session_id):
        """删除整个会话历史。

        Args:
            session_id: 会话 ID。

        Returns:
            是否成功删除。
        """
        history_file = os.path.join(self._history_dir, f'{session_id}.json')

        if os.path.exists(history_file):
            os.remove(history_file)
            logger.debug(f"session_id={session_id}, 成功删除对话历史")
            return True

        return False

    # ── 会话任务 ──────────────────────────────────────────────────

    def save_session_tasks(self, session_id, tasks):
        """持久化会话任务数据（短期/长期任务）。

        Args:
            session_id: 会话 ID。
            tasks: 任务数据字典。
        """
        tasks_dir = os.path.join(self._json_dir, "session_tasks")
        os.makedirs(tasks_dir, exist_ok=True)
        file_path = os.path.join(tasks_dir, f"{session_id}.json")
        self._write_json(file_path, tasks)

    def get_session_tasks(self, session_id):
        """读取会话任务数据。

        Args:
            session_id: 会话 ID。

        Returns:
            任务数据字典，不存在返回 {"short": [], "long": []}。
        """
        file_path = os.path.join(self._json_dir, "session_tasks", f"{session_id}.json")
        if not os.path.exists(file_path):
            return {"short": [], "long": []}
        return self._read_json(file_path)

    def delete_session_tasks(self, session_id):
        """删除指定会话的任务数据。

        Args:
            session_id: 会话 ID。
        """
        file_path = os.path.join(self._json_dir, "session_tasks", f"{session_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)

    # ── 归档 ──────────────────────────────────────────────────────

    def insert_archive(self, session_id, summary, turns):
        """将历史轮次归档存储。

        Args:
            session_id: 会话 ID。
            summary: 归档摘要。
            turns: 对话轮次列表。

        Returns:
            生成的 archive_id。
        """
        import uuid as _uuid

        archive_id = f"arch_{session_id[:16]}_{_uuid.uuid4().hex[:8]}"

        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')

        os.makedirs(os.path.dirname(archive_file), exist_ok=True)

        self._write_json(archive_file, {
            'id': archive_id,
            'session_id': session_id,
            'summary': summary,
            'turns': turns,
            'created_at': datetime.now().isoformat(),
        })
        logger.info(f"归档创建: {archive_id} ({len(turns)} 轮)")
        return archive_id

    def get_archive(self, archive_id):
        """按 ID 读取归档。

        Args:
            archive_id: 归档 ID。

        Returns:
            归档内容字典，不存在返回 None。
        """
        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')

        if not os.path.exists(archive_file):
            logger.warning(f"归档不存在: {archive_id}")
            return None

        return self._read_json(archive_file)

    def delete_session_archives(self, session_id):
        """删除指定会话的所有归档文件。

        Args:
            session_id: 会话 ID。
        """
        prefix = f"arch_{session_id[:16]}_"
        if not os.path.isdir(self._archive_dir):
            return
        for fname in os.listdir(self._archive_dir):
            if fname.startswith(prefix) and fname.endswith('.json'):
                try:
                    os.remove(os.path.join(self._archive_dir, fname))
                except OSError:
                    pass

    def format_archive_turns(self, archive_id):
        """读取归档并格式化为 LLM 可读的文本。

        Args:
            archive_id: 归档 ID。

        Returns:
            格式化后的文本字符串，归档不存在返回 None。
        """
        data = self.get_archive(archive_id)

        if not data:
            return None

        lines = [f"[归档 {archive_id}] 以下为历史对话记录："]

        for t in data.get('turns', []):
            if t.get('user'):
                lines.append(f"用户：{t['user']}")
            if t.get('assistant'):
                lines.append(f"助手：{t['assistant']}")

        return "\n\n".join(lines)


if __name__ == "__main__":

    store = JSONFileStore()

    store.insert_user("test", "123456")

    print("Credentials check:", store.check_user_credentials("test", "123456"))
