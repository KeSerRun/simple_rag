"""Agent: LLM tool-calling 循环 + 运行时状态 + 工具注册中心 + workflow 路由 + 集成系统"""
from .rag_system import RAGSystem
from .integrated_system import IntegratedSystem
from .state import AgentState
from .tools.registry import ToolRegistry, ToolContext, ToolDef
from .tools import registry, TOOL_SCHEMAS, execute_tool
from .workflow_router import WorkflowRouter
from .bus import MessageBus, bus as agent_bus
from .state_machine import StateMachine, StateContext, TurnState
from .checkpoint import CheckpointStore, Checkpoint, restore_messages
from .subagent import SubagentManager
from .agent_loop import AgentLoop, SessionManager
from .hooks import AgentHook, CompositeHook, LoggingHook

__all__ = [
    "RAGSystem", "IntegratedSystem",
    "AgentState",
    "ToolRegistry", "ToolContext", "ToolDef",
    "registry", "TOOL_SCHEMAS", "execute_tool",
    "WorkflowRouter",
    "MessageBus", "agent_bus",
    "StateMachine", "StateContext", "TurnState",
    "CheckpointStore", "Checkpoint", "restore_messages",
    "SubagentManager",
    "AgentLoop", "SessionManager",
    "AgentHook", "CompositeHook", "LoggingHook",
]
