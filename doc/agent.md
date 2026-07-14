# Agent 引擎

> 位置：`agent/` — 工具调用循环、状态管理、上下文治理、集成入口

## 文件结构

```
agent/
├── __init__.py           # 导出 ToolLoop, registry, TOOL_SCHEMAS
├── context.py            # SkillLoader, WorkflowRouter, SystemContext
├── governor.py           # compress_history, truncate_history
├── integrate.py          # IntegratedSystem (顶层集成入口)
├── loop.py               # ToolLoop (工具调用循环核心)
├── state.py              # AgentState (运行时状态)
└── tools/                # 工具注册与 handlers
    ├── __init__.py       # 自动发现 + 注册
    ├── registry.py       # ToolRegistry, ToolDef, register_all_builtins
    ├── _infra_handlers.py    # 基础设施工具 (set_goal, complete_goal, my, read_workflow, ask_user_for_clarification)
    ├── _kb_handlers.py       # 知识库工具 (search_knowledge_base, read_full_document, list_documents 等)
    ├── _web_handlers.py      # 联网工具 (web_search, read_url)
    ├── _format.py            # 检索结果格式化
    └── cache.py              # 内存缓存 (TTL 5min, LRU 100 条)
```

## ToolLoop — 工具调用循环

**文件**: [loop.py](../agent/loop.py)

核心消息循环：system → user → LLM → tool_calls → 执行 → 回灌 → 循环 → 最终答案。

### 工作流程

```
generate_answer(query, stream=False)
  │
  ├─ _build_system_message()
  │   ├─ identity (self.system_context.identity)
  │   ├─ 当前时间/时区
  │   ├─ 回答风格 skill (prompts/style/)
  │   └─ 工作流指令 (prompts/workflow/)
  │
  ├─ 组装 messages: [system, ...history, user(query)]
  │
  ├─ _run_tool_loop() 或 _run_tool_loop_stream()
  │   └─ LLM 调用 → 返回 tool_calls?
  │       ├─ 是 → concurrent.futures 并行执行工具
  │       │        → dispatch(name, args_json, ctx=ToolContext)
  │       │        → 结果追加到 messages
  │       │        → continue (下一轮 LLM 调用)
  │       └─ 否 → 返回最终 content
  │
  ├─ should_continue() 检查
  │   ├─ iteration >= max_iterations? → 中断，保存状态
  │   └─ total chars > context_window_chars? → 中断
  │
  └─ 返回答案
```

### 工具并发执行

并发的安全工具（`search_knowledge_base`, `read_chunk_context`, `read_document_titles`, `list_documents`）在同一批次中并行执行，其他工具顺序执行。

### 中断恢复

达工具迭代上限后，返回提示文本，用户回复"继续"即可从断点恢复。

## AgentState — 运行时状态

**文件**: [state.py](../agent/state.py)

| 方法 | 功能 |
|------|------|
| `add_user_query(content)` | 记录用户输入 |
| `add_assistant_response(content, tool_calls)` | 记录 LLM 回复 |
| `add_tool_result(tool_call_id, content)` | 记录工具结果 |
| `should_continue()` | 检查迭代上限和字符预算 |
| `_save_turn_messages()` | 持久化本轮消息 |

## IntegratedSystem — 集成入口

**文件**: [integrate.py](../agent/integrate.py)

对外提供统一问答接口：

| 方法 | 功能 |
|------|------|
| `run_agent(session_id, question, partition, style, stream, workflow)` | 问答入口 |
| `get_history(session_id)` | 加载历史 + 上下文治理 |
| `cancel_generation(session_id)` | 中断流式生成 |

## SystemContext — 系统上下文

**文件**: [context.py](../agent/context.py)

管理三类系统提示：
- `identity` — 从 `prompts/identity.md` 加载的 LLM 身份设定
- `SkillLoader` — 从 `prompts/style/` 加载回答风格
- `WorkflowRouter` — 从 `prompts/workflow/` 加载工作流

## ContextGovernor — 上下文治理

**文件**: [governor.py](../agent/governor.py)

| 函数 | 触发条件 | 效果 |
|------|---------|------|
| `compress_history()` | 输入字符 > `budget` | tool 消息按 4 等分保留 30% |
| `truncate_history()` | 压缩后仍超 `budget` | 丢弃最早 turn/qa，保留 event |

详见 [上下文治理机制](architecture.md#上下文治理机制)。

## 工具注册中心

**文件**: [tools/registry.py](../agent/tools/registry.py)

| 组件 | 功能 |
|------|------|
| `ToolRegistry` | 注册/查询/调度工具 |
| `ToolDef` | 工具定义（name/description/parameters/handler） |
| `ToolContext` | 工具执行上下文（vector_store/partition/data_store/session_id） |
| `register_all_builtins()` | 注册全部 14 个内建工具 |

已注册工具的详细文档见 [tool.md](tool.md)。
