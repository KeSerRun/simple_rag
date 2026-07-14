# 工具文档

> RAG Simple 系统中所有已注册的工具（共 14 个），按功能分类。
> 注册位置：`agent/tools/registry.py` → `register_all_builtins()`

---

## 目录

- [1. 知识库检索](#1-知识库检索)
  - [search_knowledge_base](#search_knowledge_base)
  - [read_full_document](#read_full_document)
  - [list_documents](#list_documents)
  - [read_chunk_context](#read_chunk_context)
  - [read_document_titles](#read_document_titles)
  - [read_section](#read_section)
  - [search_document_content](#search_document_content)
- [2. 互联网搜索](#2-互联网搜索)
  - [web_search](#web_search)
  - [read_url](#read_url)
- [3. 会话控制](#3-会话控制)
  - [set_goal](#set_goal)
  - [complete_goal](#complete_goal)
  - [my](#my)
  - [read_workflow](#read_workflow)
- [4. 交互辅助](#4-交互辅助)
  - [ask_user_for_clarification](#ask_user_for_clarification)

---

## 1. 知识库检索

### search_knowledge_base

**功能**：知识库语义检索，覆盖文本、表格、图片图表。支持多 query，自动 Reciprocal Rank Fusion（RRF）重排。

**嵌入模型**：`BAAI/bge-m3`

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `queries` | `string[]` | ✅ | - | 检索查询列表。简单问题 1 个；多焦点问题拆 2-10 个子查询。用名词短语而非完整问句。 |
| `search_system` | `boolean` | ❌ | `true` | 是否同时搜索系统公开文档。设为 `false` 只搜索用户自己的文档。 |
| `top_k` | `integer` | ❌ | `10` | 返回结果数量，上限 `50`。粗略概览时减小，全面排查时增加。 |

**说明**：
- 当传入多个 query 时，每个 query 单独检索 `retrieval_top_k`（50）条
- 所有结果通过 RRF 融合排序（公式：`score = Σ 1/(60 + rank_i)`）
- 被多个 query 同时命中的片段排名会自然提升
- 知识库中每块都有 `chunk_type` 标记（`text` / `table` / `image`），不同类型的内容特征不同：
  - `text`：纯文本段落，自然语言叙述
  - `table`：表格数据，正文以 Markdown 表格线为主，数值密集
  - `image`：图片图表，正文包含图标题或图表描述
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_search_kb()`

---

### read_full_document

**功能**：读取某篇文档的完整全文（Markdown 格式），支持分页。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `filename` | `string` | ✅ | - | 文档文件名（含扩展名）。必须是文档清单中出现的完整文件名，如 `KD指标.pdf` |
| `offset` | `integer` | ❌ | `0` | 字符偏移位置，用于分页读取。末尾会提示后续 offset。 |
| `max_chars` | `integer` | ❌ | `10000` | 本次最多读取字符数。建议不超过 50000。 |

**说明**：
- 读取的是 MinerU 解析后的 Markdown 源文件
- 分页读取时返回内容末尾会附带页码提示，如 `offset=10000 继续阅读`
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_read_full_document()`

---

### list_documents

**功能**：列出知识库中的文档清单，支持关键词过滤和排序。返回文档名、类型、大小、修改时间。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `pattern` | `string` | ❌ | - | 文件名关键词过滤（如 `KD`、`财报`），不传列出全部。 |
| `list_system` | `boolean` | ❌ | `true` | 是否同时列出系统公开文档。设为 `false` 只列用户文档。 |
| `sort_by` | `string` | ❌ | `name` | 排序方式：`name`（按名称）或 `time`（按修改时间）。 |

**说明**：
- 系统文档前有 📖 图标，用户文档前有 📄 图标
- 可先调用此工具查看可用文档，再使用 `read_full_document` 读取具体内容
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_list_documents()`

---

### read_chunk_context

**功能**：读取某一片段前后的相邻文档内容。当检索到的片段内容不完整、图表标题需要查看正文、同主题片段分散时使用。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `chunk_id` | `string` | ✅ | - | 目标片段的 ID，从检索结果标头 `[id=]` 字段获取。 |
| `before` | `integer` | ❌ | `3` | 向前取多少块（最大 10）。 |
| `after` | `integer` | ❌ | `3` | 向后取多少块（最大 10）。 |

**说明**：
- 按页面顺序排列，目标 chunk 标记为 `【目标】`
- 内容截断至每块 500 字符
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_read_chunk_context()`

---

### read_document_titles

**功能**：读取某篇文档的标题目录结构。返回文档内所有级别的标题列表，方便快速定位感兴趣的内容。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `source` | `string` | ✅ | - | 文档文件名（含扩展名），如 `KD指标.pdf`。 |

**说明**：
- 读取的是 MinerU 解析后的 Markdown 源文件中的标题（`#` 开头行）
- 配合 `read_section` 或 `read_full_document` 读取具体内容
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_read_document_titles()`

---

### read_section

**功能**：根据文档名和标题关键词，读取该标题下的正文内容。支持模糊匹配和拆词匹配。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `source` | `string` | ✅ | - | 文档文件名（含扩展名），如 `KD指标.pdf`。 |
| `heading` | `string` | ✅ | - | 标题关键词，匹配任意级别标题。如 `第一章`、`1.1 背景`、`风险收益`。 |

**说明**：
- 先精确匹配，再拆词匹配
- 标题层级更高的下一个标题出现时结束，确保读取完整章节
- 最多返回 30000 字符，超出截断并提示
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_read_section()`

---

### search_document_content

**功能**：在所有知识库文档的全文内容中搜索关键词（大小写不敏感），返回匹配的文档名和行号。类似于全文 grep。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `keyword` | `string` | ✅ | - | 搜索关键词（大小写不敏感）。 |
| `source` | `string` | ❌ | - | 限定仅搜索某篇文档（含扩展名）。 |
| `max_results` | `integer` | ❌ | `10` | 最大返回匹配数量（1-50）。 |

**说明**：
- 搜索范围包括用户文档和系统文档
- 返回格式：文档名 → 行号 → 上下文片段
- **handler**：`agent/tools/_kb_handlers.py` → `_exec_search_document_content()`

---

## 2. 互联网搜索

### web_search

**功能**：搜索互联网获取最新信息（实时新闻、数据等知识库未覆盖的内容）。

**搜索后端**：`duckduckgo`

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | `string` | ✅ | - | 搜索关键词，用名词短语或简洁问句。 |
| `max_results` | `integer` | ❌ | `5` | 返回结果数量（1-10）。 |

**说明**：
- 返回结果包含标题、摘要和来源链接
- 对完全相同的 query 最多调用 2 次，后续重复调用会被拦截
- **handler**：`agent/tools/_web_handlers.py` → `_exec_web_search()`

---

### read_url

**功能**：读取指定网页的完整文字内容。仅限公开可访问的网页。

**请求超时**：`60` 秒

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `url` | `string` | ✅ | - | 要读取的网页完整 URL（必须以 `http://` 或 `https://` 开头）。 |
| `offset` | `integer` | ❌ | `0` | 读取起始偏移（字符数）。 |
| `max_chars` | `integer` | ❌ | `10000` | 本次最多读取字符数。建议不超过 50000。 |

**说明**：
- 对完全相同的 URL 最多调用 2 次
- 分页读取时末尾会提示后续 offset
- **handler**：`agent/tools/_web_handlers.py` → `_exec_read_url()`

---

## 3. 会话控制

### set_goal

**功能**：设置当前会话的持续目标。目标会持续注入 system prompt，在后续多轮对话中自动保留上下文。适合用户交代需要多步完成的任务时调用。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `goal` | `string` | ✅ | - | 目标的详细描述，LLM 应该努力完成的目标。 |

**说明**：
- 设置后每个后续请求都会携带此目标
- **handler**：`agent/tools/_infra_handlers.py` → `_exec_set_goal()`

---

### complete_goal

**功能**：标记当前目标已完成。

**参数**：无

**说明**：
- 当用户确认目标已完成时调用
- 清除 `set_goal` 设置的目标
- **handler**：`agent/tools/_infra_handlers.py` → `_exec_complete_goal()`

---

### my

**功能**：查看当前会话的运行时状态和配置（模型、迭代上限、上下文窗口、检索参数等）。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `action` | `string` | ✅ | - | 要执行的操作：`check`（查看状态）。 |
| `key` | `string` | ❌ | - | 要查看的配置项关键词，如 `model`。不传则显示全部。 |

**说明**：
- `my(action='check')` 查看完整状态
- `my(action='check', key='model')` 查看单项
- **handler**：`agent/tools/_infra_handlers.py` → `_exec_my()`

---

### read_workflow

**功能**：读取工作流的完整分步指令。可用工作流已在 system prompt 中列出。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `string` | ✅ | - | 工作流名称，如 `USstocks`、`Autoplan`、`DeepResearch`。 |

**当前可用工作流**：
- `Briefing` — 简报
- `Comparison` — 对比分析
- `DeepResearch` — 深度研究
- `Autoplan` — 自动规划
- `USstocks` — 美股分析

**说明**：
- 先调用此工具获取完整指令，再按步骤执行
- **handler**：`agent/tools/_infra_handlers.py` → `_exec_read_workflow()`

---

## 4. 交互辅助

### ask_user_for_clarification

**功能**：当用户请求模糊（指代不清、未指定具体文档）且已有检索结果不足以推断时，向用户提问以获取补充信息。

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `question` | `string` | ✅ | - | 需要向用户询问的具体问题。如 `请问您指的是本季度的哪一份财报？`。 |

**说明**：
- 调用后对话中断，等待用户回复
- 仅在已有检索结果仍不足以推断时才应调用
- **handler**：`agent/tools/_infra_handlers.py` → `_exec_ask_clarification()`
