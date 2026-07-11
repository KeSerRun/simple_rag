# 数据存储模块 — `backend/storage/`

提供持久化数据存储，负责保存用户信息、会话记录、聊天历史等结构化数据。使用 JSON 文件存储。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `json_store.py` | JSON 文件存储。`JSONFileStore` 类，数据保存在 `data/json_store/*.json` 文件中 |

---

## 调用方式

```python
from storage import JSONFileStore as DataStore
store = DataStore()
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
```
