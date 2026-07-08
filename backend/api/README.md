# API 接口模块 — `backend/api/`

提供后端所有 HTTP API 接口，包括用户认证、智能问答、文档管理、历史记录和后台管理。

---

## 文件说明

### 业务 API（`api/*.py`）

| 文件 | 作用 |
|---|---|
| `auth.py` | 用户认证。`POST /api/auth/login`、`POST /api/auth/register`、JWT 签发 |
| `query.py` | 智能问答。`POST /api/query` 接收用户问题并返回 RAG 回答 |
| `sessions.py` | 会话管理。`GET /api/sessions` 列出/创建/删除对话会话 |
| `history.py` | 历史记录。`GET /api/history/{session_id}` 查看某次会话的聊天记录 |
| `documents.py` | 文档管理。`POST /api/documents/upload` 用户上传自己的 PDF 文档 |
| `deps.py` | 共享依赖。`IntegratedSystem` 单例、`auth_required` 和 `admin_required` 鉴权装饰器 |

### 管理后台 API（`api/admin/*.py`）

| 文件 | 作用 |
|---|---|
| `__init__.py` | 路由器入口。创建 `APIRouter(prefix="/api/admin")`，导入所有子模块 |
| `dashboard.py` | 仪表盘。`GET /api/admin/dashboard` 系统概览统计 |
| `config.py` | 系统设置。`GET/PUT /api/admin/config` 读取/修改 config.ini |
| `users.py` | 用户管理。`GET/POST/DELETE /api/admin/users` 用户 CRUD |
| `logs.py` | 日志查看。`GET /api/admin/logs` 查看/下载日志文件 |
| `database.py` | 数据管理。向量库统计、块浏览、完整性检查、系统文档上传/删除 |
| `eval.py` | 检索评估。`POST /api/admin/eval/run` 启动评估、`GET .../status` 查询进度、`PUT .../queries` 编辑测试查询 |

---

## API 端点一览

### 公开接口（无需登录）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/auth/login` | 登录，返回 JWT token |
| POST | `/api/auth/register` | 注册新用户 |
| GET | `/api/health` | 健康检查（在 app.py 中定义） |

### 用户接口（需登录）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/query` | 发送问答消息 |
| GET | `/api/sessions` | 获取会话列表 |
| POST | `/api/sessions` | 创建新会话 |
| GET | `/api/history/{session_id}` | 获取会话历史 |
| POST | `/api/documents/upload` | 上传个人文档 |

### 管理后台（需 admin 角色）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/admin/dashboard` | 仪表盘数据 |
| GET | `/api/admin/config` | 读取系统配置 |
| PUT | `/api/admin/config` | 更新系统配置 |
| GET | `/api/admin/users` | 用户列表 |
| POST | `/api/admin/users` | 创建用户 |
| DELETE | `/api/admin/users/{name}` | 删除用户 |
| PUT | `/api/admin/users/{name}/role` | 修改用户角色 |
| PUT | `/api/admin/users/{name}/password` | 重置密码 |
| GET | `/api/admin/logs` | 日志文件列表 |
| GET | `/api/admin/database` | 向量库统计 |
| GET | `/api/admin/database/chunks` | 块详情列表 |
| POST | `/api/admin/database/upload` | 上传系统文档 |
| DELETE | `/api/admin/database/delete` | 删除文档 |
| POST | `/api/admin/eval/run` | 启动检索评估 |
| GET | `/api/admin/eval/status/{id}` | 评估进度 |
| GET | `/api/admin/eval/queries` | 获取测试查询 |
| PUT | `/api/admin/eval/queries` | 保存测试查询 |

---

## 鉴权机制

所有受保护接口通过两个装饰器控制：

```python
@auth_required    # 验证 JWT token，通过后注入 request.state.user
@admin_required   # 检查 request.state.user["role"] == "admin"
```

使用示例：

```python
from ..deps import auth_required, admin_required

@router.get("/api/admin/settings")
@auth_required
@admin_required
async def get_settings(request: Request):
    username = request.state.user["username"]  # 当前登录用户名
    ...
```

---

## 依赖关系

```
auth.py ──→ base.config / base.logger / storage
query.py ──→ deps.py (IntegratedSystem)
sessions.py ──→ deps.py
history.py ──→ deps.py
documents.py ──→ deps.py / base.config
deps.py ──→ main.py (IntegratedSystem) / base.config / base.logger
admin/*.py ──→ deps.py / base.config / base.logger
```
