# ===== 模块文档字符串（模块整体说明） =====
# 这是一个多行字符串（docstring），用来说明这个文件的作用和用法
# 它描述了基于 SQLite 的持久化存储，接口与 JSONFileStore 完全一致
"""
基于 SQLite 的持久化存储，接口与 JSONFileStore 完全一致。

用法:
    from storage import SQLiteStore
    store = SQLiteStore()
    store.insert_user("admin", "xxx", role="admin")

优势 vs JSONFileStore:
    - 查询效率: SQL 索引替代 O(n) JSON 全表扫描
    - 并发安全: WAL 模式 + 事务，比文件锁更健壮
    - 数据一致性: 外键约束防止孤立记录
    - 零依赖: 仅使用 Python 标准库 sqlite3
"""

# ===== 导入标准库模块 =====
# 导入 json 模块，用于处理 JSON 数据的序列化（将 Python 对象转成 JSON 字符串）和反序列化（将 JSON 字符串转回 Python 对象）
import json
# 导入 os 模块，用于和操作系统交互，比如创建目录、拼接文件路径等
import os
# 导入 sqlite3 模块，这是 Python 自带的 SQLite 数据库操作库，不需要额外安装
import sqlite3
# 导入 threading 模块，用于创建线程锁，保证多线程环境下的数据安全
import threading
# 从 datetime 模块中导入 datetime 类，用于获取当前时间戳
from datetime import datetime
# 从 typing 模块中导入 Optional 类型，用于类型注解，表示某个参数可以传 None
from typing import Optional

# ===== 导入项目内部模块 =====
# 从 base.config 模块中导入 conf 对象，conf 是项目的全局配置对象，里面保存了各种配置项（比如数据目录路径）
from base.config import conf
from base.logger import logger
from .base import BaseStore


