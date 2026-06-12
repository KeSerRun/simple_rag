# RAG Simple — 智能问答系统

基于 **检索增强生成（RAG）** 的智能问答系统，采用双层检索架构（BM25 关键词检索 + 混合向量检索），集成多种智能检索策略，支持多格式文档 OCR 解析与上传，提供完整的 Web 聊天界面。

## ✨ 核心特性

### 🔍 双层检索架构
- **第一层 — BM25 关键词检索**：对历史高质量问答对进行快速关键词匹配，置信度达标时直接返回答案，跳过 LLM 推理，响应速度极快
- **第二层 — RAG 深度检索**：当 BM25 未命中时，自动进入完整的 RAG 流水线，通过向量搜索 + 重排序 + LLM 生成高质量答案

### 🧠 智能检索策略
系统内置四种检索策略，由轻量级 LLM（Qwen2.5-0.5B）自动选择最优方案：

| 策略 | 说明 |
|------|------|
| **直接检索** | 使用原始查询直接进行向量搜索 |
| **HyDE**（假设文档检索） | 先生成假设答案，再用假设答案进行检索，缩小语义鸿沟 |
| **子查询检索** | 将复杂查询拆解为多个子查询分别检索后合并去重 |
| **回溯检索** | 生成回溯问题以更好地匹配文档内容 |

### 📄 多格式文档支持
- **PDF** — PyMuPDF + OCR（含嵌入式图像识别）
- **Word（DOC/DOCX）** — python-docx + OCR
- **PowerPoint（PPT/PPTX）** — python-pptx + OCR
- **图片（PNG/JPG）** — RapidOCR 直接识别
- **纯文本（TXT/Markdown）** — 直接解析

### 🎯 混合向量搜索
- 使用 **BGE-M3** 模型同时生成稠密向量和稀疏向量
- 在 **Milvus** 向量数据库中执行混合搜索
- 通过 **BGE-Reranker-v2-M3** 对候选结果进行重排序
- 父-子分块策略（200 字符父块 / 50 字符子块）确保检索精度与上下文完整性

### 🔐 用户系统
- JWT 认证，区分 `admin` 和 `user` 角色
- admin 可上传/管理文档，user 仅可聊天问答
- 通过 `config.ini` 的 `[superuser]` 段配置管理员账户，服务启动时自动创建
- 多会话管理，对话历史持久化

### 📊 质量评估
- 集成 **RAGAS** 评估框架
- 四项指标：上下文精度、上下文召回率、忠实度、答案相关性

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (Vue 3)                        │
│         聊天界面 / 文档管理 / 会话管理 / Markdown 渲染        │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/SSE
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Server (Port 11000)                 │
│                  JWT 认证 / REST API / SSE 流式              │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                              ▼
┌──────────────────┐          ┌──────────────────────────────┐
│   BM25 检索层     │          │        RAG 检索层             │
│  (mysql_qa)      │          │       (rag_qa)               │
│                  │          │                              │
│  MySQL ←→ Redis  │          │  ┌──────────────────────┐    │
│  jieba 分词      │          │  │  查询分类器 (BERT)    │    │
│  BM25Okapi 匹配  │          │  │  需要检索? 不需要?    │    │
│  阈值: 0.95     │          │  └──────────┬───────────┘    │
└────────┬─────────┘          │             ▼                │
         │ 未命中              │  ┌──────────────────────┐    │
         │                     │  │ 策略选择器 (Qwen0.5B) │    │
         │                     │  │ 直接/HyDE/子查询/回溯 │    │
         │                     │  └──────────┬───────────┘    │
         │                     │             ▼                │
         │                     │  ┌──────────────────────┐    │
         │                     │  │  Milvus 混合搜索      │    │
         │                     │  │  稠密 + 稀疏向量      │    │
         │                     │  │  BGE-Reranker 重排序  │    │
         │                     │  └──────────┬───────────┘    │
         │                     │             ▼                │
         │                     │  ┌──────────────────────┐    │
         │                     │  │  LLM 生成 (Qwen1.5B)  │    │
         │                     │  │  上下文 + 历史 + 提示词│    │
         │                     │  └──────────────────────┘    │
         │                     └──────────────────────────────┘
         │                                    │
          └──────────────┬───────────────────┘
                         ▼
                   最终答案 → MySQL 历史记录 + QA 对缓存
