"""基础设施工具 handlers: 虚拟工具 / 子 Agent / 辅助函数等。
注册统一在 registry.py 的 register_all_builtins() 中。
"""
from __future__ import annotations

from .registry import ToolContext


# ===== ask_user_for_clarification（虚拟工具） =====
def _exec_ask_clarification(args: dict, ctx: ToolContext) -> str:
    """
    虚拟工具 handler: ask_user_for_clarification
    外部 agent 循环检测到此工具被调用时，不会执行 handler，
    直接将 question 返回给用户并中止自动生成。
    """
    question = args.get("question", "需要您提供更多信息。")
    return question


# ===== spawn_subagent =====
def _exec_spawn_subagent(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: spawn_subagent
    将子任务派发给后台 sub-agent 执行。
    sub-agent 完成后结果会自动注入当前对话。
    适用于需要独立搜索/计算/比较的任务。
    """
    task = (args.get("task") or "").strip()
    if not task:
        return "(未提供 task 参数)"

    # 从 ctx 中获取 subagent_manager
    mgr = getattr(ctx, "subagent_manager", None)
    if not mgr:
        return "(子 Agent 管理器不可用)"

    # 获取可用的工具列表（可选）
    allowed_tools = args.get("allowed_tools") or []

    task_id = mgr.spawn(
        task=task,
        session_id=ctx.session_id or "",
        label=task[:20],
        tools=allowed_tools,
    )

    return f"(子任务已派发: {task_id}，完成后结果将自动注入)"
