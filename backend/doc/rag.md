# RAG 核心模块 — `backend/rag/`

RAG（检索增强生成）核心模块，负责文档加载、向量化存储、语义检索和检索质量评估。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `vector_store.py` | 向量存储核心。基于 OpenAI Embedding + FAISS 的本地向量库。提供文档入库、相似度搜索、分区管理 |
| `llm_client.py` | LLM 客户端封装。统一管理 OpenAI 兼容 API 的聊天/工具调用/Embedding 请求，包含流式输出和 LLM Listwise Reranker |
| `pdf_parser.py` | PDF 解析器。对接 MinerU API，上传 PDF → 解析 → 下载 → 分块 |
| `text_splitter.py` | 中文文本切分器。递归按段落/句号/逗号切分，适合中文场景 |
| `eval_rag.py` | 检索质量评估。用测试查询调用检索工具，LLM 打分计算精确率 |
| `eval_queries.json` | 评估用的测试查询列表（外部文件，可编辑） |

---

## 调用方式

### 1. 向量存储 (`VectorStore`)

```python
from rag.vector_store import VectorStore
from rag.llm_client import OpenAIClient

# 初始化
client = OpenAIClient(api_key="sk-xxx", base_url="...")
store = VectorStore(
    client=client,
    embedding_model="text-embedding-ada-002",
    embedding_dim=1024,
)

# 添加文档
store.add_documents(documents, partition="my_partition")

# 相似度搜索
results = store.search(query="沪深300择时策略", top_k=10, partition="my_partition")
for doc in results:
    print(doc.page_content)       # 文本内容
    print(doc.metadata["source"]) # 来源文件名

# 删除文档
store.delete_documents_by_sources(["xxx.pdf"], partition="my_partition")
```

### 2. LLM 客户端 (`OpenAIClient`)

```python
from rag.llm_client import OpenAIClient

client = OpenAIClient(
    api_key="sk-xxx",
    base_url="https://api.openai.com/v1",
)

# 纯文本对话
resp = client.chat(
    messages=[{"role": "user", "content": "你好"}],
    model="deepseek-v4-flash",
)
print(resp)  # "你好！有什么可以帮助你的吗？"

# 带工具调用的对话
resp = client.chat_with_tools(
    messages=[{"role": "user", "content": "搜索一下沪深300"}],
    model="deepseek-v4-flash",
    tools=[{"type": "function", "function": {...}}],
)

# 获取 Embedding 向量
vectors = client.embed(texts=["金融文本"], model="text-embedding-ada-002")
```

### 3. LLM Reranker (`LLMReranker`)

```python
from rag.llm_client import LLMReranker

reranker = LLMReranker(client=client, model="deepseek-v4-flash", enable=True)
reranked = reranker.rerank(query="沪深300", chunks=result_chunks, top_k=5)
```

### 4. PDF 解析 (`MinerUPDFLoader`)

```python
from rag.pdf_parser import MinerUPDFLoader

loader = MinerUPDFLoader("path/to/doc.pdf")
documents = loader.load()  # 返回 Document 列表
```

### 5. 文本切分 (`ChineseRecursiveTextSplitter`)

```python
from rag.text_splitter import ChineseRecursiveTextSplitter

splitter = ChineseRecursiveTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_text("这是一段很长的中文文本……")
```

### 6. 评估 (`eval_rag`)

```python
from rag.eval_rag import test_precision, load_test_queries, print_precision_report
from rag.llm_client import OpenAIClient

judge = OpenAIClient(api_key="sk-xxx")
results = test_precision(judge)  # 运行评估
print_precision_report(results)   # 打印报告

# 编辑测试查询
from rag.eval_rag import load_test_queries, save_test_queries
queries = load_test_queries()
queries.append("新查询词")
save_test_queries(queries)
```

---

## 依赖关系

```
pdf_parser.py  ──→  vector_store.py (Document 类)
text_splitter.py ──→ vector_store.py (Document 类)
vector_store.py ──→ llm_client.py (Embedding)
vector_store.py ──→ pdf_parser.py (MinerUPDFLoader)
eval_rag.py ──→ llm_client.py / vector_store.py / agent.tools
llm_client.py  （无内部依赖）
```