```

### 数据流说明

1. 用户通过 Vue 前端发送查询请求到 FastAPI `/api/query`
2. `IntegratedSystem` 首先调用 BM25 检索器搜索历史 QA 对
3. 若 BM25 命中（置信度 > 0.95），直接返回缓存答案
4. 若未命中，进入 RAG 流水线：
   - BERT 查询分类器判断是否需要检索
   - Qwen2.5-0.5B 选择最优检索策略
   - BGE-M3 生成稠密+稀疏向量 → Milvus 混合搜索
   - BGE-Reranker 重排序 → Qwen2.5-1.5B 生成答案
5. 高质量答案（>32 字符）自动存入 MySQL QA 对表，丰富 BM25 语料库

## 📁 项目结构

```
rag_simple/
├── README.md                              # 项目文档
├── LICENSE                                # MIT 开源协议
├── .gitignore                             # Git 忽略规则
├── docker/                                # Docker 编排与数据卷
│   ├── docker-compose.yml                # MySQL + Redis + Milvus 编排
│   ├── init.sql                          # MySQL 初始化建表脚本
│   └── data/                             # 数据卷映射（运行时生成）
│       ├── mysql/                        # MySQL 数据
│       ├── redis/                        # Redis 数据
│       ├── etcd/                         # Milvus 元数据
│       ├── minio/                        # Milvus 对象存储
│       └── milvus/                       # Milvus 向量数据
├── backend/                              # Python 后端
│   ├── app.py                            # FastAPI 入口（Web 服务）
│   ├── main.py                           # IntegratedSystem 核心编排器
│   ├── config.ini                        # 全局配置文件
│   ├── base/                             # 基础设施
│   │   ├── config.py                     # 配置解析器（单例）
│   │   └── logger.py                     # 日志模块
│   ├── mysql_qa/                         # BM25 检索模块
│   │   ├── main.py                       # MySQLQA 组合器
│   │   ├── db/mysql_client.py            # MySQL CRUD
│   │   ├── cache/redis_client.py         # Redis 缓存
│   │   ├── retrieval/bm25_search.py      # BM25 搜索引擎
│   │   └── utils/preprocess.py          # jieba 分词预处理
│   ├── rag_qa/                           # RAG 核心模块
│   │   ├── core/
│   │   │   ├── rag_system.py             # RAGSystem 问答编排器
│   │   │   ├── vector_store.py           # Milvus 向量存储与搜索
│   │   │   ├── document_process.py       # 文档加载与分块
│   │   │   ├── llm.py                    # LLM 包装器（Qwen2.5）
│   │   │   ├── prompts.py               # RAG 提示词模板
│   │   │   ├── query_classifier.py       # BERT 查询分类器
│   │   │   └── strategy_selector.py      # 策略选择器
│   │   ├── document_loaders/             # OCR 文档加载器
│   │   │   ├── pdf_loader.py             # PDF 加载器
│   │   │   ├── doc_loader.py             # Word 加载器
│   │   │   ├── ppt_loader.py             # PPT 加载器
│   │   │   └── img_loader.py             # 图片加载器
│   │   ├── text_spliter/                 # 中文文本分割器
│   │   │   ├── chinese_recurisive_text_spliter.py
│   │   │   └── ali_text_spliter.py       # ModelScope 语义分割
│   │   └── assesment/rag_as.py          # RAGAS 评估
│   ├── model/                            # 本地模型文件
│   │   ├── bge-m3/                       # BGE-M3 嵌入模型
│   │   ├── bge-reranker-v2-m3/           # BGE 重排序模型
│   │   ├── bert-base-chinese/            # BERT 基础中文模型
│   │   ├── bert-classifier-base/         # 微调后的查询分类器
│   │   ├── nlp_bert_document-segmentation_chinese-base/
│   │   ├── qwen-2.5-0.5b-instruct/      # 策略选择模型
│   │   └── qwen-2.5-1.5b-instruct/      # 主 LLM
│   ├── data/                             # 数据文件
│   │   ├── mysql_qa/qa_data.csv          # 种子问答对
│   │   ├── query_classify/               # 分类器训练/评估数据
│   │   └── rag_evaluate/                 # RAGAS 评估数据
│   └── dist/                             # 前端构建产物（由 FastAPI 提供）
└── frontend/                             # Vue 3 前端
    ├── index.html                        # HTML 入口
    └── src/
        ├── main.js                       # Vue 应用入口
        ├── App.vue                       # 根组件
        ├── router/index.js               # 路由配置
        ├── stores/user.js                # Pinia 用户状态（持久化）
        ├── http/interceptor.js           # Axios JWT 拦截器
        ├── views/
        │   ├── Home.vue                  # 主聊天界面
        │   ├── Login.vue                 # 登录页
        │   └── Register.vue             # 注册页
        └── components/
            ├── SessionSidebar.vue        # 会话侧边栏
            ├── ChatHeader.vue            # 聊天头部
            ├── MessageList.vue           # 消息列表（Markdown 渲染）
            ├── ChatInput.vue             # 输入框 + 文件上传
            └── DocManagerModal.vue       # 文档管理弹窗
