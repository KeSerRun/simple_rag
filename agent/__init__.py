"""Agent 核心模块: LLM tool-calling 循环、运行时状态、工具注册、工作流路由与集成系统。

该模块是 RAG 系统的 Agent 层，提供以下核心能力:
  - RAGSystem / IntegratedSystem: 高层集成入口
  - AgentState: tool-calling 循环的运行时状态管理
  - ToolRegistry / ToolContext / ToolDef: 工具注册与执行引擎
  - WorkflowRouter: 基于 prompts/workflow/ 的工作流路由
  - CheckpointStore / Checkpoint: 工具执行状态的保存与恢复
  - SessionLockManager: 会话级别互斥锁

# ──

子模块结构:
  - agent/state.py:     AgentState 运行时状态
  - agent/loop.py:      SessionLockManager 并发控制
  - agent/checkpoint.py: Checkpoint 检查点机制
  - agent/workflow.py:   WorkflowRouter 工作流路由
  - agent/context_builder.py: ContextBuilder prompt 组装
  - agent/tools/:        工具注册、执行与 schemas
"""

from .rag_system import RAGSystem
from .integrate import IntegratedSystem
from .state import AgentState
from .tools.registry import ToolRegistry, ToolContext, ToolDef
from .tools import registry, TOOL_SCHEMAS, execute_tool
from .workflow import WorkflowRouter
from .checkpoint import CheckpointStore, Checkpoint, restore_messages
from .session import SessionLockManager

__all__ = [
    "RAGSystem", "IntegratedSystem",
    "AgentState",
    "ToolRegistry", "ToolContext", "ToolDef",
    "registry", "TOOL_SCHEMAS", "execute_tool",
    "WorkflowRouter",
    "CheckpointStore", "Checkpoint", "restore_messages",
    "SessionLockManager",
]
