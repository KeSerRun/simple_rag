"""基础设施工具 handlers: 虚拟工具 / 子 Agent / 辅助函数等。
注册统一在 registry.py 的 register_all_builtins() 中。
"""
from __future__ import annotations

import threading
from pathlib import Path

from base.config import conf
from .registry import ToolContext


# ===== 简单目标存储（模块级 dict，由 IntegratedSystem 读取） =====
_GOALS: dict[str, dict] = {}
_GOALS_LOCK = threading.Lock()


def _set_goal(session_id: str, goal: str):
    with _GOALS_LOCK:
        _GOALS[session_id] = {"goal": goal, "status": "active"}


def _complete_goal(session_id: str):
    with _GOALS_LOCK:
        _GOALS[session_id] = {"goal": "", "status": "completed"}


def _get_goal_line(session_id: str) -> str:
    with _GOALS_LOCK:
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

        return "\n".join(lines)

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

    elif action == "subagents":
        mgr = getattr(ctx, "subagent_manager", None)
        if not mgr:
            return "(子 Agent 管理器不可用)"
        import time as _time
        lines = ["=== 子 Agent 列表 ==="]
        with mgr._lock:
            statuses = dict(mgr._status)

# ===== read_workflow（渐进式加载工作流） =====
def _exec_read_workflow(args: dict, ctx: ToolContext) -> str:
    """读取工作流的完整分步指令。"""
    name = (args.get("name") or "").strip()
    if not name:
        return "(未提供 name 参数)"
    router = getattr(ctx, "workflow_router", None)
    if not router:
        return "(工作流路由器不可用)"
    content = router.get_workflow_content(name)
    if not content:
        return f"(未找到工作流: {name})"
    return f"工作流：{name}\n\n{content}"


# ===== read_tool_result =====
def _exec_read_tool_result(args: dict, ctx: ToolContext) -> str:
    """读取被持久化的工具结果完整内容。支持 offset 分段读取。"""
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    base = Path(conf.data_dir) / "json_store" / "tool_results"
    target = None

    # 先在根目录找
    try:
        t = (base / filename).resolve()
        t.relative_to(base.resolve())
        if t.is_file():
            target = t
    except (ValueError, OSError):
        pass

    # 没找到时搜索 session 子目录
    if target is None:
        for session_dir in base.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                t = (session_dir / filename).resolve()
                t.relative_to(session_dir.resolve())
                if t.is_file():
                    target = t
                    break
            except (ValueError, OSError):
                continue

    if target is None:
        return f"(文件不存在: {filename})"

    try:
        content = target.read_text(encoding="utf-8")
        total = len(content)
        offset = max(int(args.get("offset", 0)), 0)
        max_chars = conf.tool_page_chars
        chunk = content[offset:offset + max_chars]
        part_info = ""
        if total > max_chars:
            end = offset + len(chunk)
            if end < total:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符。调用 offset={end} 继续读取)"
            else:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符 — 已到末尾)"
        return chunk + part_info
    except Exception as e:
        return f"(读取失败: {e})"
