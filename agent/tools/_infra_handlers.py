"""基础设施工具 handlers: 虚拟工具 / 子 Agent / 辅助函数等。
注册统一在 registry.py 的 register_all_builtins() 中。
"""
from __future__ import annotations

import threading
from pathlib import Path

from base.config import conf
from .registry import ToolContext

# ===== ask_user_for_clarification（虚拟工具） =====
def _exec_ask_clarification(args: dict, ctx: ToolContext) -> str:
    question = args.get("question", "需要您提供更多信息。")
    return question

# ===== my（内省工具，类比 nanobot MyTool） =====
def _exec_my(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "check")
    key = args.get("key", "")

    from base.config import conf
    from . import registry

    if action == "check" and not key:
        lines = ["=== 当前状态 ==="]
        lines.append(f"模型: {conf.chat_model}")
        lines.append(f"最大迭代: {conf.max_tool_iter}")
        lines.append(f"上下文窗口: {conf.context_window_chars} 字符")
        lines.append(f"输出字符上限: {conf.max_output_chars}")
        lines.append(f"检索 Top-K: {conf.retrieval_top_k}")
        lines.append(f"搜索后端: {conf.search_backend}")
        lines.append("")

        counts = dict(registry.call_counts)
        if counts:
            lines.append("=== 工具调用统计 ===")
            for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {cnt}")

        return "\n".join(lines)

    elif action == "check" and key:
        key_map = {
            "model": ("chat_model", conf.chat_model),
            "max_iterations": ("max_tool_iter", conf.max_tool_iter),
            "context_window": ("context_window_chars", conf.context_window_chars),
            "max_tokens": ("max_output_chars", conf.max_output_chars),
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

    return "(未知 action)"

# ===== set_goal =====
_GOAL_KEY = "_goals"
_GOAL_CACHE: dict[str, dict] = {}  # 内存缓存,避免每次读文件


def _exec_set_goal(args: dict, ctx: ToolContext) -> str:
    """设置会话持续目标，通过 data_store 持久化。"""
    goal = (args.get("goal") or "").strip()
    if not goal:
        return "(未提供 goal 参数)"
    sid = ctx.session_id or ""
    entry = {"goal": goal, "status": "active"}
    _GOAL_CACHE[sid] = entry
    if ctx.data_store:
        tasks = ctx.data_store.get_session_tasks(sid) or {}
        goals = tasks.get(_GOAL_KEY, {})
        goals[sid] = entry
        tasks[_GOAL_KEY] = goals
        ctx.data_store.save_session_tasks(sid, tasks)
    return f"(目标已设置：{goal})"


def _exec_complete_goal(args: dict, ctx: ToolContext) -> str:
    """完成当前目标。"""
    sid = ctx.session_id or ""
    if sid in _GOAL_CACHE:
        _GOAL_CACHE[sid]["status"] = "completed"
    if ctx.data_store:
        tasks = ctx.data_store.get_session_tasks(sid) or {}
        goals = tasks.get(_GOAL_KEY, {})
        if sid in goals:
            goals[sid] = {"goal": "", "status": "completed"}
            tasks[_GOAL_KEY] = goals
            ctx.data_store.save_session_tasks(sid, tasks)
    return "(当前目标已完成)"


def _get_goal_line(sid: str, data_store) -> str:
    """读取当前活跃目标文本（优先走内存缓存）。"""
    if sid in _GOAL_CACHE:
        g = _GOAL_CACHE[sid]
        if g.get("status") == "active" and g.get("goal"):
            return f"\n当前目标：{g['goal']}"
    if not data_store or not sid:
        return ""
    try:
        tasks = data_store.get_session_tasks(sid) or {}
        goals = tasks.get(_GOAL_KEY, {})
        g = goals.get(sid)
        if g and g.get("status") == "active" and g.get("goal"):
            _GOAL_CACHE[sid] = g
            return f"\n当前目标：{g['goal']}"
    except Exception:
        pass
    return ""

# ===== read_workflow（渐进式加载工作流） =====
def _exec_read_workflow(args: dict, ctx: ToolContext) -> str:
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
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    base = Path(conf.data_dir) / "json_store" / "tool_results"
    target = None

    try:
        t = (base / filename).resolve()
        t.relative_to(base.resolve())
        if t.is_file():
            target = t
    except (ValueError, OSError):
        pass

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

# ===== 内省工具：my（查看状态）、ask_user_for_clarification（向用户追问） =====

# ===== 目标管理：set_goal / complete_goal（通过 data_store 持久化） =====

# ===== 工作流读取：read_workflow（渐进式加载完整指令） =====

# ===== 工具结果追溯：read_tool_result（分段读取持久化的工具输出） =====
