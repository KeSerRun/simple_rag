import json
import os
import tempfile
import threading
from datetime import datetime

from base.config import conf
from base.logger import logger


class JSONFileStore:
    """基于 JSON 文件的持久化存储,覆盖用户/会话/对话历史三张表

    文件结构:
        data/users.json              - 用户表
        data/sessions.json           - 会话表
        data/history/                - 对话历史目录
            {session_id}.json        -   每个会话一个文件
    """

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or conf.data_dir
        self._users_file = os.path.join(self.data_dir, 'users.json')
        self._sessions_file = os.path.join(self.data_dir, 'sessions.json')
        self._history_dir = os.path.join(self.data_dir, 'history')
        # 全局锁(写操作串行化,防止 uvicorn 多线程并发写)
        self._lock = threading.Lock()
        self._ensure_dirs()
        self._init_files()

    def _ensure_dirs(self):
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self._history_dir, exist_ok=True)

    def _init_files(self):
        for filepath in [self._users_file, self._sessions_file]:
            if not os.path.exists(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)

    # --- internal helpers --------------------------------------------------

    def _read_json(self, filepath):
        with self._lock:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)

    def _write_json(self, filepath, data):
        """原子写入"""
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
        """原子地读取 → 更新 → 写入 JSON 文件。整个过程中持锁。"""
        with self._lock:
            dirname = os.path.dirname(filepath)
            os.makedirs(dirname, exist_ok=True)
            data = []
            if os.path.exists(filepath):
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
        return max((item['id'] for item in items), default=0) + 1

    # --- 用户 --------------------------------------------------------------

    def insert_user(self, username, password, role='user'):
        def updater(users):
            if any(u['username'] == username for u in users):
                logger.info(f"用户 '{username}' 已存在,跳过插入")
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
        def updater(users):
            orig = list(users)
            users[:] = [u for u in users if u['username'] != username]
            if len(users) == len(orig):
                return False
            logger.info(f"成功删除用户: {username}")
            return True
        return self._update_json(self._users_file, updater)

    def check_user_credentials(self, username, password):
        users = self._read_json(self._users_file)
        for u in users:
            if u['username'] == username and u['password'] == password:
                logger.info(f"成功验证用户凭据: {username}")
                return {'username': u['username'], 'role': u['role']}
        return False

    # --- 会话 --------------------------------------------------------------

    def insert_session(self, session_id, username):
        def updater(sessions):
            if any(s['session_id'] == session_id for s in sessions):
                return False
            sessions.append({
                'session_id': session_id,
                'username': username,
                'created_at': datetime.now().isoformat()
            })
            logger.info(f"成功插入用户会话: session_id={session_id}, username={username}")
            return True
        return self._update_json(self._sessions_file, updater)

    def delete_session(self, session_id):
        def updater(sessions):
            orig = list(sessions)
            sessions[:] = [s for s in sessions if s['session_id'] != session_id]
            if len(sessions) == len(orig):
                return False
            logger.info(f"成功删除用户会话: session_id={session_id}")
            return True
        return self._update_json(self._sessions_file, updater)

    def fetch_sessions_by_username(self, username):
        sessions = self._read_json(self._sessions_file)
        result = []
        for s in sessions:
            if s['username'] == username:
                # 取首条用户消息作为会话摘要
                first_msg = ''
                history = self.get_session_history(s['session_id'])
                if history and len(history) > 0:
                    first_msg = history[0].get('user', '')[:40]
                result.append({
                    'id': s['session_id'],
                    'created_at': s.get('created_at', ''),
                    'first_msg': first_msg,
                })
        return result if result else None

    # --- 对话历史 ----------------------------------------------------------

    def get_session_history(self, session_id):
        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        if not os.path.exists(history_file):
            return None
        history = self._read_json(history_file)
        logger.info(f"session_id={session_id}, 成功查询对话历史")
        return history

    def insert_session_history(self, session_id, user, assistant):
        def updater(history):
            history.append({
                'id': self._get_next_id(history),
                'type': 'qa',
                'user': user,
                'assistant': assistant,
                'timestamp': datetime.now().isoformat()
            })
            logger.info(f"session_id={session_id}, 成功插入对话历史")
            return True
        return self._update_json(
            os.path.join(self._history_dir, f'{session_id}.json'), updater)

    def insert_session_event(self, session_id, event_type, files):
        """记录会话级操作事件 (上传 / 删除文件等), 与 qa 条目一起追加到同一历史文件。

        event_type: 'upload' | 'delete' | 'delete_all'
        files:     list[str] 受影响的文件名 (delete_all 时可为空)
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
        logger.info(f"session_id={session_id}, 记录事件: {event_type} -> {files}")
        return True

    def delete_session_history(self, session_id):
        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        if os.path.exists(history_file):
            os.remove(history_file)
            logger.info(f"session_id={session_id}, 成功删除对话历史")
            return True
        return False

    # --- 归档 ---------------------------------------------------------------

    def insert_archive(self, session_id, summary, turns):
        """将历史轮次归档存储，返回 archive_id。"""
        import uuid as _uuid
        archive_id = f"arch_{_uuid.uuid4().hex[:12]}"
        archive_file = os.path.join(self.data_dir, 'archives', f'{archive_id}.json')
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
        """按 ID 读取归档，返回完整内容或 None。"""
        archive_file = os.path.join(self.data_dir, 'archives', f'{archive_id}.json')
        if not os.path.exists(archive_file):
            logger.warning(f"归档不存在: {archive_id}")
            return None
        return self._read_json(archive_file)

    def format_archive_turns(self, archive_id):
        """读取归档并格式化为 LLM 可读的文本。"""
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
