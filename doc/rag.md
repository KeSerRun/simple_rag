# RAG 基础设施

> 位置：`rag/` — 向量存储、PDF 解析、质量评估

## 文件结构

```
rag/
├── __init__.py
├── vector_store.py     # VectorStore (FAISS + Embedding)
├── pdf_parser.py       # MinerU PDF 解析
└── eval_rag.py         # 质量评估工具 (LLM 评分)
```

## VectorStore — 向量存储

**文件**: [vector_store.py](../rag/vector_store.py)

基于 OpenAI Embedding + FAISS 的本地向量存储。

### 核心方法

| 方法 | 说明 |
|------|------|
| `add_documents(documents, partition)` | 嵌入文档并写入索引 |
| `search(query, top_k, source_filter, partition)` | 语义检索 |
| `get_documents_by_partition(partition)` | 分区文档列表 |
| `delete_documents_by_partition(partition)` | 按分区删除 |
| `delete_documents_by_sources(sources, partition)` | 按来源删除 |
| `store_documents_from_dir(directory, partition)` | 从目录加载 |

### 数据流

```
文档文件 → MinerU 解析 → chunk 分块
  → process_documents_from_dir() 过滤短块和停用词
  → add_documents()
    → _embed() 生成向量 (L2 归一化)
    → 写入 FAISS 索引 + metadata JSON
    → 持久化到磁盘
```

### 检索流程

```
query → _embed(query) → FAISS search (top_k × 4 候选)
  → partition/source 过滤
  → 取 top_k → 去重 → 返回 Document[]
```

### 元数据字段

| 字段 | 说明 |
|------|------|
| `id` | 内容 MD5 哈希 |
| `text` | chunk 正文 |
| `source` | 来源文件名 |
| `partition` | 分区标识 |
| `chunk_type` | 类型：text / table / image |
| `page` | 页码 |
| `section_path` | 章节路径 |
| `caption` | 图表标题 |
| `img_path` | 关联图片路径 |

## PDF Parser — MinerU 解析

**文件**: [pdf_parser.py](../rag/pdf_parser.py)

通过 MinerU API 进行 PDF 解析，支持：
- PDF 分页解析
- 表格识别（Markdown 格式输出）
- 图片/图表提取
- 章节结构保留
- VLM / Lite 两种模型版本

## Eval — 检索质量评估

**文件**: [eval_rag.py](../rag/eval_rag.py)

对每个检索结果使用 LLM 评判器打分 0-4：

| 评分 | 含义 |
|------|------|
| 0 | 完全不相关 |
| 1 | 略微相关 |
| 2 | 部分相关 |
| 3 | 相关 |
| 4 | 非常相关 |

评分 ≥ 3 的计为"相关"，计算 Precision@K。
