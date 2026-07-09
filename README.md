# RAG Simple — 智能 RAG Agent 系统 

基于 **检索增强生成（RAG）** 的智能 Agent 问答系统。核心采用 **Tool-calling 循环（ReAct 架构）**，支持知识库检索、联网搜索、工作流路由、多工具并行执行和 **LLM Listwise Rerank** 等功能。

---

## 目录

- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [核心概念](#核心概念)
- [配置说明](#配置说明)
- [API 接口](#api-接口)
- [开发指南](#开发指南)
- [项目结构](#项目结构)
- [各模块文档](#各模块文档)

---

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- 向量数据库：FAISS（本地）

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd rag_simple

# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt

# 前端
cd ../frontend
npm install
```

### 配置

编辑 `backend/config.ini`：

```ini
[api]
chat_api_key = sk-your-api-key
chat_base_url = https://api.deepseek.com
chat_model = deepseek-v4-flash

[agent]
max_tool_iter = 8          # 每轮最多调用工具轮数
max_calls_per_tool = 3     # 单个工具最多调用次数

[retrieval]
enable_llm_rerank = True   # 启用 LLM Listwise Rerank
```

### 启动

```bash
# 终端 1：启动后端 API 服务（开发模式热重载）
cd backend
python app.py              # 访问 http://localhost:11000/index

# 终端 2：启动前端开发服务器（可选，用于前端开发热重载）
cd frontend
npm run dev                # 访问 http://localhost:5173
```

> **注意**：前端构建后产物会输出到 `backend/dist/`，由后端 FastAPI 直接托管。生产环境只需启动后端，前端通过 `http://localhost:11000/index` 访问。

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                    前端 (Vue 3 + Naive UI)                    │
│              /api/query (流式/非流式)                         │
│    文件上传 / 会话管理 / 历史记录 / 管理后台                    │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                  FastAPI 后端 (Python 3.11)                    │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  main.py     │  │  api/        │  │  storage/         │  │
│  │  Integrated   │  │  ┌ admin/   │  │  JSON / SQLite    │  │
│  │  System      │  │  │ 配置/用户 │  │  持久化存储       │  │
│  │  集成入口     │  │  │ 日志/评估 │  │                   │  │
│  └──────┬───────┘  │  │ 数据库    │  └─────────┬─────────┘  │
│         │           │  ├ auth/    │            │            │
│         │           │  ├ query/   │            │            │
│         │           │  ├ sessions/│            │            │
│         │           │  └ ...      │            │            │
│         │           └──────┬──────┘            │            │
│  ┌──────▼──────────────────▼───────────────────▼──────────┐ │
│  │                   agent/ (核心)                         │ │
│  │  ┌───────────────────────────────────────────────────┐ │ │
│  │  │  rag_system.py     ← Tool-calling 循环驱动        │ │ │
│  │  │   ├─ _run_tool_loop()          非流式              │ │ │
│  │  │   └─ _run_tool_loop_stream()   流式                │ │ │
│  │  ├─ registry.py       工具注册中心                    │ │ │
│  │  ├─ state.py          Agent 状态机                   │ │ │
│  │  ├─ context_builder.py 身份/Skill 提示词工厂          │ │ │
│  │  ├─ workflow_router.py 工作流路由引擎                 │ │ │
│  │  ├─ tools/            工具处理函数                    │ │ │
│  │  │   ├─ _handlers.py   知识库搜索/联网搜索/全文读取    │ │ │
│  │  │   ├─ _format.py     结果格式化                    │ │ │
│  │  │   └─ _search_backends.py 多搜索后端封装           │ │ │
│  │  └─ prompts/          工作流定义 (.md)               │ │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               rag/ (基础设施)                             │ │
│  │  ├─ vector_store.py    FAISS 向量库 + 文档入库           │ │
│  │  ├─ llm_client.py      LLM/Embedding 客户端 + Reranker  │ │
│  │  ├─ pdf_parser.py      MinerU PDF 解析                  │ │
│  │  ├─ text_splitter.py   中文文本切分（备用）              │ │
│  │  └─ eval_rag.py        检索质量评估                     │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心概念

### 1. Tool-calling 循环（Agent 循环）

系统核心是 **while 循环 + LLM 自主决策** 的 ReAct 架构：

```
用户输入 → System Prompt + 历史 → LLM
  │
  ├─ LLM 返回 tool_calls → 并发执行工具 → 结果回灌 messages → 重复
  │
  └─ LLM 返回自然语言 → 结束循环 → 输出答案
```

- **非流式**（`_run_tool_loop`）：整体循环完成后一次性返回
- **流式**（`_run_tool_loop_stream`）：逐 token 输出 + 实时工具调用状态

### 2. 状态机（AgentState）

每个对话请求生成一个 `AgentState`，封装了：

| 属性 | 说明 |
|------|------|
| `messages` | OpenAI 格式的完整对话消息 |
| `iteration` | 已执行的工具轮次数 |
| `max_iterations` | 最大轮次上限（工作流可动态覆盖） |
| `max_calls_per_tool` | 单工具最大调用次数（工作流可动态覆盖） |
| `_called_tools_history` | 已调用的工具签名缓存（防重复） |
| `_tool_call_counts` | 各工具累计调用计数（防换词死循环） |

### 3. 双重防死循环机制

LLM 在 Tool-calling 中容易陷入"搜不到就换词再搜"的死循环。系统通过两层拦截：

1. **签名去重**（`_called_tools_history`）：完全相同的工具名+参数组合只能调用一次
2. **计数上限**（`_tool_call_counts`）：同一个工具在单轮中调用超过 `max_calls_per_tool` 次即拦截

### 4. 工作流路由（Workflow Router）

通过 `prompts/workflow/route.md` 定义路由规则。命中后向 System Prompt 注入强制工作流指令：

```
route.md 关键词匹配 → 读取 workflow/xxx.md Frontmatter
  ├─ 注入步骤指令到 System Prompt
  └─ 动态覆盖 AgentState 的 max_iterations / max_calls_per_tool
```

工作流通过 Python 正则引擎匹配后强制注入，LLM 无法拒绝执行，保证了 SOP 的 100% 落地。

### 5. LLM Listwise Rerank

检索增强阶段的可选优化环节：

```
FAISS 检索 Top-30 → LLM Listwise Rerank → 保留 Top-5
```

LLM 根据 query 与每个 chunk 的相关性进行全局排序，过滤低相关的噪音片段，提升注入上下文的信息密度。

### 6. 工具注册表（Registry）

采用注册表模式，工具通过 `registry.register()` 声明式注册：

```python
registry.register(
    name="my_tool",
    description="工具描述",
    parameters={...},
    handler=_exec_my_tool,
)
```

外部通过 `registry.dispatch(name, args_json, ctx=ToolContext(...))` 派发，解耦了工具定义和调用。

---

## 配置说明

`backend/config.ini` 全部配置项：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| **LLM / API** | | |
| `chat_model` | deepseek-v4-flash | 对话模型名 |
| `chat_base_url` | https://api.openai.com/v1 | API 端点 |
| `chat_reasoning_effort` | - | 推理力度（low/medium/high） |
| `embedding_model` | text-embedding-3-small | 嵌入模型名 |
| `embedding_dim` | 1024 | 嵌入向量维度 |
| `timeout` | 60 | API 超时（秒） |
| `max_retries` | 3 | API 重试次数 |
| **MinerU（PDF 解析）** | | |
| `mineru_base_url` | https://mineru.net | MinerU API 地址 |
| `mineru_api_key` | - | MinerU API 密钥 |
| `mineru_model_version` | vlm | 解析模型版本 |
| **Agent** | | |
| `max_tool_iter` | 8 | 单次对话最大工具调用轮次 |
| `max_calls_per_tool` | 3 | 单个工具最大调用次数 |
| `max_output_tokens` | 8192 | 生成答案的最大 Token 数 |
| **检索** | | |
| `retrieval_top_k` | 30 | 向量检索返回 Top-K 文档块 |
| `candidate_top_k` | 5 | 重排/截断后保留数 |
| `enable_llm_rerank` | false | LLM Listwise Rerank 开关 |
| `min_chunk_length` | 30 | 文本块最小长度 |
| **搜索** | | |
| `search_backend` | duckduckgo | 搜索后端（duckduckgo/searxng/bocha/bing） |
| `search_timeout` | 15 | 搜索超时（秒） |
| **对话历史** | | |
| `max_history_length` | 200 | 最大保留轮次 |
| `max_history_chars` | 100000 | 最大字符数 |
| **日志** | | |
| `app_log_level` | INFO | 应用日志级别 |
| `console_log_level` | DEBUG | 控制台日志级别 |

---

## API 接口

### 用户接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/query` | 非流式问答 |
| POST | `/api/query/stream` | 流式问答（SSE） |
| POST | `/api/documents/upload` | 上传个人文档 |
| GET | `/api/documents/list` | 文档列表 |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/history/{session_id}` | 会话历史 |
| GET | `/api/health` | 健康检查 |

### 管理后台（需 admin 角色）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/dashboard` | 仪表盘统计 |
| GET | `/api/admin/config` | 读取系统配置 |
| PUT | `/api/admin/config` | 更新系统配置 |
| GET | `/api/admin/users` | 用户列表 |
| POST | `/api/admin/users` | 创建用户 |
| DELETE | `/api/admin/users/{name}` | 删除用户 |
| PUT | `/api/admin/users/{name}/role` | 修改角色 |
| PUT | `/api/admin/users/{name}/password` | 重置密码 |
| GET | `/api/admin/logs` | 日志文件 |
| GET | `/api/admin/database` | 向量库统计 |
| GET | `/api/admin/database/chunks` | 块详情 |
| GET | `/api/admin/database/partitions` | 分区列表 |
| GET | `/api/admin/database/check_integrity` | 完整性检查 |
| POST | `/api/admin/database/upload` | 上传系统文档 |
| DELETE | `/api/admin/database/delete` | 删除文档 |
| POST | `/api/admin/eval/run` | 启动检索评估 |
| GET | `/api/admin/eval/status/{id}` | 评估进度 |
| GET | `/api/admin/eval/queries` | 获取测试查询 |
| PUT | `/api/admin/eval/queries` | 保存测试查询 |

---

## 开发指南

### 如何添加新工具

1. 在 `backend/agent/tools/_handlers.py` 中编写 handler 函数：

```python
def _exec_my_tool(args: dict, ctx: ToolContext) -> str:
    param = args.get("param_name")
    # ... 执行逻辑 ...
    return "结果字符串"
```

2. 在 `backend/agent/tools/__init__.py` 中注册：

```python
registry.register(
    name="my_tool",
    description="工具描述，LLM 根据此描述决定何时调用",
    parameters={
        "type": "object",
        "properties": {
            "param_name": {
                "type": "string",
                "description": "参数说明",
            },
        },
        "required": ["param_name"],
    },
    handler=_exec_my_tool,
)
```

3. 重启后端，LLM 会在下一轮对话中自动学会使用此工具。

### 如何添加新工作流

1. 创建 `backend/prompts/workflow/xxx.md`：

```markdown
---
name: xxx
description: 工作流说明
max_tool_iter: 12
max_calls_per_tool: 6
---

### 步骤一：任务分析
...
```

2. 在 `backend/prompts/workflow/route.md` 添加路由规则：

```
- xxx: 关键词1, 关键词2, ...
```

3. 重启后端生效。

### 前端开发

```bash
cd frontend
npm run dev       # 热重载开发
npm run build     # 生产构建（输出到 backend/dist/）
```

前端使用 Vue 3 + Vite + Naive UI + Pinia。

---

## 项目结构

```
rag_simple/
├── backend/                          # Python 后端
│   ├── agent/                        # Agent 核心
│   │   ├── rag_system.py            # 主循环入口（Tool-calling）
│   │   ├── registry.py              # 工具注册中心
│   │   ├── state.py                 # 状态机
│   │   ├── context_builder.py       # 身份/Skill 提示词工厂
│   │   ├── workflow_router.py       # 工作流路由引擎
│   │   ├── tools/                   # 工具实现
│   │   │   ├── _handlers.py         # 知识库/搜索/全文读取
│   │   │   ├── _format.py           # 结果格式化
│   │   │   └── _search_backends.py  # 多搜索后端
│   │   └── prompts/workflow/        # 工作流定义 .md
│   │       ├── route.md             # 路由规则
│   │       └── *.md                 # 各工作流定义
│   ├── api/                         # HTTP 路由
│   │   ├── __init__.py              # 路由汇总
│   │   ├── admin/                   # 管理后台 API
│   │   │   ├── __init__.py          # 路由器入口
│   │   │   ├── config.py            # 系统设置
│   │   │   ├── dashboard.py         # 仪表盘
│   │   │   ├── database.py          # 数据库管理
│   │   │   ├── logs.py              # 日志查看
│   │   │   ├── users.py             # 用户管理
│   │   │   └── eval.py              # 检索评估
│   │   ├── auth.py                  # 登录/注册
│   │   ├── query.py                 # 问答接口
│   │   ├── sessions.py              # 会话管理
│   │   ├── history.py               # 历史记录
│   │   ├── documents.py             # 文档管理
│   │   └── deps.py                  # 鉴权依赖 + 系统单例
│   ├── rag/                         # RAG 基础设施
│   │   ├── vector_store.py          # FAISS 向量库 + 文档入库
│   │   ├── llm_client.py            # LLM/Embedding 客户端 + Reranker
│   │   ├── pdf_parser.py            # MinerU PDF 解析
│   │   ├── text_splitter.py         # 中文文本切分（备用）
│   │   ├── eval_rag.py              # 检索质量评估
│   │   └── eval_queries.json        # 评估测试查询
│   ├── base/                        # 基础组件
│   │   ├── config.py                # 配置解析（config.ini + 环境变量）
│   │   └── logger.py                # 结构化日志（控制台 + 文件 + HTTP）
│   ├── storage/                     # 数据持久化
│   │   ├── json_store.py            # JSON 文件存储（默认）
│   │   └── sqlite_store.py          # SQLite 存储（备用）
│   ├── data/                        # 运行时数据
│   │   ├── data.json                # 用户/会话/消息数据
│   │   └── vector_store/            # 向量库文件
│   ├── dist/                        # 前端构建产物
│   ├── app.py                       # FastAPI 应用入口
│   ├── main.py                      # IntegratedSystem 集成入口
│   ├── config.ini                   # 配置文件
│   └── pyproject.toml               # Python 项目配置
│
├── frontend/                        # Vue 3 前端
│   ├── src/
│   │   ├── views/                   # 所有页面
│   │   │   ├── admin/               # 管理后台
│   │   │   │   ├── AdminLayout.vue  # 后台布局 + 侧边栏
│   │   │   │   ├── AdminDashboard.vue
│   │   │   │   ├── AdminSettings.vue
│   │   │   │   ├── AdminUsers.vue
│   │   │   │   ├── AdminLog.vue
│   │   │   │   ├── AdminDatabase.vue
│   │   │   │   └── AdminEval.vue    # 检索评估页
│   │   │   ├── Chat.vue             # 主聊天页
│   │   │   ├── Home.vue             # 首页
│   │   │   ├── Login.vue            # 登录页
│   │   │   └── Register.vue         # 注册页
│   │   ├── stores/                  # Pinia 状态管理
│   │   │   ├── user.js              # 用户认证
│   │   │   ├── admin.js             # 管理后台 API
│   │   │   └── theme.js             # 主题
│   │   ├── http/                    # Axios 封装 + 拦截器
│   │   ├── router/                  # Vue Router 配置
│   │   ├── config/                  # 品牌配置
│   │   └── assets/                  # 静态资源
│   ├── package.json
│   └── vite.config.js
│
├── README.md                        # 本文件
└── backend/README.md                # 后端独立说明
```

---

## 各模块文档

每个后端模块均有独立的 README，包含文件说明、调用示例和依赖关系：

| 模块 | 路径 | 内容 |
|------|------|------|
| RAG 基础 | [backend/rag/README.md](backend/rag/README.md) | 向量库、LLM 客户端、PDF 解析、评估 |
| Agent | [backend/agent/README.md](backend/agent/README.md) | 工具注册、工作流路由、主循环 |
| API | [backend/api/README.md](backend/api/README.md) | HTTP 接口、鉴权、端点一览 |
| 配置 | [backend/base/README.md](backend/base/README.md) | config.ini、日志使用 |
| 存储 | [backend/storage/README.md](backend/storage/README.md) | 用户/会话/消息 CRUD |
