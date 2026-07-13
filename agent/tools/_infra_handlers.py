"""基础设施工具 handlers：虚拟工具 / 子 Agent / 辅助函数等。

提供 LLM agent 运行时所需的基础设施工具，包括：
  - 向用户发起澄清询问
  - 查询和修改运行时状态
  - 设置 / 完成会话持续目标
  - 读取工作流的完整分步指令
  - 读取被持久化的工具结果

注册统一在 registry.py 的 register_all_builtins() 中完成。
"""

from __future__ import annotations

import threading
from pathlib import Path

from base.config import conf
from .registry import ToolContext

# ── 便利工具：向用户询问 ──


def _exec_ask_clarification(args: dict, ctx: ToolContext) -> str:
    """向用户发起澄清询问。

    当用户请求模糊（指代不清、未指定具体文档）、且已有检索结果不足以推断时调用。
    调用后会中断对话流，将 question 抛给用户等待补充。

    Args:
        args: 工具参数字典，键:
            question: 向用户询问的具体问题（必填）。
        ctx: 工具运行时上下文。

    Returns:
        用户需要看到的询问文本。
    """
    question = args.get("question", "需要您提供更多信息。")
    return question


# ── 运行时状态查询 ──


def _exec_my(args: dict, ctx: ToolContext) -> str:
    """查询运行时状态和配置项。

    支持查看完整状态概览、特定配置项、以及子 Agent 列表。
    由 LLM 在需要了解自身运行环境时调用。

    Args:
        args: 工具参数字典，键:
            action: 操作类型 — 'check'（查看状态）。
            key: 要查看的特定配置项关键词（可选）。
        ctx: 工具运行时上下文。

    Returns:
        格式化的状态文本或错误提示。
    """
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

    return "(未知 action)"


# ── 会话目标管理 ──

_GOAL_KEY = "_goals"
_GOAL_CACHE: dict[str, dict] = {}


def _exec_set_goal(args: dict, ctx: ToolContext) -> str:
    """设置会话持续目标，通过 data_store 持久化。

    当用户交代了一个多轮对话才能完成的目标时调用。
    目标信息会持续注入 system prompt 供后续对话参考。

    Args:
        args: 工具参数字典，键:
            goal: 目标的详细描述（必填）。
        ctx: 工具运行时上下文。

    Returns:
        操作结果提示字符串。
    """
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
    """完成当前目标。

    当用户确认目标已完成时调用。将活跃目标标记为 'completed' 状态。

    Args:
        args: 工具参数字典（本工具无需额外参数）。
        ctx: 工具运行时上下文。

    Returns:
        操作结果提示字符串。
    """
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
    """读取当前活跃目标文本，优先走内存缓存。

    用于组装 system prompt 中的目标信息行。
    缓存未命中时回退到 data_store 查询，查到后写入缓存。

    Args:
        sid: 会话 ID。
        data_store: 持久化数据存储对象。

    Returns:
        格式如 '\\n当前目标：xxx' 的字符串，无活跃目标时返回空字符串。
    """
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


# ── 工作流读取 ──


def _exec_read_workflow(args: dict, ctx: ToolContext) -> str:
    """读取工作流的完整分步指令。

    system prompt 中列出了可用的工作流及其摘要。
    如需使用某个工作流，先调用此工具获取完整指令，再按步骤执行。

    Args:
        args: 工具参数字典，键:
            name: 工作流名称，如 USstocks、Autoplan、DeepResearch（必填）。
        ctx: 工具运行时上下文。

    Returns:
        工作流完整指令文本，或错误提示。
    """
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


# ── 持久化工具结果读取 ──


def _exec_read_tool_result(args: dict, ctx: ToolContext) -> str:
    """读取被持久化的工具结果完整内容，支持 offset 分页。

    当工具返回 "[工具结果已保存至 ...]" 引用时，调用此工具传入文件名读取原始内容。

    Args:
        args: 工具参数字典，键:
            filename: 持久化结果的文件名，不含路径（必填）。
            offset: 字符偏移位置，用于分页读取（可选，默认 0）。
        ctx: 工具运行时上下文。

    Returns:
        文件内容（分页截取后的文本），末尾附分页提示。
    """
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