# ===== 定义 SQLiteStore 类 =====
# class 关键字用来定义一个类，SQLiteStore 是基于 SQLite 的持久化存储类
# 它的接口设计得和 JSONFileStore 一模一样，方便替换使用
class SQLiteStore(BaseStore):
    """基于 SQLite 的持久化存储。

    文件结构:
        data/store.db  — 单文件 SQLite 数据库（含 users / sessions / history / archives 四张表）

    线程安全:
        使用 threading.Lock 序列化写操作（与 JSONFileStore 一致），
        读操作不持锁（SQLite 自身通过 WAL 模式处理读并发）。
    """

    # ===== __init__ 方法：类的构造函数 =====
    # 当创建 SQLiteStore 对象时，会自动调用这个方法
    # db_path 参数是可选的，如果不传，就使用默认路径（conf.data_dir 下的 store.db）
    def __init__(self, db_path: Optional[str] = None):
        # 设置 self.db_path 属性，保存数据库文件的完整路径
        # 如果调用方传了 db_path 就用传进来的，否则在配置的数据目录下创建 store.db 文件
        self.db_path = db_path or os.path.join(conf.data_dir, "store.db")
        # 创建一个线程锁对象，用于保护写操作，防止多个线程同时写数据库导致数据错乱
        self._lock = threading.Lock()
        # 调用 _init_db 方法，初始化数据库（创建表、索引，启用 WAL 模式等）
        self._init_db()
        # 使用 logger 记录一条信息日志，表示 SQLiteStore 已经初始化完成，并打印数据库文件路径
        logger.info(f"SQLiteStore 就绪: {self.db_path}")

    # ===== 数据库初始化相关方法（内部使用） =====
    # 下面的方法是以下划线 _ 开头的，按照 Python 惯例，表示"内部使用、不要在外面直接调用"
    # ─── 数据库初始化 ─────────────────────────────────

    # 定义 _init_db 方法，用来初始化数据库：创建表、索引，启用 WAL 模式
    def _init_db(self):
        """建表（含索引），启用 WAL 模式。"""
        # 确保数据库文件所在的目录存在，如果不存在就自动创建
        # os.path.dirname 获取 db_path 的目录部分，os.makedirs 递归创建目录
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # 使用 with 语句获取数据库连接，with 会自动帮我们关闭连接
        # _get_conn 是一个内部方法，用来获取一个新的 SQLite 连接对象
        with self._get_conn() as conn:
            # 执行 PRAGMA 语句，将 SQLite 的日志模式设置为 WAL（Write-Ahead Logging）
            # WAL 模式允许多个读操作和一个写操作同时进行，提高了并发性能
            conn.execute("PRAGMA journal_mode=WAL")
            # 启用外键约束，这样 SQLite 会检查外键关系，防止出现孤立数据
            conn.execute("PRAGMA foreign_keys=ON")

            # 执行一段 SQL 脚本（多条 SQL 语句一起执行），创建四张表
            conn.executescript("""
                -- 创建 users 表（用户表），用于存储用户信息
                CREATE TABLE IF NOT EXISTS users (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键，每插入一条数据自动加 1
                    username  TEXT    NOT NULL UNIQUE,             -- 用户名，不能为空，且必须唯一
                    password  TEXT    NOT NULL,                    -- 密码，不能为空
                    role      TEXT    NOT NULL DEFAULT 'user',     -- 角色，默认是普通用户 'user'
                    created_at TEXT   NOT NULL                     -- 创建时间，存储为文本格式的时间戳
                );
                -- 在 users 表的 username 字段上创建索引，加速按用户名查询的速度
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

                -- 创建 sessions 表（会话表），用于存储用户登录会话
                CREATE TABLE IF NOT EXISTS sessions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                    session_id TEXT    NOT NULL UNIQUE,             -- 会话 ID，全局唯一
                    username   TEXT    NOT NULL,                    -- 会话所属的用户名
                    created_at TEXT    NOT NULL,                    -- 会话创建时间
                    -- 外键约束：username 引用 users 表的 username，当用户被删除时，自动级联删除该用户的所有会话
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                );
                -- 在 sessions 表的 username 字段上创建索引，加速按用户名查会话
                CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);

                -- 创建 history 表（对话历史表），存储用户和 AI 的聊天记录
                CREATE TABLE IF NOT EXISTS history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                    session_id  TEXT    NOT NULL,                    -- 所属会话 ID
                    type        TEXT    NOT NULL DEFAULT 'qa',       -- 记录类型，'qa' 表示问答记录，'event' 表示事件记录
                    user_text   TEXT,                                -- 用户发送的文本内容
                    assistant   TEXT,                                -- AI 助手的回复文本
                    event_type  TEXT,                                -- 事件类型（比如上传文件、删除文件等），仅 type='event' 时有效
                    files_json  TEXT,                                -- 文件列表的 JSON 字符串，记录事件涉及的文件
                    timestamp   TEXT    NOT NULL,                    -- 这条历史记录的创建时间
                    -- 外键约束：session_id 引用 sessions 表的 session_id，当会话被删除时，自动级联删除该会话的所有历史
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                -- 在 history 表的 session_id 字段上创建索引，加速按会话 ID 查询历史记录
                CREATE INDEX IF NOT EXISTS idx_history_session_id ON history(session_id);

                -- 创建 session_tasks 表（会话任务表），存储短期/长期任务状态
                CREATE TABLE IF NOT EXISTS session_tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL UNIQUE,
                    tasks_json  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_tasks_sid ON session_tasks(session_id);

                -- 创建 archives 表（归档表），用于存储归档的对话记录（压缩存储，方便回顾）
                CREATE TABLE IF NOT EXISTS archives (
                    archive_id  TEXT    PRIMARY KEY,                 -- 归档 ID，主键，唯一标识一个归档
                    session_id  TEXT    NOT NULL,                    -- 对应的会话 ID
                    summary     TEXT    NOT NULL,                    -- 归档摘要，简要描述这段对话的内容
                    turns_json  TEXT    NOT NULL,                    -- 完整对话轮次的 JSON 字符串
                    created_at  TEXT    NOT NULL,                    -- 归档创建时间
                    -- 外键约束：当会话被删除时，归档的 session_id 被设为 NULL（保留归档但断开关联）
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
                );
                -- 在 archives 表的 session_id 字段上创建索引，加速按会话 ID 查询归档
                CREATE INDEX IF NOT EXISTS idx_archives_session_id ON archives(session_id);
            """)

    # 定义 _get_conn 方法，用于获取一个新的 SQLite 数据库连接
    # 返回值类型注解 -> sqlite3.Connection 表示这个方法返回一个 SQLite 连接对象
    def _get_conn(self) -> sqlite3.Connection:
        """获取新的数据库连接（每个调用方独立连接，避免跨线程共用）。"""
        # 调用 sqlite3.connect 方法连接到数据库文件，返回一个连接对象
        conn = sqlite3.connect(self.db_path)
        # 设置连接的行工厂为 sqlite3.Row，这样查询结果可以通过列名访问（像字典一样）
        # 默认返回的是元组，只能用下标访问，设置后更方便
        conn.row_factory = sqlite3.Row
        # 每次获取连接时都启用外键约束，确保数据完整性
        conn.execute("PRAGMA foreign_keys=ON")
        # 返回这个连接对象
        return conn

    # 定义 _now 方法，获取当前时间的 ISO 格式字符串
    # 返回类型是 str（字符串）
    def _now(self) -> str:
        # 调用 datetime.now() 获取当前时间，然后调用 isoformat() 方法转成标准格式的字符串
        # 例如：'2024-01-15T10:30:00.123456'
        return datetime.now().isoformat()

    # ===== 用户管理相关方法（增删改查） =====
    # 这些方法是对 users 表的操作，每个方法都做了日志记录
    # ─── 用户 ─────────────────────────────────────────

    # 定义 insert_user 方法：向 users 表插入一个新用户
    # username: 用户名, password: 密码, role: 角色（默认是普通用户 "user"）
    # 返回值类型是 bool（布尔值），True 表示插入成功，False 表示用户已存在
    def insert_user(self, username: str, password: str, role: str = "user") -> bool:
        """插入用户。已存在（含大小写变体）时返回 False。"""
        # 使用线程锁保护写操作，同一时间只有一个线程能执行这里的代码
        # with self._lock 是获取锁，执行完代码后自动释放锁
        with self._lock:
            # 使用 try 语句捕获可能出现的异常
            try:
                # 获取数据库连接，with 语句结束后自动关闭连接
                with self._get_conn() as conn:
                    # 执行 INSERT 语句向 users 表插入一条新记录
                    # 使用 ? 作为占位符，后面用元组提供实际值，这样可以防止 SQL 注入攻击
                    conn.execute(
                        "INSERT INTO users (username, password, role, created_at) VALUES (?, ?, ?, ?)",
                        (username, password, role, self._now()),
                    )
                # 日志记录：插入用户成功
                logger.info(f"成功插入用户: {username}")
                # 返回 True 表示插入成功
                return True
            # 捕获 sqlite3.IntegrityError 异常，这个异常在违反数据库约束时触发
            # 比如 username 字段设置了 UNIQUE，插入重复用户名就会报这个错
            except sqlite3.IntegrityError:
                # 日志记录：用户已存在，跳过插入
                logger.info(f"用户 '{username}' 已存在,跳过插入")
                # 返回 False 表示插入失败（用户已存在）
                return False

    # 定义 delete_user 方法：从 users 表删除一个用户
    # username: 要删除的用户名
    # 返回值是 bool，True 表示删除成功，False 表示用户不存在
    def delete_user(self, username: str) -> bool:
        """删除用户。不存在时返回 False。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 DELETE 语句删除指定用户名的记录
                # 返回的是游标对象（cursor），通过它可以知道影响了多少行
                cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
                # rowcount 表示被删除的行数，如果是 0 说明没有找到这个用户
                if cur.rowcount == 0:
                    # 没有找到用户，返回 False
                    return False
                # 日志记录：成功删除用户
                logger.info(f"成功删除用户: {username}")
                # 返回 True 表示删除成功
                return True

    # 定义 check_user_credentials 方法：验证用户名和密码是否正确
    # username: 用户名, password: 密码
    # 返回值：验证成功返回包含用户信息的字典，失败返回 False
    def check_user_credentials(self, username: str, password: str):
        """验证用户凭据。成功返回 {username, role}，失败返回 False。"""
        # 获取数据库连接（读操作不需要持锁，SQLite 的 WAL 模式可以处理读并发）
        with self._get_conn() as conn:
            # 执行 SELECT 查询，从 users 表中查找用户名和密码都匹配的记录
            # .fetchone() 方法只取查询结果的第一行，如果没有匹配的则返回 None
            row = conn.execute(
                "SELECT username, role FROM users WHERE LOWER(username) = LOWER(?) AND password = ?",
                (username, password),
            ).fetchone()
            # 判断是否找到了匹配的记录
            if row:
                # 日志记录：用户验证成功
                logger.info(f"成功验证用户凭据: {username}")
                # 返回一个字典，包含用户名和角色
                # 因为 conn.row_factory 设置成了 sqlite3.Row，所以可以通过列名访问
                return {"username": row["username"], "role": row["role"]}
            # 没有找到匹配的记录，返回 False 表示验证失败
            return False

    # 定义 get_all_users 方法：分页查询所有用户
    # page: 页码，从 1 开始，默认第 1 页
    # page_size: 每页显示多少条，默认 20 条
    # 返回值是一个字典，包含 items（用户列表）和 total（用户总数）
    def get_all_users(self, page: int = 1, page_size: int = 20) -> dict:
        """分页查询所有用户。返回 {"items": [...], "total": N}。"""
        # 计算偏移量：第 1 页偏移 0，第 2 页偏移 page_size，以此类推
        offset = (page - 1) * page_size
        # 获取数据库连接（读操作不持锁）
        with self._get_conn() as conn:
            # 查询用户总数，COUNT(*) 是 SQL 的聚合函数，返回表中的记录数
            # .fetchone()[0] 取第一行第一列的值，也就是总数
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            # 按条件查询用户列表，按 id 倒序排列（最新的在前），并使用 LIMIT 和 OFFSET 实现分页
            rows = conn.execute(
                "SELECT username, role, created_at FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()  # fetchall() 获取所有匹配的行
        # 把查询结果（sqlite3.Row 对象列表）转成普通的字典列表
        # dict(r) 将 Row 对象转成字典，列表推导式 [dict(r) for r in rows] 批量转换
        items = [dict(r) for r in rows]
        # 返回包含用户列表和总数的字典
        return {"items": items, "total": total}

    # 定义 update_user_role 方法：更新用户的角色
    # username: 用户名, new_role: 新的角色名
    # 返回值是 bool，True 表示更新成功，False 表示用户不存在
    def update_user_role(self, username: str, new_role: str) -> bool:
        """更新用户角色。不存在时返回 False。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 UPDATE 语句，更新匹配用户的 role 字段
                # cur 是游标对象，rowcount 表示被更新的行数
                cur = conn.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))
                # 如果 rowcount > 0 说明有记录被更新了，返回 True；否则返回 False
                return cur.rowcount > 0

    # 定义 update_user_password 方法：更新用户的密码
    # username: 用户名, new_password: 新密码
    # 返回值是 bool，True 表示更新成功，False 表示用户不存在
    def update_user_password(self, username: str, new_password: str) -> bool:
        """更新用户密码。不存在时返回 False。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 UPDATE 语句，更新匹配用户的 password 字段
                cur = conn.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, username))
                # 如果 rowcount > 0 说明有记录被更新了，返回 True；否则返回 False
                return cur.rowcount > 0

    # ===== 会话管理相关方法 =====
    # 这些方法是对 sessions 表的操作，管理用户登录会话
    # ─── 会话 ─────────────────────────────────────────

    # 定义 insert_session 方法：插入一个新的会话记录
    # session_id: 会话的唯一标识, username: 所属用户名
    # 返回值是 bool，True 表示插入成功，False 表示会话 ID 已存在
    def insert_session(self, session_id: str, username: str) -> bool:
        """插入会话。已存在时返回 False。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 使用 try 语句捕获可能的主键重复异常
            try:
                # 获取数据库连接
                with self._get_conn() as conn:
                    # 执行 INSERT 语句向 sessions 表插入一条新会话记录
                    conn.execute(
                        "INSERT INTO sessions (session_id, username, created_at) VALUES (?, ?, ?)",
                        (session_id, username, self._now()),
                    )
                # 日志记录：成功插入会话
                logger.debug(f"成功插入用户会话: session_id={session_id}, username={username}")
                # 返回 True 表示插入成功
                return True
            # 捕获唯一约束异常（session_id 重复时触发）
            except sqlite3.IntegrityError:
                # 会话已存在，返回 False
                return False

    # 定义 delete_session 方法：删除一个会话
    # session_id: 要删除的会话 ID
    # 返回值是 bool，True 表示删除成功，False 表示会话不存在
    # 注意：由于外键设置了 ON DELETE CASCADE，删除会话时会自动删除该会话的所有历史记录
    def delete_session(self, session_id: str) -> bool:
        """删除会话（级联删除关联的 history 记录）。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 DELETE 语句删除指定 session_id 的会话
                cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                # 如果 rowcount == 0，说明没有找到这个会话，返回 False
                if cur.rowcount == 0:
                    return False
                # 日志记录：成功删除会话
                logger.debug(f"成功删除用户会话: session_id={session_id}")
                # 返回 True 表示删除成功
                return True

    # 定义 fetch_sessions_by_username 方法：查询某个用户的所有会话
    # username: 用户名
    # 返回值：会话列表（每个会话包含 id、创建时间和首条消息摘要），没有会话时返回 None
    def fetch_sessions_by_username(self, username: str):
        """查询用户的所有会话（含首条消息摘要）。"""
        # 获取数据库连接（读操作不持锁）
        with self._get_conn() as conn:
            # 查询该用户的所有会话，按 id 倒序排列（最新的在前面）
            rows = conn.execute(
                "SELECT session_id, created_at FROM sessions WHERE username = ? ORDER BY id DESC",
                (username,),
            ).fetchall()  # 获取所有匹配的行

        # 如果查询结果为空列表（没有查到任何会话）
        if not rows:
            # 返回 None 表示没有会话
            return None

        # 创建一个空列表，用来存放处理后的会话信息
        result = []
        # 遍历查询结果的每一行
        for r in rows:
            # 从当前行取出 session_id 字段的值
            sid = r["session_id"]
            # 取首条用户消息作为会话摘要
            # 先初始化为空字符串
            first_msg = ""
            # 调用 get_session_history 方法获取该会话的历史记录
            history = self.get_session_history(sid)
            # 如果历史记录存在且不为空列表
            if history and len(history) > 0:
                # 取第一条记录的 user_text 或 user 字段，如果都没有就取空字符串
                # 然后用 [:40] 截取前 40 个字符，作为简短摘要
                first_msg = (history[0].get("user_text") or history[0].get("user") or "")[:40]
            # 把处理好的会话信息添加到结果列表中
            result.append({
                "id": sid,                # 会话 ID
                "created_at": r["created_at"],  # 创建时间
                "first_msg": first_msg,   # 首条消息摘要
            })
        # 返回会话列表
        return result

    # ===== 对话历史管理相关方法 =====
    # 这些方法是对 history 表的操作，管理用户和 AI 之间的聊天记录
    # ─── 对话历史 ─────────────────────────────────────

    # 定义 get_session_history 方法：读取某个会话的全部历史记录
    # session_id: 会话 ID
    # 返回值：历史记录列表（每条记录是字典格式），没有记录时返回 None
    def get_session_history(self, session_id: str):
        """读取某个会话的全部历史记录。"""
        # 获取数据库连接（读操作不持锁）
        with self._get_conn() as conn:
            # 查询该会话的所有历史记录，按 id 升序排列（从旧到新）
            rows = conn.execute(
                "SELECT type, user_text, assistant, event_type, files_json, timestamp "
                "FROM history WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()  # 获取所有行

        # 如果查询结果为空，说明没有历史记录
        if not rows:
            # 返回 None
            return None

        # 创建一个空列表，用来存放处理后的历史记录
        history = []
        # 遍历查询结果的每一行
        for r in rows:
            # 获取当前记录的类型（'qa' 或 'event'）
            entry_type = r["type"]
            # 如果类型是 'event'（表示这是一个事件记录，比如文件上传/删除）
            if entry_type == "event":
                # 向历史列表添加一条事件记录
                history.append({
                    "type": "event",                                      # 记录类型：事件
                    "event_type": r["event_type"],                       # 事件类型（如上传、删除）
                    "files": json.loads(r["files_json"]) if r["files_json"] else [],  # 文件列表，从 JSON 字符串解析回 Python 列表
                    "timestamp": r["timestamp"],                         # 事件发生时间
                })
            else:
                # 类型是 'qa'（问答记录），向历史列表添加一条问答记录
                history.append({
                    "type": "qa",                                         # 记录类型：问答
                    "user": r["user_text"] or "",                        # 用户消息，如果为 None 则取空字符串
                    "assistant": r["assistant"] or "",                   # AI 回复，如果为 None 则取空字符串
                    "timestamp": r["timestamp"],                         # 消息时间
                })

        # 日志记录：成功查询到对话历史
        logger.debug(f"session_id={session_id}, 成功查询对话历史")
        # 返回处理后的历史记录列表
        return history

    # 定义 insert_session_history 方法：插入一条 QA 对话记录
    # session_id: 会话 ID, user: 用户消息, assistant: AI 回复
    # 返回值是 bool，始终返回 True（只要不出异常就是成功）
    def insert_session_history(self, session_id: str, user: str, assistant: str) -> bool:
        """插入一条 QA 对话记录。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 INSERT 语句，向 history 表插入一条类型为 'qa' 的记录
                conn.execute(
                    "INSERT INTO history (session_id, type, user_text, assistant, timestamp) "
                    "VALUES (?, 'qa', ?, ?, ?)",
                    (session_id, user, assistant, self._now()),
                )
            # 日志记录：成功插入对话历史
            logger.debug(f"session_id={session_id}, 成功插入对话历史")
            # 返回 True 表示成功
            return True

    # 定义 insert_session_event 方法：插入一条会话事件记录（比如上传文件、删除文件等）
    # session_id: 会话 ID, event_type: 事件类型, files: 相关的文件列表
    # 返回值是 bool，True 表示成功，False 表示 session_id 为空
    def insert_session_event(self, session_id: str, event_type: str, files: list) -> bool:
        """插入一条会话事件记录（上传/删除文件等）。"""
        # 如果 session_id 为空（None 或空字符串），直接返回 False，不执行插入
        if not session_id:
            return False
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 INSERT 语句，向 history 表插入一条类型为 'event' 的记录
                # files 列表需要先用 json.dumps 转成 JSON 字符串，才能存到数据库的文本字段中
                # ensure_ascii=False 表示不强制转义非 ASCII 字符（比如中文正常显示）
                conn.execute(
                    "INSERT INTO history (session_id, type, event_type, files_json, timestamp) "
                    "VALUES (?, 'event', ?, ?, ?)",
                    (session_id, event_type, json.dumps(files, ensure_ascii=False), self._now()),
                )
            # 日志记录：记录事件成功，打印事件类型和文件列表
            logger.debug(f"session_id={session_id}, 记录事件: {event_type} -> {files}")
            # 返回 True 表示成功
            return True

    # 定义 delete_session_history 方法：删除某个会话的全部历史记录
    # session_id: 会话 ID
    # 返回值是 bool，True 表示删除了至少一条记录，False 表示没有记录被删除
    def delete_session_history(self, session_id: str) -> bool:
        """删除某个会话的全部历史。"""
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 DELETE 语句，删除该会话的所有历史记录
                cur = conn.execute("DELETE FROM history WHERE session_id = ?", (session_id,))
                # 如果 rowcount > 0 说明有记录被删除了，返回 True；否则返回 False
                return cur.rowcount > 0

    # ===== 会话任务持久化 =====
    def save_session_tasks(self, session_id: str, tasks: dict):
        """持久化会话任务数据。"""
        import json
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO session_tasks (session_id, tasks_json, updated_at) "
                    "VALUES (?, ?, ?)",
                    (session_id, json.dumps(tasks, ensure_ascii=False), self._now()),
                )

    def get_session_tasks(self, session_id: str) -> dict:
        """读取会话任务数据，不存在则返回默认空结构。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT tasks_json FROM session_tasks WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row:
            import json
            return json.loads(row[0])
        return {"short": [], "long": []}

    # ===== 归档管理相关方法 =====
    # 这些方法是对 archives 表的操作，用于将对话历史压缩归档保存（方便以后回顾）
    # ─── 归档 ─────────────────────────────────────────

    # 定义 insert_archive 方法：将历史对话轮次归档存储
    # session_id: 会话 ID, summary: 归档摘要, turns: 对话轮次列表
    # 返回值是 str（字符串），即生成的归档 ID
    def insert_archive(self, session_id: str, summary: str, turns: list) -> str:
        """将历史轮次归档存储，返回 archive_id。"""
        # 导入 uuid 模块（在函数内部导入，按需加载），用于生成全局唯一标识符
        import uuid as _uuid
        # 生成归档 ID：前缀 "arch_" 加上 UUID 的前 12 位十六进制字符
        # uuid4() 生成的 UUID 是随机的，.hex 转成十六进制字符串，[:12] 取前 12 个字符
        archive_id = f"arch_{_uuid.uuid4().hex[:12]}"
        # 获取线程锁，保护写操作
        with self._lock:
            # 获取数据库连接
            with self._get_conn() as conn:
                # 执行 INSERT 语句，向 archives 表插入一条归档记录
                # turns 列表需要用 json.dumps 转成 JSON 字符串再存储
                conn.execute(
                    "INSERT INTO archives (archive_id, session_id, summary, turns_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (archive_id, session_id, summary, json.dumps(turns, ensure_ascii=False), self._now()),
                )
        # 日志记录：归档创建成功，并显示归档 ID 和对话轮次数
        logger.info(f"归档创建: {archive_id} ({len(turns)} 轮)")
        # 返回生成的归档 ID
        return archive_id

    # 定义 get_archive 方法：按归档 ID 读取归档记录
    # archive_id: 归档 ID
    # 返回值：包含归档完整信息的字典，如果归档不存在则返回 None
    def get_archive(self, archive_id: str):
        """按 ID 读取归档，返回完整内容或 None。"""
        # 获取数据库连接（读操作不持锁）
        with self._get_conn() as conn:
            # 执行 SELECT 查询，从 archives 表中查找指定 archive_id 的记录
            # .fetchone() 返回第一行，没有匹配时返回 None
            row = conn.execute(
                "SELECT archive_id, session_id, summary, turns_json, created_at FROM archives WHERE archive_id = ?",
                (archive_id,),
            ).fetchone()

        # 如果没有找到匹配的记录
        if not row:
            # 记录警告日志：归档不存在
            logger.warning(f"归档不存在: {archive_id}")
            # 返回 None 表示没有找到
            return None

        # 找到归档记录，将数据库中的字段组装成字典返回
        return {
            "id": row["archive_id"],                          # 归档 ID
            "session_id": row["session_id"],                  # 关联的会话 ID
            "summary": row["summary"],                        # 归档摘要
            "turns": json.loads(row["turns_json"]),           # 对话轮次，从 JSON 字符串解析回 Python 列表
            "created_at": row["created_at"],                  # 归档创建时间
        }

    # 定义 format_archive_turns 方法：读取归档并格式化为人类可读的文本（方便给 LLM 看）
    # archive_id: 归档 ID
    # 返回值：格式化后的文本字符串，如果归档不存在则返回 None
    def format_archive_turns(self, archive_id: str):
        """读取归档并格式化为 LLM 可读的文本。"""
        # 调用 get_archive 方法获取归档数据
        data = self.get_archive(archive_id)
        # 如果归档不存在，直接返回 None
        if not data:
            return None
        # 创建一个列表，第一行是标题，说明这是一段归档的历史对话记录
        lines = [f"[归档 {archive_id}] 以下为历史对话记录："]
        # 遍历归档中的每一轮对话
        for t in data.get("turns", []):      # data.get("turns", []) 安全获取 turns 字段，没有则返回空列表
            # 如果这一轮有用户消息（user 字段不为空）
            if t.get("user"):
                # 添加一行 "用户：[消息内容]"
                lines.append(f"用户：{t['user']}")
            # 如果这一轮有 AI 回复（assistant 字段不为空）
            if t.get("assistant"):
                # 添加一行 "助手：[回复内容]"
                lines.append(f"助手：{t['assistant']}")
        # 将所有行用两个换行符连接起来，形成一段完整的文本
        # "\n\n".join(lines) 在每行之间加一个空行，让阅读更清晰
        return "\n\n".join(lines)
