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
# 终端 1：启动后端 API 服务
cd backend
python app.py        # 访问 http://localhost:8000

# 终端 2：启动前端开发服务器
cd frontend
npm run dev           # 访问 http://localhost:5173
```

### 生产构建

```bash
cd frontend
npm run build         # 构建产物输出到 backend/dist/
# 然后重启后端，前端文件通过 FastAPI 静态文件服务提供
```

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                    前端 (Vue 3 + Naive UI)                      │
│              /api/query (流式/非流式)                           │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                  FastAPI 后端 (Python 3.11)                    │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  main.py     │  │  api/        │  │  storage/         │  │
│  │  集成系统     │  │  路由+鉴权    │  │  JSON 持久化存储   │  │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬─────────┘  │
│         │                 │                     │            │
│  ┌──────▼─────────────────▼─────────────────────▼──────────┐ │
│  │                   agent/ (核心)                           │ │
│  │  ┌──────────────────┐                                   │ │
│  │  │  rag_system.py   │ ← Tool-calling 循环驱动            │ │
│  │  │   ├─ _run_tool_loop()          非流式                  │ │
│  │  │   └─ _run_tool_loop_stream()   流式                    │ │
│  │  ├─ state.py         │ Agent 状态机                      │ │
│  │  ├─ tools.py         │ 内建工具注册                        │ │
│  │  ├─ registry.py      │ 工具注册中心                        │ │
│  │  ├─ workflow_router.py │ 工作流路由引擎                     │ │
│  │  ├─ context_builder.py │ 身份/Skill 提示词工厂              │ │
│  │  └─ prompts/workflow/ │ 工作流定义 (.md)                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               rag/ (基础设施)                              │ │
│  │  ├─ core/openai_client.py     LLM/Embedding 客户端        │ │
│  │  ├─ core/local_vector_store.py  向量库封装                 │ │
│  │  ├─ core/reranker.py          LLM Listwise Rerank        │ │
│  │  └─ core/document_process.py   文档处理管线                │ │
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
- **反思模式**：已移除，因为流式模式下不适用

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
FAISS 检索 Top-30 → LLM Listwise Rerank → 保留 Top-15
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
| `chat_model` | gpt-4o-mini | 对话模型名 |
| `chat_base_url` | https://api.openai.com/v1 | API 端点 |
| `chat_reasoning_effort` | - | 推理力度（low/medium/high） |
| `embedding_model` | text-embedding-3-small | 嵌入模型名 |
| **Agent** | | |
| `max_tool_iter` | 6 | 单次对话最大工具调用轮次 |
| `max_calls_per_tool` | 3 | 单个工具最大调用次数 |
| `max_output_tokens` | 8192 | 生成答案的最大 Token 数 |
| **检索** | | |
| `retrieval_top_k` | 30 | 向量检索返回 Top-K 文档块 |
| `candidate_top_k` | 5 | 多 query 时每个 query 的候选数 |
| `enable_llm_rerank` | false | LLM Listwise Rerank 开关 |
| **搜索** | | |
| `search_backend` | duckduckgo | 搜索后端（duckduckgo/searxng/bocha/bing） |
| `search_timeout` | 15 | 搜索超时（秒） |

---

## API 接口

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/query` | POST | 非流式问答 |
| `/api/query/stream` | GET | 流式问答（SSE） |
| `/api/admin/config` | GET/PUT | 系统配置读取/保存 |
| `/api/admin/dashboard` | GET | 仪表盘统计 |
| `/api/admin/users` | GET/POST/DELETE | 用户管理 CRUD |
| `/api/admin/logs` | GET | 日志查看与下载 |
| `/api/admin/database` | GET | 向量库统计 |
| `/api/documents/upload` | POST | 文档上传 |
| `/api/documents/list` | GET | 文档列表 |

---

## 开发指南

### 如何添加新工具

1. 在 `backend/agent/tools.py` 中编写 handler 函数并注册：

```python
def _exec_my_tool(args: dict, ctx: ToolContext) -> str:
    param = args.get("param_name")
    # ... 执行逻辑 ...
    return "结果字符串"

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

2. 重启后端，LLM 会在下一轮对话中自动学会使用此工具。

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
npm run build     # 生产构建
```

前端使用 Vue 3 + Vite + Naive UI + Pinia。

### 代码风格

- Python：遵循 PEP 8，使用中文注释
- 前端：ESLint + Prettier

### 添加新依赖

```bash
cd backend
pip install <package>
pip freeze > requirements.txt

cd frontend
npm install <package>
```

---

## 项目结构

```
rag_simple/
├── backend/                      # Python 后端
│   ├── agent/                    # Agent 核心
│   │   ├── rag_system.py         # 主循环入口（带逐行注释）
│   │   ├── state.py              # 状态机（带逐行注释）
│   │   ├── tools.py              # 工具注册（带逐行注释）
│   │   ├── registry.py           # 工具注册中心
│   │   ├── workflow_router.py    # 工作流路由（带逐行注释）
│   │   ├── context_builder.py    # 身份/Skill 工厂（带逐行注释）
│   │   └── prompts/workflow/     # 工作流定义 .md
│   │       ├── route.md          # 路由规则
│   │       ├── USstocks.md       # 美股分析工作流
│   │       └── Autoplan.md       # 规划工作流
│   ├── api/                      # HTTP 路由
│   │   ├── query.py              # 问答接口
│   │   ├── documents.py          # 文档接口
│   │   ├── admin.py              # 管理后台接口
│   │   └── deps.py               # 鉴权依赖
│   ├── rag/core/                 # RAG 基础设施
│   │   ├── openai_client.py      # LLM 客户端（带逐行注释）
│   │   ├── local_vector_store.py # 向量库
│   │   ├── reranker.py           # LLM Listwise Rerank
│   │   └── document_process.py   # 文档处理
│   ├── base/                     # 配置与日志
│   ├── storage/                  # 数据持久化
│   ├── app.py                    # 后端入口
│   └── config.ini                # 配置文件
│
├── frontend/                     # Vue 3 前端
│   ├── src/
│   │   ├── components/           # 通用组件
│   │   ├── views/                # 页面
│   │   │   ├── admin/            # 管理后台
│   │   │   ├── Chat.vue          # 主聊天页
│   │   │   ├── Login.vue         # 登录页
│   │   │   └── Register.vue      # 注册页
│   │   ├── stores/               # Pinia 状态管理
│   │   ├── http/                 # axios 封装
│   │   └── assets/               # 静态资源
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── README.md                     # 本文件（项目根目录）
├── backend/README.md             # 后端独立说明
└── frontend/README.md            # 前端独立说明
```
