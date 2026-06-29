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

    def _get_next_id(self, items):
        return max((item['id'] for item in items), default=0) + 1

    # --- 用户 --------------------------------------------------------------

    def insert_user(self, username, password, role='user'):
        users = self._read_json(self._users_file)
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
        self._write_json(self._users_file, users)
        logger.info(f"成功插入用户: {username}")
        return True

    def delete_user(self, username):
        users = self._read_json(self._users_file)
        new_users = [u for u in users if u['username'] != username]
        if len(new_users) == len(users):
            return False
        self._write_json(self._users_file, new_users)
        logger.info(f"成功删除用户: {username}")
        return True

    def check_user_credentials(self, username, password):
        users = self._read_json(self._users_file)
        for u in users:
            if u['username'] == username and u['password'] == password:
                logger.info(f"成功验证用户凭据: {username}")
                return {'username': u['username'], 'role': u['role']}
        return False

    # --- 会话 --------------------------------------------------------------

    def insert_session(self, session_id, username):
        sessions = self._read_json(self._sessions_file)
        if any(s['session_id'] == session_id for s in sessions):
            return False
        sessions.append({
            'session_id': session_id,
            'username': username,
            'created_at': datetime.now().isoformat()
        })
        self._write_json(self._sessions_file, sessions)
        logger.info(f"成功插入用户会话: session_id={session_id}, username={username}")
        return True

    def delete_session(self, session_id):
        sessions = self._read_json(self._sessions_file)
        new_sessions = [s for s in sessions if s['session_id'] != session_id]
        if len(new_sessions) == len(sessions):
            return False
        self._write_json(self._sessions_file, new_sessions)
        logger.info(f"成功删除用户会话: session_id={session_id}")
        return True

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
        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        history = []
        if os.path.exists(history_file):
            history = self._read_json(history_file)
        history.append({
            'id': self._get_next_id(history),
            'user': user,
            'assistant': assistant,
            'timestamp': datetime.now().isoformat()
        })
        self._write_json(history_file, history)
        logger.info(f"session_id={session_id}, 成功插入对话历史")
        return True

    def delete_session_history(self, session_id):
        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        if os.path.exists(history_file):
            os.remove(history_file)
            logger.info(f"session_id={session_id}, 成功删除对话历史")
            return True
        return False


if __name__ == "__main__":
    store = JSONFileStore()
    store.insert_user("test", "123456")
    print("Credentials check:", store.check_user_credentials("test", "123456"))
