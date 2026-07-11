# Agent 智能体模块 — `backend/agent/`

负责智能体的工具调度、工作流路由和对话状态管理。LLM 通过这个模块调用知识库搜索、联网搜索等工具。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `rag_system.py` | **核心入口**。`RAGSystem` 类，封装整个 RAG 问答流程：接收用户问题 → 循环调用工具 → 生成回答 |
| `registry.py` | 工具注册中心。`ToolRegistry` 管理所有工具的注册、查找、调度执行 |
| `workflow_router.py` | 工作流路由器。根据关键词匹配预定义工作流（如「写报告」「分析」），走不同 prompt 路线 |
| `state.py` | 对话状态管理。`State` 类保存消息历史、迭代次数、分区信息等 |
| `context_builder.py` | 上下文构建器。组装 system prompt、注入工具描述、构建消息列表 |
| `tools/__init__.py` | 工具注册入口。导入并注册所有工具 handler |
| `tools/_handlers.py` | 工具处理函数。`search_knowledge_base`、`search_web`、`read_full_document` 等的具体实现 |
| `tools/_format.py` | 检索结果格式化。把 Document 列表格式化为 LLM 友好的文本 |
| `tools/_web_handlers.py` | Web 工具处理函数 + 搜索后端实现。DuckDuckGo / SearXNG / 博查 / Bing |

---

## 调用方式

### 1. 直接问答 (`RAGSystem`)

```python
from agent.rag_system import RAGSystem
from storage.json_store import DataStore

# 初始化
data_store = DataStore()
rag = RAGSystem(data_store=data_store)

# 单轮问答（同步）
result = rag.ask(session_id="session_001", query="沪深300最近表现如何？")
print(result["answer"])       # LLM 的回答文本
print(result["sources"])      # 引用的文档来源

# 流式问答
for chunk in rag.ask_stream(session_id="session_001", query="简单介绍一下"):
    print(chunk, end="", flush=True)

# 流式问答（自动规划模式）
for chunk in rag.ask_stream(session_id="session_001", query="写一份分析报告"):
    print(chunk, end="", flush=True)
```

### 2. 工具注册与调用 (`ToolRegistry`)

```python
from agent.tools.registry import ToolRegistry, ToolContext
from rag.vector_store import VectorStore

# 创建注册中心
registry = ToolRegistry()

# 注册自定义工具
def my_handler(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    results = ctx.vector_store.search(query)
    return f"找到 {len(results)} 条结果"

registry.register(
    name="my_search",
    description="搜索知识库",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["query"],
    },
    handler=my_handler,
)

# 调用工具
ctx = ToolContext(vector_store=store)
result = registry.dispatch("my_search", '{"query": "沪深300"}', ctx=ctx)
print(result)
```

### 3. 工作流路由 (`WorkflowRouter`)

```python
from agent.workflow_router import WorkflowRouter

router = WorkflowRouter()
matched = router.route("帮我写一份沪深300的分析报告")
print(matched.workflow_name)  # 比如 "analysis"
print(matched.prompt)          # 匹配到的 system prompt
```

---

## RAGSystem 内部流程

```
用户输入 → WorkflowRouter 匹配工作流
         → State 初始化（消息历史 + 分区 + 迭代次数）
         → ContextBuilder 构建消息列表
         → 进入 tool-loop 循环:
              1. LLM 选择工具 → 调 registry.dispatch()
              2. 工具执行 → 返回结果
              3. 结果追加到消息列表
              4. 判断是否继续（达上限或 LLM 决定停止）
         → 生成最终回答
         → 返回结果
```

---

## 依赖关系

```
rag_system.py ──→ registry.py / state.py / context_builder.py / workflow_router.py / tools/
tools/__init__.py ──→ registry.py / _handlers.py
_web_handlers.py ──→ registry.py / _format.py
workflow_router.py ──→ (读取 route.md 路由文件)
```
