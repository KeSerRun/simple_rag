# 基础配置模块 — `backend/base/`

提供全局配置解析和日志记录基础设施，所有其他模块都依赖本模块。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `config.py` | 全局配置。从 `config.ini` 读取所有配置项，提供 `conf` 全局单例 |
| `logger.py` | 日志系统。控制台 + 文件 + HTTP 请求三层日志，支持按模块设置级别 |
| `__init__.py` | 空文件，标记为 Python 包 |

---

## 调用方式

### 1. 读取配置 (`conf`)

```python
from base.config import conf

# 字符串配置
api_key = conf.openai_api_key          # API 密钥
base_url = conf.openai_base_url        # API 地址
model = conf.chat_model                # 模型名称

# 整数配置
top_k = conf.retrieval_top_k           # 检索数量（默认 30）
candidate_k = conf.candidate_top_k     # 重排后保留数（默认 5）
timeout = conf.openai_timeout          # 超时秒数


[retrieval]
retrieval_top_k = 30
candidate_top_k = 5
data_dir = conf.data_dir               # 数据存储目录
vector_dir = conf.vector_store_dir     # 向量库存储目录
log_path = conf.log_path               # 日志存放目录
```

### 2. 日志记录 (`logger`)

```python
from base.logger import logger

# 不同级别的日志
logger.debug("调试信息，开发时用")
logger.info("正常信息，服务运行状态")
logger.warning("警告，不影响运行但需要注意")
logger.error("错误，某个操作失败了")

# 日志会自动同时输出到：
#   - 控制台（默认 DEBUG 级别，彩色输出）
#   - 日志文件（默认 INFO 级别，按日期轮转）
```

### 3. HTTP 请求日志

```python
from base.logger import log_http

# 记录一次 HTTP 请求（由 FastAPI 中间件自动调用）
log_http("GET", "/api/query", 200, "username")
# 输出格式: 127.0.0.1 - username [08/Jul/2026] "GET /api/query" 200
```

---

## 配置项来源

配置按以下优先级合并（高优先级覆盖低优先级）：

1. **环境变量**（最高优先级）
2. **config.ini 文件**
3. **默认值**（写在代码中）

config.ini 示例结构：
```ini
[storage]
data_dir = data
vector_store_dir = data/vector_store

[retrieval]
retrieval_top_k = 30
candidate_top_k = 5

[api]
chat_api_key = sk-xxx
chat_base_url = https://api.openai.com/v1
chat_model = deepseek-v4-flash

[agent]
max_tool_iter = 8

[logger]
app_log_level = INFO
console_log_level = DEBUG
```

---

## 依赖关系

```
config.py ──→ configparser（内置） / os
logger.py ──→ logging（内置） / os
（两个文件相互独立，互不依赖）
```
