# 数据存储模块 — `backend/storage/`

提供持久化数据存储，负责保存用户信息、会话记录、聊天历史等结构化数据。支持 JSON 文件和 SQLite 两种后端。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `json_store.py` | JSON 文件存储。`DataStore` 类，数据保存在 `data/*.json` 文件中。**当前默认存储后端** |
| `sqlite_store.py` | SQLite 数据库存储。备用存储后端，功能与 JSON 版本一致 |
| `__init__.py` | 根据配置导出 `DataStore` 别名：使用 JSON 或 SQLite |

---

## 调用方式

### 1. 初始化

```python
# 自动根据 config.ini 的 storage.backend 选择后端
from storage import DataStore
store = DataStore()  # 默认使用 JSON 存储

# 手动指定文件路径
store = DataStore(file_path="data/my_data.json")
```

### 2. 用户管理

```python
# 创建用户
store.create_user("张三", "password123", role="user")

# 查询用户
user = store.get_user("张三")
print(user.username)   # "张三"
print(user.role)       # "user"
print(user.password)   # 密码哈希值

# 列出所有用户
users = store.get_all_users()
for u in users:
    print(f"{u.username} ({u.role})")

# 更新用户角色
store.update_user_role("张三", "admin")

# 重置密码
store.update_password("张三", "new_password")

# 删除用户
store.delete_user("张三")
```

### 3. 会话管理

```python
# 创建新会话
session = store.create_session(
    session_id="session_001",
    username="张三",
    title="沪深300分析",
)

# 获取用户的所有会话
sessions = store.get_user_sessions("张三")
for s in sessions:
    print(f"{s.session_id}: {s.title} ({s.created_at})")

# 删除会话
store.delete_session("session_001")
```

### 4. 消息记录

```python
# 保存消息
store.save_message(
    session_id="session_001",
    role="user",
    content="沪深300最近表现如何？",
)

# 获取会话消息历史
messages = store.get_messages("session_001")
for msg in messages:
    print(f"[{msg.role}] {msg.content[:50]}...")

# 获取用户的完整聊天记录
history = store.get_history("张三")
```

### 5. 存储统计

```python
stats = store.get_stats()
print(stats)
# {
#     "type": "json",
#     "data_file": "data/data.json",
#     "file_size_bytes": 102400,
#     "users": 5,
#     "sessions": 12,
#     "messages": 1024,
# }
```

---

## 存储后端切换

编辑 `config.ini` 的 `[storage]` 节：

```ini
[storage]
# 可选值: json (默认) 或 sqlite
backend = sqlite
data_dir = data
```

切换后端后数据**不会自动迁移**，需手动复制或重新导入。

---

## 数据结构

### JSON 文件结构 (`data/data.json`)
```json
{
  "users": {
    "张三": {
      "username": "张三",
      "password": "<bcrypt 哈希>",
      "role": "user",
      "created_at": "2026-07-08T..."
    }
  },
  "sessions": {
    "session_001": {
      "session_id": "session_001",
      "username": "张三",
      "title": "沪深300分析",
      "system_prompt": "..."
    }
  },
  "messages": [
    {
      "session_id": "session_001",
      "role": "user",
      "content": "你好"
    }
  ]
}
```

---

## 依赖关系

```
json_store.py ──→ base.config (conf.data_dir)
sqlite_store.py ──→ base.config / base.logger
__init__.py ──→ json_store / sqlite_store
（两个存储后端互不依赖，可独立使用）
```
