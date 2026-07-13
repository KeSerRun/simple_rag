# RAG Simple

基于 FastAPI + LLM 的 RAG 知识问答系统，支持多工作流、工具调用、PDF 解析、向量检索、管理后台。

## 项目结构

```
rag_simple/
├── agent/                         # Agent 核心 — 工具循环 + 路由
│   ├── rag_system.py              # 主循环：generate_answer → 非流式/流式工具循环
│   ├── integrate.py               # IntegratedSystem：历史管理、上下文治理、流式桥接
│   ├── state.py                   # AgentState：消息历史、迭代计数
│   ├── loop.py                    # SessionLockManager：会话锁
│   ├── workflow.py                # WorkflowRouter：工作流路由引擎
│   ├── context_builder.py         # 身份/Skill 工厂
│   ├── checkpoint.py              # CheckpointStore：中断状态持久化
│   └── tools/
│       ├── registry.py            # 工具注册中心：register / dispatch
│       ├── _infra_handlers.py     # 基础设施工具（set_goal / complete_goal / my 等）
│       ├── _kb_handlers.py        # 知识库检索工具
│       ├── _web_handlers.py       # 联网搜索工具
│       └── _format.py             # 工具结果格式化
│
├── api/                           # HTTP 接口（FastAPI）
│   ├── query.py                   # /api/query 问答接口（SSE 流式 + 非流式）
│   ├── history.py                 # /api/history 对话历史
│   ├── sessions.py                # /api/sessions 会话管理
│   ├── documents.py               # /api/documents 文档上传/列表
│   ├── auth.py                    # /api/auth JWT 认证
│   ├── deps.py                    # 鉴权依赖注入
│   └── admin/                     # 管理后台 API
│       ├── dashboard.py           #   仪表盘统计
│       ├── database.py            #   向量库管理 + 系统数据上传
│       ├── config.py              #   系统设置
│       ├── eval.py                #   检索质量评估（精确率）
│       ├── logs.py                #   日志查看
│       └── users.py               #   用户管理
│
├── rag/                           # RAG 基础设施
│   ├── vector_store.py            # FAISS 向量库（检索/存储/分区/文档管理）
│   ├── pdf_parser.py              # MinerU PDF 解析 + 分块
│   ├── text_splitter.py           # 文本分块
│   └── eval_rag.py                # 评估工具：LLM 评分、精确率计算
│
├── base/                          # 全局基础设施
│   ├── config.py                  # Config 配置解析（config.ini）
│   ├── llm_client.py              # OpenAI 兼容客户端（chat / embedding）
│   └── logger.py                  # 结构化日志
│
├── storage/                       # 数据持久化
│   ├── json_store.py              # JSON 文件存储（会话/归档/任务 CRUD）
│   └── base.py                    # 存储抽象基类
│
├── prompts/                       # 提示词模板
│   ├── identity.md                # 身份设定
│   └── workflow/                  # 工作流定义
│       ├── Briefing.md
│       ├── Comparison.md
│       ├── DeepResearch.md
│       ├── Autoplan.md
│       └── USstocks.md
│
├── web/                           # Vue3 前端（Vite + Naive UI）
├── dist/                          # 前端构建产物
├── data/                          # 运行时数据（向量库、JSON 存储、评估数据）
├── logs/                          # 日志文件
│
├── app.py                         # FastAPI 应用入口
├── sdk.py                         # 对外 SDK（ask / ask_stream）
├── config.ini                     # 配置文件
├── pyproject.toml                 # 项目元数据 + 依赖
└── README.md
```

## 快速开始

### 后端

```bash
pip install -r requirements.txt
# 或使用 uv
uv sync

# 编辑 config.ini 填入 API Key
# 关键配置：
#   [api] chat_api_key / chat_base_url / chat_model
#   [api] embedding_api_key / embedding_base_url / embedding_model
#   [api] mineru_api_key / mineru_base_url（PDF 解析）

python app.py
# 服务默认启动于 http://0.0.0.0:11000
```

### 前端

```bash
cd web
npm install
npm run dev
# 开发服务器默认启动于 http://localhost:5173
# 构建生产版本：npm run build（输出到 dist/）
```

## 管理后台

服务启动后访问 `http://localhost:11000/#/admin`，使用 `config.ini` 中 `[superuser]` 配置的账号登录。

- **仪表盘**：系统概览、实时日志
- **系统设置**：LLM / 检索 / MinerU / Agent 参数在线调整
- **数据管理**：向量库统计、切块详情、系统数据上传（PDF → MinerU 解析 → 向量化）
- **检索评估**：使用测试查询 + LLM 评判器评估检索精确率
- **用户管理**：用户 CRUD

## 主要功能

- **多工作流**：简报、对比、深度研究、自动规划等
- **工具调用**：知识库检索、联网搜索、文档阅读、URL 解析等 16 个工具
- **PDF 解析**：MinerU API（支持 VLM/Lite 模型）
- **上下文治理**：超预算时自动压缩/归档历史对话
- **中断恢复**：达限后保存状态，回复「继续」恢复
- **管理后台**：配置热更新、向量库管理、检索质量评估

## 配置说明

参见 [config.ini](config.ini) 各段注释。