```

## 🚀 快速开始

### 环境要求

| 组件 | 版本 / 说明 |
|------|-------------|
| Python | 3.10+ |
| Node.js | 18+ |
| MySQL | 5.7+ |
| Redis | 6.0+ |
| Milvus | 2.3+（需支持稠密+稀疏混合搜索） |
| CUDA | 推荐 11.8+（GPU 推理加速） |
| 磁盘空间 | 约 20GB+（含模型文件） |

### 1. 克隆项目并安装依赖

```bash
# 进入后端目录
cd backend

# 安装 Python 依赖（建议使用 conda 虚拟环境）
pip install -r requirements.txt

# 进入前端目录
cd ../frontend

# 安装前端依赖
npm install
```

### 2. 启动数据库与中间件（Docker Compose）

项目提供了编排文件，一键启动所需全部中间件：

```bash
# 进入 docker 目录
cd docker

# 启动所有服务（MySQL + Redis + Milvus）
docker compose up -d

# 查看运行状态
docker compose ps

# 验证各服务
curl http://localhost:9091/healthz   # Milvus 健康检查
```

首次启动时，MySQL 会自动执行 `docker/init.sql` 建表。所有数据持久化在 `docker/data/` 目录下。

> 容器默认端口与 [backend/config.ini](backend/config.ini) 配置一致：MySQL=3306、Redis=6379、Milvus=19530。

### 3. 配置模型文件

将以下模型下载到 `backend/model/` 目录下：

- [BGE-M3](https://huggingface.co/BAAI/bge-m3) → `model/bge-m3/`
- [BGE-Reranker-v2-M3](https://huggingface.co/BAAI/bge-reranker-v2-m3) → `model/bge-reranker-v2-m3/`
- [BERT-base-Chinese](https://huggingface.co/google-bert/bert-base-chinese) → `model/bert-base-chinese/`
- [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) → `model/qwen-2.5-1.5b-instruct/`
- [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) → `model/qwen-2.5-0.5b-instruct/`
- [ModelScope 文档分割模型](https://www.modelscope.cn/models/iic/nlp_bert_document-segmentation_chinese-base) → `model/nlp_bert_document-segmentation_chinese-base/`

微调后的查询分类器模型需自行训练或从 `model/bert-classifier-base/` 加载。

### 4. 修改配置

编辑 [backend/config.ini](backend/config.ini)，根据实际环境修改数据库连接信息：

```ini
[mysql]
host = localhost
port = 3306
user = root
password = 123456
database = fqa

[redis]
host = localhost
port = 6379

[milvus]
host = localhost
port = 19530

[superuser]
# 管理员用户列表，多个用英文逗号分隔（一一对应下方密码）
users = Admin123,Super123
passwords = Admin123,Super123
```

### 5. 初始化种子数据

首次启动时，BM25 模块会自动从 `backend/data/mysql_qa/qa_data.csv` 加载种子问答对到 MySQL 和 Redis 中。

### 6. 构建前端

```bash
# 构建前端（输出到 frontend/dist/）
cd frontend
npm run build
```

### 7. 启动后端服务

```bash
cd backend
python app.py
```

服务将在 `http://localhost:11000` 启动。

