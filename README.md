# RAG Simple — 后端架构

```
backend/
├── agent/                          # Agent 核心 — 工具循环 + 路由
│   ├── rag_system.py               # 主循环入口：generate_answer → 非流式/流式工具循环
│   ├── state.py                    # AgentState 状态机：消息历史、迭代计数、防死循环
│   ├── tools.py                    # 内建工具注册（知识库检索/联网搜索/文档读取/归档/澄清）
│   ├── registry.py                 # 工具注册中心：register() 注册，dispatch() 派发
│   ├── workflow_router.py          # 工作流路由引擎：解析 route.md → 关键词匹配 → 动态配额
│   ├── context_builder.py          # 身份/Skill 工厂：加载 identity.md + 风格模板
│   └── prompts/workflow/           # 工作流定义目录（.md 文件）
│       ├── route.md                #   路由规则：关键词 → 工作流映射
│       ├── USstocks.md             #   美股分析工作流（5 步）
│       └── Autoplan.md             #   复杂规划工作流（6 步）
│
├── api/                            # HTTP 接口层（FastAPI）
│   ├── query.py                    # /api/query 问答接口（SSE 流式 + 非流式）
│   ├── documents.py                # /api/documents 文档上传/列表/图片
│   ├── admin.py                    # /api/admin 管理后台（配置/用户/日志/数据库）
│   └── deps.py                     # 鉴权依赖注入（JWT + superuser 校验）
│
├── rag/                            # RAG 基础设施
│   └── core/
│       ├── openai_client.py        # LLM/Embedding 客户端封装（chat / chat_with_tools / embed）
│       ├── local_vector_store.py   # FAISS 向量库封装（检索/存储/分区管理）
│       ├── reranker.py             # LLM Listwise Rerank（检索结果相关性重排序）
│       └── document_process.py     # 文档解析/分块处理管线
│
├── base/                           # 全局基础设施
│   ├── config.py                   # Config 配置解析（config.ini + .env + 环境变量）
│   └── logger.py                   # 结构化日志（控制台 + 文件 + HTTP 日志）
│
├── storage/                        # 数据持久化
│   ├── json_store.py               # JSON 文件存储（会话历史/归档 CRUD）
│   └── __init__.py
│
├── app.py                          # FastAPI 应用入口
├── config.ini                      # 配置文件
├── test.py                         # 临时测试脚本
└── requirements.txt                # Python 依赖清单
```
