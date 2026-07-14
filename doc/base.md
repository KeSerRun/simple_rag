# 基础模块

> 位置：`base/` — 全局基础设施

## 文件结构

```
base/
├── __init__.py
├── config.py         # 配置解析 (config.ini + .env + 环境变量)
├── llm_client.py     # OpenAI 兼容客户端 (chat / embedding)
└── logger.py         # 结构化日志
```

## Config — 配置管理

**文件**: [config.py](../base/config.py)

### 加载顺序（低→高）

1. `config.ini` — 基础配置（支持 `[section]` 分组）
2. `.env` 文件 — 环境变量覆盖（可选，按行解析 `KEY=VALUE`）
3. OS 环境变量 — 最高优先级

### 路径标准化

`normalize_path()` — 相对路径拼接项目根目录，绝对路径不变。

### 热重载

管理后台保存设置 → `_write_config_ini` 行级替换 → 同时更新内存中 `conf` 对象属性 → 即时生效，无需重启。

### 主要配置项分组

| 分组 | config.ini 段 | 关键项 |
|------|--------------|--------|
| API | `[api]` | chat_model, api_key, base_url, timeout |
| Embedding | `[api]` | embedding_model, embedding_dim, embedding_api_key |
| MinerU | `[api]` | mineru_api_key, base_url, model_version |
| 检索 | `[retrieval]` | retrieval_top_k, candidate_top_k, min_chunk_length |
| Agent | `[agent]` | max_tool_iter, max_output_chars, eval_max_workers |
| 搜索 | `[search]` | backend (duckduckgo/searxng/bocha/bing) |
| 治理 | `[governance]` | context_window_chars, compression_ratio |

## LLM Client

**文件**: [llm_client.py](../base/llm_client.py)

OpenAI 兼容客户端，支持：

| 方法 | 功能 |
|------|------|
| `chat(messages, **kwargs)` | 非流式对话 |
| `chat_stream(messages, **kwargs)` | 流式对话（逐 token yield） |
| `embed(texts, model)` | 批量文本嵌入 |
| `count_tokens(text)` | Token 计数 |

同时用于对话模型和嵌入模型（不同 base_url / api_key）。

## Logger

**文件**: [logger.py](../base/logger.py)

结构化日志，支持：

| 级别 | 用途 |
|------|------|
| `console_log_level` | 控制台输出 |
| `app_log_level` | 应用运行日志 |
| `http_log_level` | HTTP 请求日志 |
| `user_log_level` | 用户操作日志（QA 记录） |