## 📡 API 端点

### 认证相关

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/register` | 用户注册 | 无 |
| POST | `/api/login` | 用户登录，返回 JWT | 无 |

### 会话管理

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/create_session` | 创建新会话 | 无 |
| GET | `/api/sessions/{username}` | 获取用户会话列表 | 无 |
| DELETE | `/api/sessions/{session_id}` | 删除会话及历史 | 无 |
| GET | `/api/history/{session_id}` | 获取会话历史 | 无 |
| POST | `/api/clear_history` | 清除会话历史 | 无 |

### 问答

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/query` | 提交查询（支持 SSE 流式） | 无 |

### 文档管理（需 admin 角色）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/upload` | 上传文件到服务器 | Admin |
| POST | `/api/upload_embeddings` | 上传文件并直接入库 | Admin |
| POST | `/api/add_documents` | 将已上传文件向量化入库 | Admin |
| GET | `/api/documents/{username}` | 获取用户文档列表 | Admin |
| POST | `/api/clear_documents` | 清空用户所有文档 | Admin |
| POST | `/api/clear_chosed_documents` | 删除选中文档 | Admin |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/index` | 前端主页 |

## ⚙️ 配置说明

完整配置参见 [backend/config.ini](backend/config.ini)，主要配置项：

### 检索配置 `[retrieval]`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `parent_chunk_size` | 200 | 父块大小（字符） |
| `child_chunk_size` | 50 | 子块大小（字符） |
| `chunk_overlap` | 20 | 块重叠大小 |
| `retrieval_top_k` | 10 | 检索候选数 |
| `candidate_top_k` | 5 | 重排序后保留数 |
| `dense_weight` | 1.0 | 稠密检索权重 |
| `sparse_weight` | 0.7 | 稀疏检索权重 |

### BM25 配置 `[bm25]`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `similarity_threshold` | 0.95 | 相似度阈值，高于此值直接返回 |

### 对话配置 `[conversation_history]`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_history_length` | 10 | 对话历史最大保留轮数 |

### 超级管理员配置 `[superuser]`

服务启动时会自动根据此配置创建管理员账户（已存在则跳过）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `users` | - | 管理员用户名列表，多个用英文逗号分隔 |
| `passwords` | - | 管理员密码列表，与 `users` 一一对应 |

## 📊 RAGAS 评估

项目集成了 RAGAS 评估框架，可通过 [backend/rag_qa/assesment/rag_as.py](backend/rag_qa/assesment/rag_as.py) 运行评估。评估数据位于 `backend/data/rag_evaluate/`。

评估指标：

| 指标 | 说明 | 参考值 |
|------|------|--------|
| Context Precision | 检索上下文精确度 | 0.87 |
| Context Recall | 检索上下文召回率 | 0.98 |
| Faithfulness | 答案忠实度 | 0.88 |
| Answer Relevancy | 答案相关性 | 0.84 |

## 🛠️ 技术栈

### 后端

| 技术 | 用途 |
|------|------|
| FastAPI + Uvicorn | Web 框架与 ASGI 服务器 |
| PyMilvus | Milvus 向量数据库客户端 |
| BGE-M3 | 稠密 + 稀疏嵌入模型 |
| BGE-Reranker-v2-M3 | Cross-Encoder 重排序 |
| Transformers | BERT 分类器 / Qwen2.5 LLM |
| PyTorch | 深度学习框架 |
| RapidOCR (ONNX Runtime) | OCR 引擎（GPU/CPU 自动回退） |
| PyMuPDF | PDF 解析 |
| python-docx | Word 文档解析 |
| python-pptx | PowerPoint 解析 |
| rank-bm25 | BM25 关键词检索 |
| jieba | 中文分词 |
| RAGAS | RAG 质量评估 |
| PyMySQL | MySQL 数据库连接 |
| redis-py | Redis 缓存 |
| PyJWT | JWT 认证 |

### 前端

| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | UI 框架 |
| Pinia | 状态管理（持久化） |
| Vue Router | 客户端路由 |
| Axios | HTTP 客户端（JWT 拦截器） |
| marked | Markdown 渲染 |
| Vite | 构建工具 |

## 📝 License

本项目基于 [MIT License](LICENSE) 开源协议发布。
