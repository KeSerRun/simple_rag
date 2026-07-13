
import json
# 导入 json 模块，用于将 Python 对象序列化为 JSON 字符串（写入文件），
# 以及将 JSON 字符串反序列化为 Python 对象（读取文件）。
# JSON 是一种轻量级的数据交换格式，便于存储和阅读。

import os
# 比如拼接文件路径、创建目录、判断文件是否存在、删除文件等。

import tempfile
# 避免写入过程中程序崩溃导致数据损坏。

import threading
# 对 JSON 文件的读写操作是串行的，不会发生数据竞争。

from datetime import datetime


from base.config import conf
from base.logger import logger
from .base import BaseStore


class JSONFileStore(BaseStore):
    # 主要管理三张"表"（也就是三类数据）：
    #   1. 用户表（users.json）      —— 存储用户名、密码、角色等信息
    #   2. 会话表（sessions.json）    —— 存储会话 ID 和所属用户名
    #   3. 对话历史（history/ 目录）  —— 每个会话一个 JSON 文件，记录一问一答
    #   data/json_store/users.json              - 用户表
    #   data/json_store/sessions.json           - 会话表
    #   data/json_store/history/                - 对话历史目录
    #       {session_id}.json                   -   每个会话一个文件
    #   data/json_store/archives/               - 归档目录
    #       {archive_id}.json                   -   归档文件

    """基于 JSON 文件的持久化存储,覆盖用户/会话/对话历史三张表

    文件结构:
        data/json_store/users.json              - 用户表
        data/json_store/sessions.json           - 会话表
        data/json_store/history/                - 对话历史目录
            {session_id}.json                   -   每个会话一个文件
        data/json_store/archives/               - 归档目录
            {archive_id}.json                   -   归档文件
    """

    def __init__(self, data_dir=None):
        # __init__ 是类的构造函数，在创建 JSONFileStore 实例时自动调用。
        # 参数 data_dir：数据存储的根目录路径。如果为 None，则使用配置中的默认路径。
        self.data_dir = data_dir or conf.data_dir
        # 设置数据根目录：如果没有传入 data_dir，就使用全局配置中的 data_dir。
        # self.data_dir 是实例变量，存储数据目录的路径。

        self._json_dir = os.path.join(self.data_dir, 'json_store')
        # 拼接出 json_store 子目录的完整路径，例如 "data/json_store/"。
        # 下划线开头的变量名表示"内部使用"，不建议外部直接访问。

        self._users_file = os.path.join(self._json_dir, 'users.json')
        # 拼接出用户表 JSON 文件的完整路径，例如 "data/json_store/users.json"。

        self._sessions_file = os.path.join(self._json_dir, 'sessions.json')
        # 拼接出会话表 JSON 文件的完整路径，例如 "data/json_store/sessions.json"。

        self._history_dir = os.path.join(self._json_dir, 'history')
        # 拼接出对话历史目录的完整路径，例如 "data/json_store/history/"。

        self._archive_dir = os.path.join(self._json_dir, 'archives')
        # 拼接出归档目录的完整路径，例如 "data/json_store/archives/"。

        # 全局锁(写操作串行化,防止 uvicorn 多线程并发写)
        self._lock = threading.Lock()
        # 因为 uvicorn（Python web 服务器）会启动多个线程来处理请求，

        # 先迁移旧数据，再创建目录和文件
        self._migrate_from_old()
        # 调用 _migrate_from_old 方法，将旧版本存储位置的数据迁移到新的 json_store 目录。

        self._ensure_dirs()
        # 调用 _ensure_dirs 方法，创建所有必要的目录（如果目录不存在的话）。

        self._init_files()
        # 调用 _init_files 方法，初始化 users.json 和 sessions.json 文件。

    def _ensure_dirs(self):
        # 内部方法：确保所有必要的目录都存在。
        # 如果目录不存在，os.makedirs 会自动创建它们。
        # exist_ok=True 表示如果目录已存在，不会报错。
        os.makedirs(self._json_dir, exist_ok=True)
        # 创建 json_store 目录，例如 "data/json_store/"。

        os.makedirs(self._history_dir, exist_ok=True)
        # 创建 history 子目录，例如 "data/json_store/history/"。

        os.makedirs(self._archive_dir, exist_ok=True)
        # 创建 archives 子目录，例如 "data/json_store/archives/"。

    def _init_files(self):
        # 内部方法：初始化 users.json 和 sessions.json 文件。
        # 这样后续读取时直接 json.load 就能得到一个空列表，而不需要处理文件不存在的异常。
        for filepath in [self._users_file, self._sessions_file]:
            # 遍历两个文件路径：用户表文件和会话表文件。
            if not os.path.exists(filepath):
                # 如果文件还不存在，就创建它。
                with open(filepath, 'w', encoding='utf-8') as f:
                    # 以写入模式（'w'）打开文件，指定编码为 utf-8（支持中文）。
                    # with 语句确保文件使用完后自动关闭。
                    json.dump([], f, ensure_ascii=False, indent=2)
                    # ensure_ascii=False 确保中文等非 ASCII 字符正常显示，不会被转义。
                    # indent=2 让 JSON 文件有 2 个空格的缩进，便于人类阅读。

    def _migrate_from_old(self):
        # 内部方法：将旧版本的平铺数据结构迁移到新的 json_store 子目录结构中。
        # 旧版本的数据文件直接放在 data/ 根目录下（如 data/users.json），
        # 新版本统一放在 data/json_store/ 子目录下。

        """从旧的 data/ 平铺结构迁移到 data/json_store/ 目录。
        在 _ensure_dirs 之前调用，确保新空目录不会妨碍迁移。

        注意：如果目标路径是空文件（2字节 `[]`）或空目录，也视为"不存在"
        以便覆盖 _ensure_dirs 可能在之前轮次创建的空壳。
        """

        migrated = False
        # 默认为 False，表示还没有任何文件被迁移。
        # 在 _move 内部函数中，如果实际执行了迁移，会将 migrated 改为 True。

        def _is_empty_dir(path):
            return os.path.isdir(path) and len(os.listdir(path)) == 0
            # os.listdir(path) 列出目录下的所有文件和子目录。

        def _move(src, dst):
            # 内部函数：将文件或目录从 src 移动到 dst。
            # 如果源路径不存在，则什么都不做。
            # 如果目标路径不存在、是空文件（<= 2 字节）或是空目录，则覆盖迁移。

            nonlocal migrated
            # 而是来自外层函数 _migrate_from_old 的变量。
            # 这样在这个内部函数中修改 migrated 会影响外层的 migrated 变量。

            if not os.path.exists(src):
                return

            # dst 不存在，或者是空文件/空目录 → 可以覆盖
            if not os.path.exists(dst) or \
               (os.path.isfile(dst) and os.path.getsize(dst) <= 2) or \
               _is_empty_dir(dst):
                # 判断是否应该执行迁移：以下三种情况之一成立时执行：
                # 1. 目标路径不存在（全新的环境）。
                # 2. 目标路径是一个文件，且文件大小 <= 2 字节（即内容为 "[]" 的空文件）。
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # 确保目标文件的父目录存在，如果不存在就创建。

                # 如果 dst 是空壳，先删除再 rename
                if os.path.exists(dst):
                    # 如果目标路径已存在，需要先删除，因为 os.rename 不能覆盖已存在的目录。
                    if os.path.isdir(dst):
                        os.rmdir(dst)
                    else:
                        os.remove(dst)
                os.rename(src, dst)
                # 使用 os.rename 将源文件/目录重命名为目标路径，完成迁移。

                logger.info(f"迁移 {src} → {dst}")
                migrated = True

        _move(os.path.join(self.data_dir, 'users.json'), self._users_file)
        # 尝试将 data/users.json 迁移到 data/json_store/users.json。

        _move(os.path.join(self.data_dir, 'sessions.json'), self._sessions_file)
        # 尝试将 data/sessions.json 迁移到 data/json_store/sessions.json。

        # 迁移整个 history/ 和 archives/ 目录
        _move(os.path.join(self.data_dir, 'history'), self._history_dir)
        # 尝试将 data/history/ 整个目录迁移到 data/json_store/history/。

        _move(os.path.join(self.data_dir, 'archives'), self._archive_dir)
        # 尝试将 data/archives/ 整个目录迁移到 data/json_store/archives/。

        if migrated:
            # 如果发生过迁移操作（migrated 为 True），记录一条完成日志。
            logger.info("旧文件迁移完成，后续数据将写入新路径")
            # 提示开发者迁移完成，后续数据都会写入新的路径。

    # --- internal helpers --------------------------------------------------
    # 下面是几个内部辅助方法，封装了 JSON 文件读写操作的通用逻辑。

    def _read_json(self, filepath):
        # 内部方法：从指定的 JSON 文件中读取数据。
        with self._lock:
            # 虽然读操作本身不会修改数据，但配合写操作的锁可以避免
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                return []  # 文件不存在或为空时返回空列表
            with open(filepath, 'r', encoding='utf-8') as f:
                # 以只读模式（'r'）打开文件，指定 utf-8 编码。
                return json.load(f)
                # 使用 json.load 从文件对象中读取 JSON 数据，自动解析为 Python 对象并返回。

    def _write_json(self, filepath, data):
        # 内部方法：将数据以 JSON 格式写入指定文件（原子写入）。

        """原子写入"""

        with self._lock:
            dirname = os.path.dirname(filepath)
            os.makedirs(dirname, exist_ok=True)
            # 确保目录存在，如果不存在就创建（防止目标目录尚未创建的情况）。
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            #   tmp_path —— 临时文件的完整路径（如 ".../xxxxxx.tmp"）
            # dir=dirname 指定临时文件放在目标目录下（确保在同一文件系统，rename 才能原子操作）。
            # suffix='.tmp' 指定临时文件的后缀为 .tmp。
            try:
                # 使用 try 块来捕获可能的异常，确保异常时能清理临时文件。
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    # os.fdopen(fd, 'w') 将文件描述符 fd 转换为 Python 文件对象。
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    # 将数据序列化为 JSON 并写入临时文件。
                os.replace(tmp_path, filepath)
                # os.replace 将临时文件原子地替换为目标文件。
                # 要么完全成功，要么完全失败，不会出现写了一半的情况。
            except Exception:
                # 如果在写入过程中发生任何异常...
                if os.path.exists(tmp_path):
                    # 如果临时文件还存在...
                    os.remove(tmp_path)
                raise
                # 重新抛出异常，让上层调用者知道写操作失败了。

    def _update_json(self, filepath, updater):
        # 内部方法：原子地读取 → 更新 → 写入 JSON 文件。
        # 整个过程中持有锁，确保线程安全。

        """原子地读取 → 更新 → 写入 JSON 文件。整个过程中持锁。"""

        with self._lock:
            # 使用全局锁，确保整个读取-更新-写入过程是原子操作，
            dirname = os.path.dirname(filepath)
            os.makedirs(dirname, exist_ok=True)
            data = []
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            result = updater(data)
            # 调用 updater 函数，传入当前数据 data。
            # updater 函数会修改 data 的内容（比如添加或删除元素），
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            # 创建临时文件，准备原子写入。
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    # 将文件描述符转换为文件对象。
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, filepath)
                # 原子替换：用临时文件替换目标文件。
            except Exception:
                # 如果写入过程中出现异常...
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
            return result

    def _get_next_id(self, items):
        ids = [item['id'] for item in items if 'id' in item]
        # 使用列表推导式，从 items 列表中提取所有包含 'id' 键的元素的 id 值。
        # 这行代码会遍历 items 中的每个元素，如果元素字典有 'id' 键，就取出 id 值。
        return max(ids, default=0) + 1
        # 找出 ids 列表中的最大值，然后加 1 作为新 ID。
        # 如果 ids 为空（列表中没有任何元素或所有元素都没有 'id' 键），
        # default=0 会让 max() 返回 0，这样新 ID 就是 0 + 1 = 1。

    # --- 用户 --------------------------------------------------------------

    def insert_user(self, username, password, role='user'):
        # 参数 role：用户角色，默认是 'user'（普通用户），也可以是 'admin'（管理员）等。

        def updater(users):

            if any(u['username'].lower() == username.lower() for u in users):
                # any() 函数判断列表中是否有元素满足条件。
                # 这里遍历 users 列表，检查是否已有用户的 username 与要插入的用户名相同。
                logger.debug(f"用户 '{username}' 已存在,跳过插入")
                # 记录日志：用户已存在，跳过操作。
                return False

            users.append({
                'id': self._get_next_id(users),
                'username': username,
                'password': password,
                'role': role,
                'created_at': datetime.now().isoformat()
                # 使用 datetime.now() 获取当前时间，isoformat() 格式化为 ISO 8601 标准时间字符串，
                # 例如 "2026-07-08T12:34:56.789123"。
            })
            logger.info(f"成功插入用户: {username}")
          
            return True

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。
        # _update_json 会读取文件 → 调用 updater 修改数据 → 写回文件。

    def delete_user(self, username):

        def updater(users):

            orig = list(users)
            # list(users) 创建 users 的一个浅拷贝（新列表对象，但元素还是原来的字典引用）。

            users[:] = [u for u in users if u['username'] != username]
            # 关键操作：使用列表推导式过滤出不等于要删除用户名的所有用户。
            # users[:] = ... 是切片赋值，它会原地修改列表内容（替换整个列表的元素）。
            # 所以 _update_json 中的 data 变量也会同步更新。

            if len(users) == len(orig):
                return False

            logger.info(f"成功删除用户: {username}")
            # 记录日志：用户删除成功。
            return True

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    def check_user_credentials(self, username, password):
        # 验证用户凭据（用户名和密码是否匹配）。

        users = self._read_json(self._users_file)

        for u in users:
            if u['username'].lower() == username.lower() and u['password'] == password:
                # 同时满足两个条件：用户名相等 且 密码相等。
                logger.info(f"成功验证用户凭据: {username}")
                return {'username': u['username'], 'role': u['role']}
        return False

    def get_all_users(self, page=1, page_size=20):
        # 返回值：一个字典，包含 "items"（当前页的用户列表）和 "total"（用户总数）。

        """分页查询所有用户。返回 {"items": [...], "total": N}。"""

        users = self._read_json(self._users_file)

        total = len(users)

        start = (page - 1) * page_size
        # 计算起始索引。例如第 1 页：start = 0；第 2 页：start = 20。
        # 因为列表索引从 0 开始，第 1 页应该取 users[0] 到 users[19]。

        end = start + page_size
        # 计算结束索引（不包含）。例如 start=0, page_size=20 时 end=20。

        items = users[start:end]
        # 使用切片操作从 users 列表中取出一段子列表，作为当前页的数据。
        # 如果切片超出列表范围，Python 会自动截断到最大长度，不会报错。

        return {"items": items, "total": total}
        # 前端可以根据 total 计算总页数。

    def update_user_role(self, username, new_role):
        # 参数 new_role：新的角色值（字符串，如 'admin'、'user' 等）。

        """更新用户角色。"""

        def updater(users):
            for u in users:
                if u['username'] == username:
                    u['role'] = new_role
                    # 修改该用户的 role 字段为新角色值。
                    logger.info(f"用户角色变更: {username} -> {new_role}")
                    # 记录日志：角色变更信息。
                    return True
            return False

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    def update_user_password(self, username, new_password):

        """更新用户密码。"""

        def updater(users):
            for u in users:
                if u['username'] == username:
                    u['password'] = new_password
                    # 修改该用户的 password 字段为新密码。
                    logger.info(f"用户密码已重置: {username}")
                    return True
            return False

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    # --- 会话 --------------------------------------------------------------

    def insert_session(self, session_id, username):

        def updater(sessions):

            if any(s['session_id'] == session_id for s in sessions):
                # any() 遍历 sessions 列表，检查是否已有会话的 session_id 与要插入的相同。
                # 如果已存在，不重复插入。
                return False

            sessions.append({
                'session_id': session_id,
                'username': username,
                'created_at': datetime.now().isoformat()
                # 记录当前时间作为会话创建时间。
            })
            logger.debug(f"成功插入用户会话: session_id={session_id}, username={username}")
            # 记录日志：成功插入会话。
            return True

        return self._update_json(self._sessions_file, updater)
        # 调用 _update_json，传入会话表文件路径和 updater 函数。

    def delete_session(self, session_id):
        # 删除指定会话 ID 的会话记录。

        def updater(sessions):
            orig = list(sessions)

            sessions[:] = [s for s in sessions if s['session_id'] != session_id]
            # 用列表推导式过滤出 session_id 不等于要删除的会话 ID 的所有会话。
            # 切片赋值 users[:] = ... 实现原地修改。

            if len(sessions) == len(orig):
                return False

            logger.debug(f"成功删除用户会话: session_id={session_id}")
            # 记录日志：会话删除成功。
            return True

        return self._update_json(self._sessions_file, updater)
        # 调用 _update_json，传入会话表文件路径和 updater 函数。

    def fetch_sessions_by_username(self, username):
        # 返回值：如果找到会话，返回一个列表，每个元素包含会话 ID、创建时间和第一条消息；

        sessions = self._read_json(self._sessions_file)

        result = []

        for s in sessions:
            if s['username'] == username:
                # 取首条用户消息作为会话摘要
                first_msg = ''
                # 初始化第一条消息为空字符串。

                history = self.get_session_history(s['session_id'])

                if history and len(history) > 0:
                    # 历史记录存在且不为空时提取首条用户消息作为会话摘要
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
                    # 将处理后的会话信息添加到结果列表。
                    'id': s['session_id'],
                    'created_at': s.get('created_at', ''),
                    'first_msg': first_msg,
                })

        return result if result else None

    # --- 对话历史 ----------------------------------------------------------

    def get_session_history(self, session_id):

        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        # 拼接出该会话对应的历史文件路径，例如 "data/json_store/history/abc123.json"。

        if not os.path.exists(history_file):
            # 如果该文件不存在（会话还没有对话历史）...
            return None

        history = self._read_json(history_file)

        logger.debug(f"session_id={session_id}, 成功查询对话历史")
        # 记录日志：成功查询到对话历史。

        return history

    def insert_session_history(self, session_id, user, assistant):
        # 向指定会话的对话历史中添加一条问答记录。

        def updater(history):

            history.append({
                'id': self._get_next_id(history),
                'type': 'qa',
                # 记录类型为 'qa'（Question and Answer，问答）。
                'user': user,
                'assistant': assistant,
                'timestamp': datetime.now().isoformat()
            })
            logger.debug(f"session_id={session_id}, 成功插入对话历史")
            return True

        return self._update_json(
            os.path.join(self._history_dir, f'{session_id}.json'), updater)
        # 调用 _update_json，传入该会话的历史文件路径和 updater 函数。
        # 因为每个会话的历史文件路径不同（取决于 session_id）。

    def insert_session_turn(self, session_id, messages: list) -> bool:
        """插入一轮完整的对话消息（含工具调用和结果）。

        参数:
            session_id: 会话 ID
            messages: OpenAI 格式的消息列表，每个元素为 {"role": ..., "content": ...}
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
        # 参数 event_type：事件类型，可以是 'upload'（上传）、'delete'（删除）、
        #                  'delete_all'（全部删除）等字符串。
        # 参数 files：受影响的文件名列表（list[str]），delete_all 时可以为空列表。

        """记录会话级操作事件 (上传 / 删除文件等), 与 qa 条目一起追加到同一历史文件。

        event_type: 'upload' | 'delete' | 'delete_all'
        files:     list[str] 受影响的文件名 (delete_all 时可为空)
        """

        if not session_id:
            return False

        history_file = os.path.join(self._history_dir, f'{session_id}.json')

        history = []
        # 初始化历史列表为空列表（作为文件不存在的默认值）。

        if os.path.exists(history_file):
            # 如果历史文件已存在，才读取现有数据。
            history = self._read_json(history_file)

        history.append({
            # 在历史列表末尾添加一条事件记录。
            'id': self._get_next_id(history),
            'type': 'event',
            # 记录类型为 'event'（事件），区别于 'qa'（问答）。
            'event_type': event_type,
            # 事件的具体类型，如 'upload'、'delete' 等。
            'files': list(files or []),
            # 受影响的文件列表。files or [] 的意思是：如果 files 为 None 则使用空列表。
            'timestamp': datetime.now().isoformat()
        })

        self._write_json(history_file, history)
        # 使用 _write_json 直接写入整个历史列表（覆盖写入，不是原子更新）。
        # 注意这里没有使用 _update_json，因为读和写之间没有需要保持原子性的复杂逻辑。

        logger.debug(f"session_id={session_id}, 记录事件: {event_type} -> {files}")

        return True

    def delete_session_history(self, session_id):

        history_file = os.path.join(self._history_dir, f'{session_id}.json')

        if os.path.exists(history_file):
            os.remove(history_file)
            # 使用 os.remove 删除该文件。
            logger.debug(f"session_id={session_id}, 成功删除对话历史")
            return True

        return False

    # --- 会话任务持久化 -------------------------------------------------------
    def save_session_tasks(self, session_id, tasks):
        """持久化会话任务数据（短期/长期任务）。"""
        tasks_dir = os.path.join(self._json_dir, "session_tasks")
        os.makedirs(tasks_dir, exist_ok=True)
        file_path = os.path.join(tasks_dir, f"{session_id}.json")
        self._write_json(file_path, tasks)

    def get_session_tasks(self, session_id):
        """读取会话任务数据，不存在则返回默认空结构。"""
        file_path = os.path.join(self._json_dir, "session_tasks", f"{session_id}.json")
        if not os.path.exists(file_path):
            return {"short": [], "long": []}
        return self._read_json(file_path)

    def delete_session_tasks(self, session_id):
        """删除指定会话的任务数据。"""
        file_path = os.path.join(self._json_dir, "session_tasks", f"{session_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)

    # --- 归档 ---------------------------------------------------------------

    def insert_archive(self, session_id, summary, turns):

        """将历史轮次归档存储，返回 archive_id。"""

        import uuid as _uuid
        # uuid 用于生成全局唯一标识符（Universally Unique Identifier）。

        archive_id = f"arch_{session_id[:16]}_{_uuid.uuid4().hex[:8]}"
        # 生成归档 ID：前缀 "arch_" + UUID 的十六进制字符串的前 12 位。

        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')
        # 拼接出归档文件的完整路径，例如 "data/json_store/archives/arch_xxxx.json"。

        os.makedirs(os.path.dirname(archive_file), exist_ok=True)
        # 确保归档目录存在（虽然 __init__ 中已经创建过，但这里再次确保以防万一）。

        self._write_json(archive_file, {
            # 使用 _write_json 将归档数据写入文件。
            'id': archive_id,
            'session_id': session_id,
            'summary': summary,
            # 归档摘要，通常是 LLM 生成的对话总结。
            'turns': turns,
            # 完整的对话轮次列表（用户问题和助手回复的交替序列）。
            'created_at': datetime.now().isoformat(),
        })
        logger.info(f"归档创建: {archive_id} ({len(turns)} 轮)")
      
        return archive_id

    def get_archive(self, archive_id):
        # 根据归档 ID 读取归档内容。

        """按 ID 读取归档，返回完整内容或 None。"""

        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')

        if not os.path.exists(archive_file):
            # 如果归档文件不存在...
            logger.warning(f"归档不存在: {archive_id}")
            # 记录警告日志：归档不存在。
            return None

        return self._read_json(archive_file)

    def delete_session_archives(self, session_id):
        """删除指定会话的所有归档文件。"""
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
        # 读取归档数据并将其中的对话轮次格式化为人类（或 LLM）可读的文本。

        """读取归档并格式化为 LLM 可读的文本。"""

        data = self.get_archive(archive_id)
        # 调用 get_archive 方法读取归档数据。

        if not data:
            # 如果 data 为 None（归档不存在）...
            return None

        lines = [f"[归档 {archive_id}] 以下为历史对话记录："]
        # 使用 f-string（格式化字符串）将 archive_id 动态嵌入到字符串中。

        for t in data.get('turns', []):
            # 遍历归档中的 turns 列表（如果没有 'turns' 键，默认使用空列表）。
            # t 是每个轮次的字典，包含 'user' 和 'assistant' 等字段。
            if t.get('user'):
                lines.append(f"用户：{t['user']}")
            if t.get('assistant'):
                lines.append(f"助手：{t['assistant']}")

        return "\n\n".join(lines)
        # 使用 "\n\n"（两个换行符，即一个空行）将 lines 列表中的所有行连接成一个字符串。


if __name__ == "__main__":
    # 如果这个文件被 import 到其他模块中，__name__ 会是模块名（"json_store"），
    # 而不是 "__main__"，所以下面的代码不会执行。

    store = JSONFileStore()
    # 创建一个 JSONFileStore 的实例（使用默认的 data_dir 配置）。

    store.insert_user("test", "123456")
    # 调用 insert_user 方法，插入一个测试用户（用户名 "test"，密码 "123456"，角色默认 "user"）。

    print("Credentials check:", store.check_user_credentials("test", "123456"))
    # 调用 check_user_credentials 验证刚才插入的用户凭据，
    # 并将结果打印到控制台。如果验证成功，会打印用户信息字典。
