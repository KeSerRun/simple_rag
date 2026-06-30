# RAG Simple — 轻量 RAG 问答系统

基于 **检索增强生成（RAG）** 的智能问答系统，零本地推理依赖：所有 LLM / Embedding 调用走 OpenAI 兼容 API，向量检索走本地 FAISS，用户/会话/历史走 JSON 文件存储。前端 Vue 3，后端 FastAPI，全栈一个进程即可起。

PDF 解析默认走 [MinerU](https://mineru.net) 做结构化版面解析（表格 / 章节 / 图表保留），未配 token 时自动回退到本地 OCR。

## 核心特性

### 全 API 化的推理链
- **LLM / Embedding 全部走 OpenAI 兼容端点**：chat 端默认 DeepSeek，embedding 端默认 SiliconFlow 的 BGE-M3，二者可独立指向不同服务商
- **零本地模型 / 零 GPU 依赖**：不需要下载 Qwen / BGE / BERT 权重，pip 装完即可跑
- **可选 LLM listwise rerank**：通过 `[api] enable_llm_rerank` 开关，关闭可显著降低延迟与成本

### 智能检索策略
| 策略 | 说明 |
|------|------|
| **直接检索** | 用原始查询直接做向量搜索 |
| **子查询检索** | LLM 把复杂查询拆解为多个子查询，分别检索后合并去重 |

策略由 LLM 自动选择；意图分类器先判定是否需要检索，闲聊路径直连 LLM。

### 文档支持
- **PDF — MinerU 优先**：调用 MinerU 官方 API 做版面解析，输出结构化 chunk（保留表格 Markdown、章节 `section_path`、`chunk_type`、`page`、`caption`）；token 未配 / API 失败时自动回退到 OCR
- **PDF — OCR 兜底**：PyMuPDF + RapidOCR，对扫描页或无 token 场景的兜底
- **纯文本（TXT/Markdown）** — 直接解析

### 向量检索
- **FAISS IndexFlatIP** 本地索引，余弦相似度
- **父-子分块**（普通文档）：父块 200 字符 / 子块 50 字符，子粒度召回 + 父粒度还原
- **预切块识别**（MinerU 文档）：MinerU 已按章节/表格结构切好，直接入库不再二次切分
- **按 partition 隔离**：每个用户拥有独立检索域，互不可见
- **可选 LLM listwise rerank**：召回后由 LLM 重排

### Prompts / Skills 可热改
- `prompts/identity.md` 定义助手身份（每次 LLM 调用注入 system）
- `prompts/skills/<name>/SKILL.md` 定义可复用 skill（answer-with-context / query-classifier / strategy-selector / subquery / rerank）
- 改 prompt 无需改代码，重启即生效

### 用户系统
- JWT 认证（区分 `admin` / `user`，但当前 API 不强制角色门禁）
- 多会话管理，对话历史持久化（JSON 文件，原子写）
- 超级管理员账户通过 `config.ini` `[superuser]` 配置，服务启动时自动创建

## 系统架构

```
┌────────────────────────────────────────────────────────────┐
│                    Frontend (Vue 3 + Vite)                 │
│      聊天界面 / 文档管理 / 会话管理 / Markdown 渲染          │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTP + SSE
                            ▼
┌────────────────────────────────────────────────────────────┐
│                FastAPI (uvicorn, port 11000)               │
│              JWT 认证 / REST API / SSE 流式                 │
└───────────────────────────┬────────────────────────────────┘
                            ▼
                    IntegratedSystem (main.py)
                            │
        ┌───────────────────┼───────────────────────┐
        ▼                   ▼                       ▼
  JSONFileStore       RAGSystem                文件上传暂存
  users.json          (rag_qa)                 data/vector_store/tmp/
  sessions.json           │                          │
  history/                ▼                          ▼
                  ┌───────────────┐         ┌───────────────────┐
                  │ 意图分类器     │         │ Document Loaders  │
                  │ (LLM)         │         │  ├ MinerU (PDF)   │
                  └───────┬───────┘         │  ├ OCR (PDF 兜底) │
                          ▼                 │  ├ DOC / PPT      │
                  ┌───────────────┐         │  ├ IMG (OCR)      │
                  │ 策略选择器     │         │  └ TXT / MD       │
                  │ (LLM)         │         └─────────┬─────────┘
                  └───────┬───────┘                   │
                          ▼                           ▼
                  ┌───────────────────────────────────────┐
                  │  VectorStore (FAISS IndexFlatIP)      │
                  │  - 父子分块                            │
                  │  - 按 partition 隔离                   │
                  │  - 可选 LLM listwise rerank            │
                  └───────────────────┬───────────────────┘
                                      ▼
                  ┌───────────────────────────────────────┐
                  │  OpenAIClient (chat / embedding 双端) │
                  │  chat:      DeepSeek                  │
                  │  embedding: SiliconFlow (BGE-M3)      │
                  └───────────────────────────────────────┘
```

### 查询数据流

1. 前端 POST `/api/query`（带 JWT、`session_id`、`question`、可选 `stream`）
2. `IntegratedSystem.get_answer` / `answer_generator` 拉历史 + 上传文件标记
3. LLM 意图分类器判断是否需检索；不需要 → 闲聊路径直连 LLM
4. 需要检索 → LLM 策略选择器选 `直接检索` / `子查询检索`
5. `VectorStore.search`：BGE-M3 embedding → FAISS 召回 → partition 过滤 → 父级去重 → 可选 LLM rerank
6. 命中的 parent chunks 拼成 context → 调 `answer-with-context` skill 构 messages → LLM 出最终答案
7. 流式 SSE 或一次性 JSON 返回

## 项目结构

```
rag_simple/
├── README.md
├── LICENSE
├── .gitignore
├── backend/                                # Python 后端
│   ├── pyproject.toml                      # 依赖与项目元数据（uv / pip 均可）
│   ├── uv.lock
│   ├── config.ini                          # 全局配置
│   ├── app.py                              # FastAPI 入口
│   ├── main.py                             # IntegratedSystem + CLI
│   ├── base/
│   │   ├── config.py                       # 配置解析器（单例 conf）
│   │   └── logger.py                       # 日志
│   ├── storage/
│   │   └── json_store.py                   # 用户/会话/历史 JSON 持久化
│   ├── api/                                # FastAPI 路由（带 JWT 装饰器）
│   │   ├── auth.py                         #   /api/register, /api/login
│   │   ├── sessions.py                     #   /api/create_session, /api/sessions/...
│   │   ├── history.py                      #   /api/history, /api/clear_history
│   │   ├── query.py                        #   /api/query (SSE)
│   │   ├── documents.py                    #   /api/upload, /api/add_documents, ...
│   │   └── deps.py                         #   IntegratedSystem 单例 + auth_required
│   ├── rag_qa/
│   │   ├── core/
│   │   │   ├── rag_system.py               # RAGSystem 编排器
│   │   │   ├── local_vector_store.py       # FAISS + JSON 元数据
│   │   │   ├── openai_client.py            # OpenAI 兼容客户端（chat + embed）
│   │   │   ├── llm.py                      # 带 identity 的 LLM 包装
│   │   │   ├── context_builder.py          # prompts/skills 加载器
│   │   │   ├── query_classifier.py         # 意图分类（LLM）
│   │   │   ├── strategy_selector.py        # 策略选择（LLM）
│   │   │   ├── document_process.py         # 文档加载 + 父子分块入口
│   │   │   └── document.py                 # 轻量 Document 容器
│   │   ├── document_loaders/
│   │   │   ├── mineru_pdf_loader.py        # PDF 默认: MinerU + 富元数据
│   │   │   └── pdf_loader.py               # PDF 兜底: OCRPDFLoader
│   │   ├── pdf_spliter/                    # MinerU 子模块
│   │   │   ├── mineru_client.py            #   API 客户端（4 步流程）
│   │   │   ├── chunker.py                  #   content_list.json → chunks
│   │   │   └── README.md
│   │   ├── text_spliter/                   # 中文递归分割器
│   │   ├── assesment/                      # 评估占位
│   │   └── main.py                         # CLI 入口（query / add_document）
│   ├── prompts/                            # 可热改 prompts
│   │   ├── identity.md                     #   助手身份
│   │   └── skills/
│   │       ├── answer-with-context/SKILL.md
│   │       ├── query-classifier/SKILL.md
│   │       ├── strategy-selector/SKILL.md
│   │       ├── subquery/SKILL.md
│   │       └── rerank/SKILL.md
│   ├── data/                               # 运行时数据（gitignored）
│   │   ├── users.json
│   │   ├── sessions.json
│   │   ├── history/{session_id}.json
│   │   └── vector_store/
│   │       ├── dense_vectors.npy           #   FAISS 矩阵
│   │       ├── metadata.json               #   行对应元数据
│   │       └── tmp/{username}/             #   上传暂存
│   ├── dist/                               # 前端构建产物（由 FastAPI 挂载）
│   └── logs/
└── frontend/                               # Vue 3 + Vite
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.js / App.vue
        ├── router/                         # 路由
        ├── stores/                         # Pinia（持久化）
        ├── http/                           # Axios JWT 拦截器
        ├── views/                          # Home / Login / Register
        └── components/                     # 聊天界面组件
```

## 快速开始

### 环境要求

| 组件 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | 18+ |
| OpenAI 兼容 LLM 服务 | DeepSeek / OpenAI / Moonshot 等任一 |
| Embedding 服务 | SiliconFlow / OpenAI 等任一 |
| MinerU token（可选） | https://mineru.net/apiManage |

无需 Docker、MySQL、Redis、Milvus，无需本地 GPU。

### 1. 安装依赖

```bash
# 后端 (推荐 uv，pip 亦可)
cd backend
uv sync                # 或: pip install -e .

# 前端
cd ../frontend
npm install
```

### 2. 配置 [backend/config.ini](backend/config.ini)

至少需要填好 chat / embedding 两端的 API key：

```ini
[api]
# Chat 端 (默认 DeepSeek)
api_key = sk-xxx                            # 优先读环境变量 OPENAI_API_KEY
base_url = https://api.deepseek.com
chat_model = deepseek-chat

# Embedding 端 (默认 SiliconFlow BGE-M3, 留空则回退到 chat 端)
embedding_api_key = sk-xxx                  # 优先读 OPENAI_EMBEDDING_API_KEY
embedding_base_url = https://api.siliconflow.cn/v1
embedding_model = BAAI/bge-m3
embedding_dim = 1024

# 可选: 启用 LLM listwise rerank (会增加 LLM 调用)
enable_llm_rerank = false
```

可选 — MinerU 高质量 PDF 解析：

```ini
[mineru]
token_key = eyJ0eXBl...                     # 留空则 PDF 自动回退到 OCR
token_name = my-token
model_version = vlm                         # vlm 精度高 / pipeline 速度快
language = ch
```

超级管理员账户（启动时自动创建）：

```ini
[superuser]
users = Admin123,Super123
passwords = Admin123,Super123
```

### 3. 构建前端

```bash
cd frontend
npm run build                               # 产物会输出到 backend/dist/
```

前端没构建也能跑 — API 全部可用，只是 `/index` 页面 404。

### 4. 启动后端

```bash
cd backend
python app.py
```

启动后访问 http://localhost:11000/index。

### 5.（可选）CLI 模式

不想跑 Web 服务也能用 `backend/main.py`：

```bash
cd backend
python main.py upload  ./some_document.pdf   --partition alice
python main.py query   "PDF 里说了什么"        --partition alice --stream
python main.py chat    --partition alice
python main.py info    --partition alice
```

## API 端点

所有 `/api/*` 端点（除注册 / 登录）都需要 `Authorization: Bearer <jwt>`。

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 登录，返回 JWT |

### 会话与历史

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/create_session` | 创建新会话 |
| GET | `/api/sessions/{username}` | 列出当前用户的会话（以 token 为准） |
| DELETE | `/api/sessions/{session_id}` | 删除会话 + 关联历史 |
| GET | `/api/history/{session_id}` | 获取会话历史 |
| POST | `/api/clear_history` | 清除指定 session 历史 |

### 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/query` | 提交查询（`{session_id, question, stream?}`），`stream=true` 走 SSE |

### 文档管理（按当前用户分区隔离）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传文件到当前用户暂存目录（不入库） |
| POST | `/api/upload_embeddings` | 上传 + 直接向量化入库（同名先删旧向量） |
| POST | `/api/add_documents` | 把已上传的目录向量化入库 |
| GET | `/api/documents/{username}` | 列出当前用户已入库的文档来源 |
| POST | `/api/clear_documents` | 清空当前用户分区所有文档 |
| POST | `/api/clear_chosed_documents` | 删除指定来源的文档 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/index` | 前端主页（需 `npm run build` 后产物在 `backend/dist/`） |

## 配置说明

完整配置见 [backend/config.ini](backend/config.ini)。

### `[storage]`
| 参数 | 默认 | 说明 |
|------|------|------|
| `data_dir` | `data` | 用户 / 会话 / 历史 JSON 根目录 |
| `vector_store_dir` | `data/vector_store` | FAISS 索引 + 元数据目录 |

### `[retrieval]`
| 参数 | 默认 | 说明 |
|------|------|------|
| `parent_chunk_size` | 200 | 父块大小（字符），仅用于非 MinerU 文档 |
| `child_chunk_size` | 50 | 子块大小 |
| `chunk_overlap` | 20 | 块重叠 |
| `retrieval_top_k` | 10 | FAISS 召回数 |
| `candidate_top_k` | 5 | 重排后保留数 |

### `[api]`
| 参数 | 默认 | 说明 |
|------|------|------|
| `api_key` / `base_url` / `chat_model` | DeepSeek | Chat 端（答案生成 / 子查询 / 分类 / 策略） |
| `embedding_api_key` / `embedding_base_url` / `embedding_model` | SiliconFlow BGE-M3 | Embedding 端，可独立于 chat 端 |
| `embedding_dim` | 1024 | 须与 embedding 模型对应（BGE-M3=1024, text-embedding-3-small=1536） |
| `enable_llm_rerank` | false | LLM listwise rerank 开关 |
| `timeout` / `max_retries` | 60 / 3 | API 请求超时与重试 |

### `[mineru]`
| 参数 | 默认 | 说明 |
|------|------|------|
| `token_key` | _空_ | MinerU API token，留空则 PDF 自动走 OCR |
| `model_version` | `vlm` | `vlm` 精度高 / `pipeline` 速度快 |
| `language` | `ch` | `ch` / `en` / `auto` |

环境变量 `MINERU_TOKEN_KEY` 优先于 `config.ini`。

### `[conversation_history]`
| 参数 | 默认 | 说明 |
|------|------|------|
| `max_history_length` | 10 | 注入到 LLM 的最大历史轮数 |

### `[superuser]`
启动时自动按列表创建管理员账户（已存在则跳过）：

```ini
users = Admin123,Super123
passwords = Admin123,Super123
```

## 自定义 Prompt

所有 LLM 行为都由 `backend/prompts/` 下的 Markdown 文件驱动：

- [`identity.md`](backend/prompts/identity.md) — 助手人格 / 边界 / Markdown 排版准则，作为 system 消息注入每次 chat
- `skills/<name>/SKILL.md` — 单个 skill 的 prompt 模板，通过 `ContextBuilder.build_messages("<name>", **vars)` 加载

修改 prompt 后重启即生效，无需改代码。新增 skill 同理：建子目录加 `SKILL.md` 即可被 `RAGSystem` 调用。

## 技术栈

### 后端
| 技术 | 用途 |
|------|------|
| FastAPI + Uvicorn | Web 框架 / ASGI |
| openai (SDK) | OpenAI 兼容的 chat / embedding 客户端 |
| faiss-cpu + numpy | 本地稠密向量索引 |
| PyMuPDF | PDF 文本提取（OCR 兜底路径） |
| RapidOCR (ONNX Runtime) | PDF 内嵌图像 OCR |
| requests + beautifulsoup4 | MinerU API 调用 + HTML 表格转 Markdown |
| PyJWT | JWT 认证 |
| Pillow / opencv-python | 图像处理 |

### 前端
| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | UI |
| Pinia | 持久化状态 |
| Vue Router | 路由 |
| Axios | HTTP（JWT 拦截器） |
| marked | Markdown 渲染 |
| Vite | 构建 |

## 已知限制

- **MinerU 调用同步阻塞**：单份 PDF 通常 15–60 秒返回，期间 HTTP 请求会一直挂着；不适合通过浏览器一次性上传几十份 PDF
- **不做本地缓存**：同一 PDF 重复上传会重新调 MinerU API
- **MinerU 表格合并单元格**：HTML→Markdown 不展开 `rowspan/colspan`，复杂表头可能错位
- **`role` 字段已存在但未强制**：JWT 里有 `role`，但当前 `/api/upload*` / `/api/add_documents` 等接口未做 admin 门禁，所有已登录用户均可调用（仅作用于自己分区）

## License

[MIT](LICENSE)
