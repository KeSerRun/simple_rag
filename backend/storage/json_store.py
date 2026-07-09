# ===== 导入标准库模块 =====

import json
# 导入 json 模块，用于将 Python 对象序列化为 JSON 字符串（写入文件），
# 以及将 JSON 字符串反序列化为 Python 对象（读取文件）。
# JSON 是一种轻量级的数据交换格式，便于存储和阅读。

import os
# 导入 os 模块，用于与操作系统进行交互，
# 比如拼接文件路径、创建目录、判断文件是否存在、删除文件等。

import tempfile
# 导入 tempfile 模块，用于创建临时文件和临时目录。
# 这里主要用于实现"原子写入"——先写入临时文件，再替换目标文件，
# 避免写入过程中程序崩溃导致数据损坏。

import threading
# 导入 threading 模块，提供多线程支持。
# 这里用 threading.Lock() 创建一个锁，确保在多线程环境下
# 对 JSON 文件的读写操作是串行的，不会发生数据竞争。

from datetime import datetime
# 从 datetime 模块中导入 datetime 类。
# 用于获取当前时间戳，在插入记录时记录创建时间。

# ===== 导入项目内部模块 =====

from base.config import conf
from base.logger import logger
from .base import BaseStore
# 从项目的基础日志模块 base.logger 中导入 logger 对象。
# logger 用于记录日志信息，方便开发者调试和追踪程序运行状态。


