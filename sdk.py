# ── RAG Simple SDK ────────────────────────────────────────────────
"""RAG Simple SDK — 对外测试/调用接口。

提供简化版的问答和系统信息查询接口，
适合在脚本或交互式环境中快速使用。

快速上手：
    from sdk import ask
    print(ask("你好"))
"""

from __future__ import annotations

from typing import Optional

from agent.integrate import IntegratedSystem

_system: Optional[IntegratedSystem] = None


# ── 系统初始化 ────────────────────────────────────────────────────


def _get_system() -> IntegratedSystem:
    """获取或初始化全局 IntegratedSystem 单例。

    Returns:
        IntegratedSystem 实例。
    """
    global _system
    if _system is None:
        _system = IntegratedSystem()
    return _system


# ── 问答接口 ──────────────────────────────────────────────────────


def ask(
    question: str,
    session_id: Optional[str] = None,
    style: Optional[str] = None,
    workflow: Optional[str] = None,
) -> str:
    """单轮问答（非流式），返回回答文本。

    Args:
        question: 用户问题。
        session_id: 会话 ID，不传则自动生成。
        style: 回答风格（如 'default'）。
        workflow: 工作流名称（如 'DeepResearch'，None 表示自动选择）。

    Returns:
        回答文本字符串。
    """
    import uuid
    sid = session_id or f"sdk-{uuid.uuid4().hex[:8]}"
    system = _get_system()
    return system.run_agent(sid, question, partition=sid, style=style, workflow=workflow)


def ask_stream(
    question: str,
    session_id: Optional[str] = None,
    style: Optional[str] = None,
    workflow: Optional[str] = None,
):
    """流式问答，yield 事件字典。

    Args:
        question: 用户问题。
        session_id: 会话 ID，不传则自动生成。
        style: 回答风格（如 'default'）。
        workflow: 工作流名称（None 表示自动选择）。

    Yields:
        事件字典，支持以下类型：
        - {"type": "token", "text": "..."}
        - {"type": "status", "status": "..."}
    """
    import uuid
    sid = session_id or f"sdk-{uuid.uuid4().hex[:8]}"
    system = _get_system()
    yield from system.run_agent(sid, question, partition=sid,
                                style=style, workflow=workflow, stream=True)


def clear_history(session_id: str):
    """清除指定会话的历史记录。

    Args:
        session_id: 会话 ID。
    """
    system = _get_system()
    system.data_store.delete_session_history(session_id)
    system.data_store.delete_session(session_id)


def info() -> dict:
    """查看当前系统状态。

    Returns:
        包含当前模型名称和可用工作流数量的字典。
    """
    system = _get_system()
    return {
        "model": system.rag_qa.chat_model,
        "tools": len(system.rag_qa.workflow_router._workflows) if hasattr(system.rag_qa, 'workflow_router') else 0,
    }
