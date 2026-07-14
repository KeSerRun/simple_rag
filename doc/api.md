# API 模块

> 位置：`api/` — FastAPI HTTP 接口

## 路由概览

```
FastAPI 应用 (app.py)
│
├── /api/auth           → api/auth.py       JWT 认证 (登录/注册/Token 刷新)
├── /api/query          → api/query.py      问答接口 (非流式 + SSE 流式)
├── /api/history        → api/history.py    会话历史
├── /api/sessions       → api/sessions.py   会话管理
├── /api/documents      → api/documents.py  文档上传/列表/图片服务
├── /api/admin          → api/admin/        管理后台 (6 个子模块)
├── /api/health         → app.py            健康检查
│
├── /                   → app.py            前端首页 (index.html)
└── /assets, /images    → app.py            静态资源/图片
```

## 认证 (/api/auth)

**文件**: [auth.py](../api/auth.py)

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 登录返回 JWT |
| `/api/auth/refresh` | POST | 刷新 Token |
| `/api/auth/me` | GET | 当前用户信息 |

JWT 认证使用 `jwt_secret_key`（缺省时基于 `chat_api_key` 派生）、`jwt_algorithm=HS256`。

## 问答 (/api/query)

**文件**: [query.py](../api/query.py)

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/query` | POST | 非流式问答 |
| `/api/query/stream` | POST | SSE 流式问答 |

流式支持以下事件类型：
- `token` — 文本 token
- `reasoning` — 推理过程
- `status` — 状态更新（start/tool_call/tool_result/end/error/cancelled）

## 文档 (/api/documents)

**文件**: [documents.py](../api/documents.py)

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/documents/upload` | POST | 上传文档 |
| `/api/documents/list` | GET | 用户文档列表 |
| `/api/documents/delete` | DELETE | 删除文档 |
| `/api/documents/image/{source}/{path}` | GET | 文档内嵌图片服务 |

## 管理后台 (/api/admin)

**文件**: [admin/](../api/admin/)

| 模块 | 文件 | 功能 |
|------|------|------|
| 仪表盘 | `dashboard.py` | 请求统计、系统状态 |
| 配置 | `config.py` | 配置读取/更新/schema |
| 数据管理 | `database.py` | 向量库统计/分区/切块/系统数据上传 |
| 评估 | `eval.py` | RAG 检索质量评估 |
| 日志 | `logs.py` | 日志文件查看/下载 |
| 用户管理 | `users.py` | 用户 CRUD/角色/密码 |

### 配置热更新

前端页面修改 → PUT `/api/admin/config` → `_write_config_ini` 行级替换 config.ini → 同时更新内存中 `conf` 对象 → 即时生效。

### 评估系统

评估流程：加载测试查询 → 逐条检索 → LLM 打分 0-4 → 统计精确率 Precision@K。支持后台异步执行，前端轮询进度。

## 鉴权依赖

**文件**: [deps.py](../api/deps.py)

| 依赖 | 说明 |
|------|------|
| `auth_required` | 需有效 JWT |
| `admin_required` | 需 admin 角色 |