class JSONFileStore(BaseStore):
    # ================================================================
    # ================================================================
    # 类定义：JSONFileStore —— 基于 JSON 文件的持久化存储
    #
    # 这个类的作用是把数据以 JSON 文件的形式存储到磁盘上，
    # 主要管理三张"表"（也就是三类数据）：
    #   1. 用户表（users.json）      —— 存储用户名、密码、角色等信息
    #   2. 会话表（sessions.json）    —— 存储会话 ID 和所属用户名
    #   3. 对话历史（history/ 目录）  —— 每个会话一个 JSON 文件，记录一问一答
    #
    # 额外还有归档（archives/ 目录），用于把旧对话打包存储。
    #
    # 文件结构：
    #   data/json_store/users.json              - 用户表
    #   data/json_store/sessions.json           - 会话表
    #   data/json_store/history/                - 对话历史目录
    #       {session_id}.json                   -   每个会话一个文件
    #   data/json_store/archives/               - 归档目录
    #       {archive_id}.json                   -   归档文件
    # ================================================================

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
        # 这个方法的作用是初始化存储路径、创建必要的目录和文件，以及迁移旧数据。
        self.data_dir = data_dir or conf.data_dir
        # 设置数据根目录：如果没有传入 data_dir，就使用全局配置中的 data_dir。
        # self.data_dir 是实例变量，存储数据目录的路径。

        self._json_dir = os.path.join(self.data_dir, 'json_store')
        # 拼接出 json_store 子目录的完整路径，例如 "data/json_store/"。
        # 所有 JSON 文件都会存放在这个目录下。
        # 下划线开头的变量名表示"内部使用"，不建议外部直接访问。

        self._users_file = os.path.join(self._json_dir, 'users.json')
        # 拼接出用户表 JSON 文件的完整路径，例如 "data/json_store/users.json"。

        self._sessions_file = os.path.join(self._json_dir, 'sessions.json')
        # 拼接出会话表 JSON 文件的完整路径，例如 "data/json_store/sessions.json"。

        self._history_dir = os.path.join(self._json_dir, 'history')
        # 拼接出对话历史目录的完整路径，例如 "data/json_store/history/"。
        # 每个会话的对话历史会作为一个独立的 JSON 文件存放在这个目录下。

        self._archive_dir = os.path.join(self._json_dir, 'archives')
        # 拼接出归档目录的完整路径，例如 "data/json_store/archives/"。

        # 全局锁(写操作串行化,防止 uvicorn 多线程并发写)
        self._lock = threading.Lock()
        # 创建一个 threading.Lock 锁对象。
        # 因为 uvicorn（Python web 服务器）会启动多个线程来处理请求，
        # 多个线程同时读写同一个文件可能导致数据混乱。
        # 这个锁确保同一时间只有一个线程能执行文件的读写操作。

        # 先迁移旧数据，再创建目录和文件
        self._migrate_from_old()
        # 调用 _migrate_from_old 方法，将旧版本存储位置的数据迁移到新的 json_store 目录。
        # 这样做是为了兼容旧版本的数据格式，确保升级后数据不丢失。

        self._ensure_dirs()
        # 调用 _ensure_dirs 方法，创建所有必要的目录（如果目录不存在的话）。

        self._init_files()
        # 调用 _init_files 方法，初始化 users.json 和 sessions.json 文件。
        # 如果这两个文件还不存在，就创建一个空数组 [] 写入文件。

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
        # 如果文件不存在，就创建一个空列表 [] 写入文件。
        # 这样后续读取时直接 json.load 就能得到一个空列表，而不需要处理文件不存在的异常。
        for filepath in [self._users_file, self._sessions_file]:
            # 遍历两个文件路径：用户表文件和会话表文件。
            if not os.path.exists(filepath):
                # 如果文件还不存在，就创建它。
                with open(filepath, 'w', encoding='utf-8') as f:
                    # 以写入模式（'w'）打开文件，指定编码为 utf-8（支持中文）。
                    # with 语句确保文件使用完后自动关闭。
                    json.dump([], f, ensure_ascii=False, indent=2)
                    # 将一个空列表 [] 以 JSON 格式写入文件。
                    # ensure_ascii=False 确保中文等非 ASCII 字符正常显示，不会被转义。
                    # indent=2 让 JSON 文件有 2 个空格的缩进，便于人类阅读。

    def _migrate_from_old(self):
        # 内部方法：将旧版本的平铺数据结构迁移到新的 json_store 子目录结构中。
        # 旧版本的数据文件直接放在 data/ 根目录下（如 data/users.json），
        # 新版本统一放在 data/json_store/ 子目录下。
        #
        # 注意：这个方法在 _ensure_dirs 之前调用，
        # 这样即使新的空目录已经被创建，也不会影响迁移判断。
        #
        # 如果目标路径是一个空文件（内容为 "[]"，大小 <= 2 字节）或空目录，
        # 也视为"不存在"，这样可以覆盖之前轮次创建的空壳文件/目录。

        """从旧的 data/ 平铺结构迁移到 data/json_store/ 目录。
        在 _ensure_dirs 之前调用，确保新空目录不会妨碍迁移。

        注意：如果目标路径是空文件（2字节 `[]`）或空目录，也视为"不存在"
        以便覆盖 _ensure_dirs 可能在之前轮次创建的空壳。
        """

        migrated = False
        # 定义一个标志变量，记录是否发生了迁移操作。
        # 默认为 False，表示还没有任何文件被迁移。
        # 在 _move 内部函数中，如果实际执行了迁移，会将 migrated 改为 True。

        def _is_empty_dir(path):
            # 内部函数：判断一个路径是否为空目录。
            # 参数 path：要检查的路径。
            # 返回值：True 表示是空目录，False 表示不是空目录或根本就不是目录。
            return os.path.isdir(path) and len(os.listdir(path)) == 0
            # os.path.isdir(path) 判断路径是否是一个目录。
            # os.listdir(path) 列出目录下的所有文件和子目录。
            # 如果两者都满足（是目录且内容为空），说明是空目录，返回 True。

        def _move(src, dst):
            # 内部函数：将文件或目录从 src 移动到 dst。
            # 参数 src：源路径（旧位置）。
            # 参数 dst：目标路径（新位置）。
            # 如果源路径不存在，则什么都不做。
            # 如果目标路径不存在、是空文件（<= 2 字节）或是空目录，则覆盖迁移。

            nonlocal migrated
            # nonlocal 关键字声明 migrated 不是这个内部函数的局部变量，
            # 而是来自外层函数 _migrate_from_old 的变量。
            # 这样在这个内部函数中修改 migrated 会影响外层的 migrated 变量。

            if not os.path.exists(src):
                # 如果源文件或源目录不存在，就什么都不做，直接返回。
                return

            # dst 不存在，或者是空文件/空目录 → 可以覆盖
            if not os.path.exists(dst) or \
               (os.path.isfile(dst) and os.path.getsize(dst) <= 2) or \
               _is_empty_dir(dst):
                # 判断是否应该执行迁移：以下三种情况之一成立时执行：
                # 1. 目标路径不存在（全新的环境）。
                # 2. 目标路径是一个文件，且文件大小 <= 2 字节（即内容为 "[]" 的空文件）。
                # 3. 目标路径是一个空目录。
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # 确保目标文件的父目录存在，如果不存在就创建。
                # os.path.dirname(dst) 获取目标路径的父目录。

                # 如果 dst 是空壳，先删除再 rename
                if os.path.exists(dst):
                    # 如果目标路径已存在，需要先删除，因为 os.rename 不能覆盖已存在的目录。
                    if os.path.isdir(dst):
                        # 如果目标是一个目录...
                        os.rmdir(dst)
                        # 用 os.rmdir 删除这个空目录。注意 rmdir 只能删除空目录。
                    else:
                        os.remove(dst)
                        # 如果目标是一个文件，用 os.remove 删除它。
                os.rename(src, dst)
                # 使用 os.rename 将源文件/目录重命名为目标路径，完成迁移。
                # 这个操作是原子的（在同一个文件系统内），不会导致数据丢失。

                logger.info(f"迁移 {src} → {dst}")
                # 记录日志：打印迁移信息，说明从哪迁移到哪。
                migrated = True
                # 将迁移标志设为 True，表示至少有一个文件被迁移了。

        # 迁移根目录的 .json 文件
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
        # 参数 filepath：要读取的 JSON 文件的完整路径。
        # 返回值：解析后的 Python 对象（通常是列表或字典）。
        with self._lock:
            # 使用全局锁，确保同一时间只有一个线程执行读操作。
            # 虽然读操作本身不会修改数据，但配合写操作的锁可以避免
            # "读到一个正在被写入的中间状态"。
            with open(filepath, 'r', encoding='utf-8') as f:
                # 以只读模式（'r'）打开文件，指定 utf-8 编码。
                return json.load(f)
                # 使用 json.load 从文件对象中读取 JSON 数据，自动解析为 Python 对象并返回。

    def _write_json(self, filepath, data):
        # 内部方法：将数据以 JSON 格式写入指定文件（原子写入）。
        # 参数 filepath：要写入的目标文件路径。
        # 参数 data：要写入的 Python 对象（会被序列化为 JSON）。
        #
        # 原子写入的含义：先写入一个临时文件，再用 os.replace 替换目标文件。
        # 这样即使写入过程中程序崩溃，目标文件也不会被破坏（最多残留一个临时文件）。

        """原子写入"""

        with self._lock:
            # 使用全局锁，确保同一时间只有一个线程能执行写操作。
            dirname = os.path.dirname(filepath)
            # 获取目标文件所在的目录路径，用于创建临时文件。
            os.makedirs(dirname, exist_ok=True)
            # 确保目录存在，如果不存在就创建（防止目标目录尚未创建的情况）。
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            # 在目标目录下创建一个临时文件。
            # mkstemp 返回两个值：
            #   fd       —— 临时文件的文件描述符（一个整数）
            #   tmp_path —— 临时文件的完整路径（如 ".../xxxxxx.tmp"）
            # dir=dirname 指定临时文件放在目标目录下（确保在同一文件系统，rename 才能原子操作）。
            # suffix='.tmp' 指定临时文件的后缀为 .tmp。
            try:
                # 使用 try 块来捕获可能的异常，确保异常时能清理临时文件。
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    # os.fdopen(fd, 'w') 将文件描述符 fd 转换为 Python 文件对象。
                    # 这样我们就可以像操作普通文件一样写入数据。
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    # 将数据序列化为 JSON 并写入临时文件。
                os.replace(tmp_path, filepath)
                # os.replace 将临时文件原子地替换为目标文件。
                # 这个操作是原子的（在操作系统层面保证），
                # 要么完全成功，要么完全失败，不会出现写了一半的情况。
            except Exception:
                # 如果在写入过程中发生任何异常...
                if os.path.exists(tmp_path):
                    # 如果临时文件还存在...
                    os.remove(tmp_path)
                    # 删除这个临时文件，避免残留垃圾文件占用磁盘空间。
                raise
                # 重新抛出异常，让上层调用者知道写操作失败了。

    def _update_json(self, filepath, updater):
        # 内部方法：原子地读取 → 更新 → 写入 JSON 文件。
        # 整个过程中持有锁，确保线程安全。
        #
        # 参数 filepath：要操作的 JSON 文件路径。
        # 参数 updater：一个函数，接收当前数据（列表），返回更新后的结果。
        #   updater 函数会在读取数据后被调用，调用者可以在这个函数中修改数据。
        # 返回值：updater 函数的返回值被透传返回给调用者。

        """原子地读取 → 更新 → 写入 JSON 文件。整个过程中持锁。"""

        with self._lock:
            # 使用全局锁，确保整个读取-更新-写入过程是原子操作，
            # 不会被其他线程打断。
            dirname = os.path.dirname(filepath)
            # 获取目标文件所在的目录路径。
            os.makedirs(dirname, exist_ok=True)
            # 确保目录存在。
            data = []
            # 初始化 data 为一个空列表。这是默认值，如果文件不存在就使用空列表。
            if os.path.exists(filepath):
                # 如果文件存在，才执行读取操作。
                with open(filepath, 'r', encoding='utf-8') as f:
                    # 以只读模式打开 JSON 文件。
                    data = json.load(f)
                    # 读取文件内容，解析为 Python 对象（通常是列表）。
            result = updater(data)
            # 调用 updater 函数，传入当前数据 data。
            # updater 函数会修改 data 的内容（比如添加或删除元素），
            # 并返回一个结果（通常是 True 或 False 表示操作是否成功）。
            # 注意：updater 操作的是列表本身（引用传递），不需要返回 data。
            fd, tmp_path = tempfile.mkstemp(dir=dirname, suffix='.tmp')
            # 创建临时文件，准备原子写入。
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    # 将文件描述符转换为文件对象。
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    # 将更新后的数据写入临时文件。
                os.replace(tmp_path, filepath)
                # 原子替换：用临时文件替换目标文件。
            except Exception:
                # 如果写入过程中出现异常...
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    # 清理临时文件。
                raise
                # 重新抛出异常。
            return result
            # 返回 updater 函数的执行结果。

    def _get_next_id(self, items):
        # 内部方法：计算下一个可用的 ID。
        # 参数 items：包含字典的列表，每个字典应该有一个 'id' 键。
        # 返回值：当前最大 ID + 1，如果列表为空则返回 1。
        ids = [item['id'] for item in items if 'id' in item]
        # 使用列表推导式，从 items 列表中提取所有包含 'id' 键的元素的 id 值。
        # 这行代码会遍历 items 中的每个元素，如果元素字典有 'id' 键，就取出 id 值。
        return max(ids, default=0) + 1
        # 找出 ids 列表中的最大值，然后加 1 作为新 ID。
        # 如果 ids 为空（列表中没有任何元素或所有元素都没有 'id' 键），
        # default=0 会让 max() 返回 0，这样新 ID 就是 0 + 1 = 1。

    # --- 用户 --------------------------------------------------------------
    # 以下方法用于操作用户数据（users.json 文件）。

    def insert_user(self, username, password, role='user'):
        # 插入一个新用户到用户表。
        # 参数 username：用户名（字符串）。
        # 参数 password：密码（字符串）。
        # 参数 role：用户角色，默认是 'user'（普通用户），也可以是 'admin'（管理员）等。
        # 返回值：True 表示插入成功，False 表示用户已存在（不重复插入）。

        def updater(users):
            # 定义内部函数 updater，作为 _update_json 的回调。
            # 参数 users：当前用户列表（从 JSON 文件读取出来）。
            # 返回值：True 表示成功插入，False 表示用户已存在。

            if any(u['username'] == username for u in users):
                # any() 函数判断列表中是否有元素满足条件。
                # 这里遍历 users 列表，检查是否已有用户的 username 与要插入的用户名相同。
                # 如果存在，说明用户名已注册，不再重复插入。
                logger.debug(f"用户 '{username}' 已存在,跳过插入")
                # 记录日志：用户已存在，跳过操作。
                return False
                # 返回 False，表示没有执行插入操作。

            users.append({
                # 如果用户名不存在，就在 users 列表末尾添加一个新用户字典。
                'id': self._get_next_id(users),
                # 使用 _get_next_id 自动分配一个自增 ID。
                'username': username,
                # 设置用户名。
                'password': password,
                # 设置密码。
                'role': role,
                # 设置用户角色。
                'created_at': datetime.now().isoformat()
                # 使用 datetime.now() 获取当前时间，isoformat() 格式化为 ISO 8601 标准时间字符串，
                # 例如 "2026-07-08T12:34:56.789123"。
            })
            logger.info(f"成功插入用户: {username}")
          
            return True
            # 返回 True，表示插入操作执行成功。

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。
        # _update_json 会读取文件 → 调用 updater 修改数据 → 写回文件。
        # 最终返回 updater 的返回值（True 或 False）。

    def delete_user(self, username):
        # 从用户表中删除指定用户名的用户。
        # 参数 username：要删除的用户名。
        # 返回值：True 表示删除成功，False 表示未找到该用户。

        def updater(users):
            # 定义内部函数 updater，作为 _update_json 的回调。
            # 参数 users：当前用户列表。
            # 返回值：True 表示成功删除，False 表示未找到用户。

            orig = list(users)
            # 复制一份原始用户列表，用于后续比较长度。
            # list(users) 创建 users 的一个浅拷贝（新列表对象，但元素还是原来的字典引用）。

            users[:] = [u for u in users if u['username'] != username]
            # 关键操作：使用列表推导式过滤出不等于要删除用户名的所有用户。
            # users[:] = ... 是切片赋值，它会原地修改列表内容（替换整个列表的元素）。
            # 这个写法保证了 users 变量仍然指向同一个列表对象（引用不变），
            # 所以 _update_json 中的 data 变量也会同步更新。

            if len(users) == len(orig):
                # 如果过滤后的列表长度和原来一样，说明没有找到匹配的用户名。
                return False
                # 返回 False，表示没有用户被删除。

            logger.info(f"成功删除用户: {username}")
            # 记录日志：用户删除成功。
            return True
            # 返回 True，表示删除操作执行成功。

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    def check_user_credentials(self, username, password):
        # 验证用户凭据（用户名和密码是否匹配）。
        # 参数 username：用户名。
        # 参数 password：密码。
        # 返回值：如果验证通过，返回包含用户名和角色的字典；
        #         如果验证失败（用户名不存在或密码错误），返回 False。

        users = self._read_json(self._users_file)
        # 使用 _read_json 读取用户表文件，获取所有用户的列表。

        for u in users:
            # 遍历用户列表中的每个用户字典。
            if u['username'] == username and u['password'] == password:
                # 同时满足两个条件：用户名相等 且 密码相等。
                logger.info(f"成功验证用户凭据: {username}")
                # 记录日志：验证成功。
                return {'username': u['username'], 'role': u['role']}
                # 返回一个字典，包含用户名和角色（不返回密码，安全考虑）。
        return False
        # 如果遍历完所有用户都没有匹配的，返回 False 表示验证失败。

    def get_all_users(self, page=1, page_size=20):
        # 分页查询所有用户。
        # 参数 page：当前页码，从 1 开始，默认第 1 页。
        # 参数 page_size：每页显示的用户数量，默认 20 条。
        # 返回值：一个字典，包含 "items"（当前页的用户列表）和 "total"（用户总数）。

        """分页查询所有用户。返回 {"items": [...], "total": N}。"""

        users = self._read_json(self._users_file)
        # 读取用户表文件，获取所有用户的列表。

        total = len(users)
        # 计算用户总数，用于前端分页显示。

        start = (page - 1) * page_size
        # 计算起始索引。例如第 1 页：start = 0；第 2 页：start = 20。
        # 因为列表索引从 0 开始，第 1 页应该取 users[0] 到 users[19]。

        end = start + page_size
        # 计算结束索引（不包含）。例如 start=0, page_size=20 时 end=20。

        items = users[start:end]
        # 使用切片操作从 users 列表中取出一段子列表，作为当前页的数据。
        # 如果切片超出列表范围，Python 会自动截断到最大长度，不会报错。

        return {"items": items, "total": total}
        # 返回一个字典，包含 items（当前页的用户列表）和 total（总用户数）。
        # 前端可以根据 total 计算总页数。

    def update_user_role(self, username, new_role):
        # 更新指定用户的角色。
        # 参数 username：要更新角色的用户名。
        # 参数 new_role：新的角色值（字符串，如 'admin'、'user' 等）。
        # 返回值：True 表示更新成功，False 表示未找到该用户。

        """更新用户角色。"""

        def updater(users):
            # 定义内部函数 updater，作为 _update_json 的回调。
            for u in users:
                # 遍历用户列表。
                if u['username'] == username:
                    # 如果找到匹配的用户名...
                    u['role'] = new_role
                    # 修改该用户的 role 字段为新角色值。
                    logger.info(f"用户角色变更: {username} -> {new_role}")
                    # 记录日志：角色变更信息。
                    return True
                    # 返回 True，表示更新成功。
            return False
            # 如果遍历完都没找到，返回 False。

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    def update_user_password(self, username, new_password):
        # 更新指定用户的密码。
        # 参数 username：要更新密码的用户名。
        # 参数 new_password：新密码（字符串）。
        # 返回值：True 表示更新成功，False 表示未找到该用户。

        """更新用户密码。"""

        def updater(users):
            # 定义内部函数 updater，作为 _update_json 的回调。
            for u in users:
                # 遍历用户列表。
                if u['username'] == username:
                    # 如果找到匹配的用户名...
                    u['password'] = new_password
                    # 修改该用户的 password 字段为新密码。
                    logger.info(f"用户密码已重置: {username}")
                    # 记录日志：密码已重置。
                    return True
                    # 返回 True，表示更新成功。
            return False
            # 如果遍历完都没找到，返回 False。

        return self._update_json(self._users_file, updater)
        # 调用 _update_json，传入用户表文件路径和 updater 函数。

    # --- 会话 --------------------------------------------------------------
    # 以下方法用于操作用户会话数据（sessions.json 文件）。

    def insert_session(self, session_id, username):
        # 创建一个新的会话记录。
        # 参数 session_id：会话的唯一标识符（字符串）。
        # 参数 username：创建该会话的用户名。
        # 返回值：True 表示插入成功，False 表示会话 ID 已存在。

        def updater(sessions):
            # 定义内部函数 updater，作为 _update_json 的回调。
            # 参数 sessions：当前会话列表。

            if any(s['session_id'] == session_id for s in sessions):
                # any() 遍历 sessions 列表，检查是否已有会话的 session_id 与要插入的相同。
                # 如果已存在，不重复插入。
                return False
                # 返回 False，表示没有执行插入。

            sessions.append({
                # 在 sessions 列表末尾添加一个新的会话字典。
                'session_id': session_id,
                # 设置会话 ID。
                'username': username,
                # 设置所属用户名。
                'created_at': datetime.now().isoformat()
                # 记录当前时间作为会话创建时间。
            })
            logger.debug(f"成功插入用户会话: session_id={session_id}, username={username}")
            # 记录日志：成功插入会话。
            return True
            # 返回 True，表示插入成功。

        return self._update_json(self._sessions_file, updater)
        # 调用 _update_json，传入会话表文件路径和 updater 函数。

    def delete_session(self, session_id):
        # 删除指定会话 ID 的会话记录。
        # 参数 session_id：要删除的会话 ID。
        # 返回值：True 表示删除成功，False 表示未找到该会话。

        def updater(sessions):
            # 定义内部函数 updater，作为 _update_json 的回调。
            orig = list(sessions)
            # 复制原始会话列表，用于比较。

            sessions[:] = [s for s in sessions if s['session_id'] != session_id]
            # 用列表推导式过滤出 session_id 不等于要删除的会话 ID 的所有会话。
            # 切片赋值 users[:] = ... 实现原地修改。

            if len(sessions) == len(orig):
                # 如果长度没变，说明没有找到匹配的会话 ID。
                return False
                # 返回 False。

            logger.debug(f"成功删除用户会话: session_id={session_id}")
            # 记录日志：会话删除成功。
            return True
            # 返回 True。

        return self._update_json(self._sessions_file, updater)
        # 调用 _update_json，传入会话表文件路径和 updater 函数。

    def fetch_sessions_by_username(self, username):
        # 根据用户名查询该用户的所有会话。
        # 参数 username：要查询的用户名。
        # 返回值：如果找到会话，返回一个列表，每个元素包含会话 ID、创建时间和第一条消息；
        #         如果没有找到任何会话，返回 None。

        sessions = self._read_json(self._sessions_file)
        # 读取会话表文件，获取所有会话列表。

        result = []
        # 初始化结果列表，用于存放匹配的会话数据。

        for s in sessions:
            # 遍历所有会话。
            if s['username'] == username:
                # 如果会话的用户名匹配要查询的用户名...
                # 取首条用户消息作为会话摘要
                first_msg = ''
                # 初始化第一条消息为空字符串。

                history = self.get_session_history(s['session_id'])
                # 调用 get_session_history 方法，获取该会话的对话历史记录。

                if history and len(history) > 0:
                    # 如果历史记录存在且不为空（列表中有元素）...
                    first_msg = history[0].get('user', '')[:40]
                    # history[0] 获取第一条记录，.get('user', '') 获取该记录中 'user' 字段的值，
                    # 如果不存在则返回空字符串。然后取前 40 个字符作为摘要。
                    # 这样前端在显示会话列表时，可以展示第一条消息的预览。

                result.append({
                    # 将处理后的会话信息添加到结果列表。
                    'id': s['session_id'],
                    # 会话 ID。
                    'created_at': s.get('created_at', ''),
                    # 会话创建时间，如果不存在则返回空字符串。
                    'first_msg': first_msg,
                    # 会话的第一条用户消息（前 40 个字符），用于列表预览。
                })

        return result if result else None
        # 如果 result 列表不为空（有匹配的会话），返回该列表。
        # 如果 result 列表为空（没有匹配的会话），返回 None。

    # --- 对话历史 ----------------------------------------------------------
    # 以下方法用于操作对话历史数据（history/ 目录下的 JSON 文件）。

    def get_session_history(self, session_id):
        # 获取指定会话的完整对话历史。
        # 参数 session_id：会话的唯一标识符。
        # 返回值：如果历史文件存在，返回对话历史列表；如果文件不存在，返回 None。

        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        # 拼接出该会话对应的历史文件路径，例如 "data/json_store/history/abc123.json"。
        # 每个会话有一个独立的 JSON 文件，以 session_id 命名。

        if not os.path.exists(history_file):
            # 如果该文件不存在（会话还没有对话历史）...
            return None
            # 返回 None，表示没有历史数据。

        history = self._read_json(history_file)
        # 使用 _read_json 读取历史文件，返回列表（每个元素是一条对话记录）。

        logger.debug(f"session_id={session_id}, 成功查询对话历史")
        # 记录日志：成功查询到对话历史。

        return history
        # 返回对话历史列表。

    def insert_session_history(self, session_id, user, assistant):
        # 向指定会话的对话历史中添加一条问答记录。
        # 参数 session_id：会话的唯一标识符。
        # 参数 user：用户发送的消息内容（字符串）。
        # 参数 assistant：助手（AI）回复的消息内容（字符串）。
        # 返回值：True 表示插入成功。

        def updater(history):
            # 定义内部函数 updater，作为 _update_json 的回调。
            # 参数 history：当前对话历史列表。

            history.append({
                # 在历史列表末尾添加一条新的问答记录。
                'id': self._get_next_id(history),
                # 自动分配一个自增 ID。
                'type': 'qa',
                # 记录类型为 'qa'（Question and Answer，问答）。
                # 这个字段用于区分不同类型的记录（问答 vs 事件）。
                'user': user,
                # 用户输入的消息。
                'assistant': assistant,
                # AI 助手的回复。
                'timestamp': datetime.now().isoformat()
                # 记录当前时间戳。
            })
            logger.debug(f"session_id={session_id}, 成功插入对话历史")
            # 记录日志：插入成功。
            return True
            # 返回 True。

        return self._update_json(
            os.path.join(self._history_dir, f'{session_id}.json'), updater)
        # 调用 _update_json，传入该会话的历史文件路径和 updater 函数。
        # 注意这里没有使用 self._history_file，而是动态拼接路径，
        # 因为每个会话的历史文件路径不同（取决于 session_id）。

    def insert_session_event(self, session_id, event_type, files):
        # 记录一个会话级操作事件（如上传文件、删除文件等）。
        # 这个事件会和普通问答记录一起追加到同一个历史文件中。
        #
        # 参数 session_id：会话的唯一标识符。
        # 参数 event_type：事件类型，可以是 'upload'（上传）、'delete'（删除）、
        #                  'delete_all'（全部删除）等字符串。
        # 参数 files：受影响的文件名列表（list[str]），delete_all 时可以为空列表。
        # 返回值：True 表示记录成功，False 表示 session_id 为空。

        """记录会话级操作事件 (上传 / 删除文件等), 与 qa 条目一起追加到同一历史文件。

        event_type: 'upload' | 'delete' | 'delete_all'
        files:     list[str] 受影响的文件名 (delete_all 时可为空)
        """

        if not session_id:
            # 如果 session_id 为空（None 或空字符串），直接返回失败。
            return False

        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        # 拼接出该会话对应的历史文件路径。

        history = []
        # 初始化历史列表为空列表（作为文件不存在的默认值）。

        if os.path.exists(history_file):
            # 如果历史文件已存在，才读取现有数据。
            history = self._read_json(history_file)
            # 读取现有的对话历史。

        history.append({
            # 在历史列表末尾添加一条事件记录。
            'id': self._get_next_id(history),
            # 自动分配一个自增 ID。
            'type': 'event',
            # 记录类型为 'event'（事件），区别于 'qa'（问答）。
            'event_type': event_type,
            # 事件的具体类型，如 'upload'、'delete' 等。
            'files': list(files or []),
            # 受影响的文件列表。files or [] 的意思是：如果 files 为 None 则使用空列表。
            # 然后用 list() 确保它是一个列表类型。
            'timestamp': datetime.now().isoformat()
            # 记录当前时间戳。
        })

        self._write_json(history_file, history)
        # 使用 _write_json 直接写入整个历史列表（覆盖写入，不是原子更新）。
        # 注意这里没有使用 _update_json，因为读和写之间没有需要保持原子性的复杂逻辑。

        logger.debug(f"session_id={session_id}, 记录事件: {event_type} -> {files}")
        # 记录日志：事件已记录。

        return True
        # 返回 True，表示操作成功。

    def delete_session_history(self, session_id):
        # 删除指定会话的整个对话历史文件。
        # 参数 session_id：会话的唯一标识符。
        # 返回值：True 表示删除成功，False 表示历史文件不存在。

        history_file = os.path.join(self._history_dir, f'{session_id}.json')
        # 拼接出该会话对应的历史文件路径。

        if os.path.exists(history_file):
            # 如果历史文件存在...
            os.remove(history_file)
            # 使用 os.remove 删除该文件。
            logger.debug(f"session_id={session_id}, 成功删除对话历史")
            # 记录日志：删除成功。
            return True
            # 返回 True。

        return False
        # 如果文件不存在，返回 False。

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

    # --- 归档 ---------------------------------------------------------------
    # 以下方法用于操作归档数据（archives/ 目录下的 JSON 文件）。
    # 归档功能用于将较长的对话历史打包存储，避免单个历史文件过大。

    def insert_archive(self, session_id, summary, turns):
        # 将一组对话轮次归档存储为一个独立的归档文件。
        # 参数 session_id：原始会话的 ID。
        # 参数 summary：归档摘要（对整段对话的总结文本）。
        # 参数 turns：对话轮次列表，每个元素是一条对话记录。
        # 返回值：新创建的归档 ID 字符串。

        """将历史轮次归档存储，返回 archive_id。"""

        import uuid as _uuid
        # 在函数内部导入 uuid 模块（一种常见的延迟导入写法），
        # uuid 用于生成全局唯一标识符（Universally Unique Identifier）。

        archive_id = f"arch_{_uuid.uuid4().hex[:12]}"
        # 生成归档 ID：前缀 "arch_" + UUID 的十六进制字符串的前 12 位。
        # uuid4() 生成一个随机 UUID，.hex 返回 32 位十六进制字符串，
        # [:12] 只取前 12 位，这样生成的 ID 简短且基本保证唯一性。

        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')
        # 拼接出归档文件的完整路径，例如 "data/json_store/archives/arch_xxxx.json"。

        os.makedirs(os.path.dirname(archive_file), exist_ok=True)
        # 确保归档目录存在（虽然 __init__ 中已经创建过，但这里再次确保以防万一）。

        self._write_json(archive_file, {
            # 使用 _write_json 将归档数据写入文件。
            'id': archive_id,
            # 归档的唯一 ID。
            'session_id': session_id,
            # 原始会话的 ID。
            'summary': summary,
            # 归档摘要，通常是 LLM 生成的对话总结。
            'turns': turns,
            # 完整的对话轮次列表（用户问题和助手回复的交替序列）。
            'created_at': datetime.now().isoformat(),
            # 归档创建时间。
        })
        logger.info(f"归档创建: {archive_id} ({len(turns)} 轮)")
      
        return archive_id
        # 返回新生成的归档 ID，调用者可以用这个 ID 来查找或读取归档内容。

    def get_archive(self, archive_id):
        # 根据归档 ID 读取归档内容。
        # 参数 archive_id：归档的唯一标识符。
        # 返回值：如果找到归档文件，返回包含完整归档数据的字典；
        #         如果文件不存在，返回 None。

        """按 ID 读取归档，返回完整内容或 None。"""

        archive_file = os.path.join(self._archive_dir, f'{archive_id}.json')
        # 拼接出归档文件的完整路径。

        if not os.path.exists(archive_file):
            # 如果归档文件不存在...
            logger.warning(f"归档不存在: {archive_id}")
            # 记录警告日志：归档不存在。
            return None
            # 返回 None。

        return self._read_json(archive_file)
        # 使用 _read_json 读取归档文件内容并返回（返回一个字典）。

    def format_archive_turns(self, archive_id):
        # 读取归档数据并将其中的对话轮次格式化为人类（或 LLM）可读的文本。
        # 参数 archive_id：归档的唯一标识符。
        # 返回值：如果找到归档，返回格式化后的字符串；如果归档不存在，返回 None。

        """读取归档并格式化为 LLM 可读的文本。"""

        data = self.get_archive(archive_id)
        # 调用 get_archive 方法读取归档数据。

        if not data:
            # 如果 data 为 None（归档不存在）...
            return None
            # 返回 None。

        lines = [f"[归档 {archive_id}] 以下为历史对话记录："]
        # 初始化字符串列表，第一行是一个标题，提示这是来自哪个归档的历史记录。
        # 使用 f-string（格式化字符串）将 archive_id 动态嵌入到字符串中。

        for t in data.get('turns', []):
            # 遍历归档中的 turns 列表（如果没有 'turns' 键，默认使用空列表）。
            # t 是每个轮次的字典，包含 'user' 和 'assistant' 等字段。
            if t.get('user'):
                # 如果这条记录包含用户消息（不为 None 且不为空字符串）...
                lines.append(f"用户：{t['user']}")
                # 添加一行：用户消息。
            if t.get('assistant'):
                # 如果这条记录包含助手回复...
                lines.append(f"助手：{t['assistant']}")
                # 添加一行：助手回复。

        return "\n\n".join(lines)
        # 使用 "\n\n"（两个换行符，即一个空行）将 lines 列表中的所有行连接成一个字符串。
        # 这样每条消息之间会有一个空行，便于阅读。


# ===== 程序入口（直接运行此文件时的测试代码） =====

if __name__ == "__main__":
    # 这个条件判断：只有当这个文件被直接执行时（而不是被其他文件 import 时），
    # 下面的代码才会运行。
    # 如果这个文件被 import 到其他模块中，__name__ 会是模块名（"json_store"），
    # 而不是 "__main__"，所以下面的代码不会执行。
    # 这样做的目的是让测试代码只在直接运行时生效，不影响被导入时的正常使用。

    store = JSONFileStore()
    # 创建一个 JSONFileStore 的实例（使用默认的 data_dir 配置）。

    store.insert_user("test", "123456")
    # 调用 insert_user 方法，插入一个测试用户（用户名 "test"，密码 "123456"，角色默认 "user"）。

    print("Credentials check:", store.check_user_credentials("test", "123456"))
    # 调用 check_user_credentials 验证刚才插入的用户凭据，
    # 并将结果打印到控制台。如果验证成功，会打印用户信息字典。
