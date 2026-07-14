# 存储层

> 位置：`storage/` — 数据持久化

## 文件结构

```
storage/
├── __init__.py
├── base.py           # DataStore 抽象基类
└── json_store.py     # JSONFileStore 实现
```

## JSONFileStore

**文件**: [json_store.py](../storage/json_store.py)

基于 JSON 文件的持久化存储。所有数据以独立 JSON 文件形式存储在 `data/` 目录下。

### 存储结构

```
data/
├── users/              # 用户数据
│   └── {username}.json
├── sessions/           # 会话配置
│   └── {session_id}.json
├── history/            # 对话历史
│   ├── {session_id}.json
│   └── arch_{session_id}.json  (压缩前归档)
├── upload_tasks/       # 上传任务状态
├── documents/          # 文档元数据
└── ...
```

### 核心方法

| 方法 | 说明 |
|------|------|
| CRUD | `create_user`, `get_user`, `update_user`, `delete_user` |
| 会话 | `get_session_config`, `save_session_config`, `list_sessions` |
| 历史 | `get_session_history`, `insert_session_turn`, `insert_session_event` |
| 文档 | `get_system_docs`, `save_upload_task`, `list_upload_tasks` |

### 线程安全

内部使用 `threading.RLock` 保证写操作的线程安全。

## DataStore 基类

**文件**: [base.py](../storage/base.py)

定义存储接口抽象基类，当前仅 `JSONFileStore` 一种实现，支持切换后端（如 SQLite/PostgreSQL）。
