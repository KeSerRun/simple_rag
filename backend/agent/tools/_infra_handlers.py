"""基础设施工具 handlers: 虚拟工具 / 辅助函数等。
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
