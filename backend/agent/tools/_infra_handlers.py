"""基础设施工具 handlers: 虚拟工具 / 子 Agent / 辅助函数等。
注册统一在 registry.py 的 register_all_builtins() 中。
"""
from __future__ import annotations

from .registry import ToolContext


# ===== 简单目标存储（模块级 dict，由 IntegratedSystem 读取） =====
_GOALS: dict[str, dict] = {}


def _set_goal(session_id: str, goal: str):
    _GOALS[session_id] = {"goal": goal, "status": "active"}


def _complete_goal(session_id: str):
    _GOALS[session_id] = {"goal": "", "status": "completed"}


def _get_goal_line(session_id: str) -> str:
    data = _GOALS.get(session_id)
    if data and data.get("status") == "active" and data.get("goal"):
        return f"\n当前目标：{data['goal']}"
    return ""


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

    mgr = getattr(ctx, "subagent_manager", None)
    if not mgr:
        return "(子 Agent 管理器不可用)"

    allowed_tools = args.get("allowed_tools") or []
    task_id = mgr.spawn(
        task=task,
        session_id=ctx.session_id or "",
        label=task[:20],
        tools=allowed_tools,
    )
    return f"(子任务已派发: {task_id}，完成后结果将自动注入)"


# ===== set_goal =====
def _exec_set_goal(args: dict, ctx: ToolContext) -> str:
    """设置会话的持续目标。目标信息会持续注入 system prompt。"""
    goal = (args.get("goal") or "").strip()
    if not goal:
        return "(未提供 goal 参数)"
    _set_goal(ctx.session_id or "", goal)
    return f"(目标已设置：{goal})"


# ===== complete_goal =====
def _exec_complete_goal(args: dict, ctx: ToolContext) -> str:
    """完成当前目标。"""
    _complete_goal(ctx.session_id or "")
    return "(当前目标已完成)"


# ===== my（内省工具，类比 nanobot MyTool） =====
def _exec_my(args: dict, ctx: ToolContext) -> str:
    """查看当前会话的运行时状态和配置。"""
    action = args.get("action", "check")
    key = args.get("key", "")

    from base.config import conf
    from . import registry

    if action == "check" and not key:
        lines = ["=== 当前状态 ==="]
        lines.append(f"模型: {conf.chat_model}")
        lines.append(f"最大迭代: {conf.max_tool_iter}")
        lines.append(f"上下文窗口: {conf.context_window_tokens}")
        lines.append(f"输出 Token 上限: {conf.max_output_tokens}")
        lines.append(f"检索 Top-K: {conf.retrieval_top_k}")
        lines.append(f"搜索后端: {conf.search_backend}")
        lines.append("")

        counts = dict(registry.call_counts)
        if counts:
            lines.append("=== 工具调用统计 ===")
            for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {cnt}")

        goal = _get_goal_line(ctx.session_id or "")
        if goal:
            lines.append("")
            lines.append(f"目标: {goal.strip()}")

        return "\\n".join(lines)

    elif action == "check" and key:
        key_map = {
            "model": ("chat_model", conf.chat_model),
            "max_iterations": ("max_tool_iter", conf.max_tool_iter),
            "context_window": ("context_window_tokens", conf.context_window_tokens),
            "max_tokens": ("max_output_tokens", conf.max_output_tokens),
            "retrieval_top_k": ("retrieval_top_k", conf.retrieval_top_k),
        }
        if key in key_map:
            name, val = key_map[key]
            return f"{name}: {val}"
        return f"(未知配置: {key})"

    return "(未知 action)"
