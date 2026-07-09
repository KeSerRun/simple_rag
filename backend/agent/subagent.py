"""子 Agent 系统：后台并行任务执行与结果注入。

基于 nanobot 的 SubagentManager 模式，适配同步架构。
使用 threading.Thread + queue.Queue 替代 asyncio。

流程:
  1. 主 agent 调用 spawn() 创建子任务
  2. 子任务在独立线程中运行（隔离的 ToolRegistry）
  3. 完成时将结果注入主 session 的消息队列
  4. 主 agent 在下次迭代前检测到注入结果并处理
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from queue import Queue, Empty
from typing import Any, Callable, Optional

from base.logger import logger
from .tools.registry import ToolRegistry, ToolContext, ToolDef
from .tools import registry as main_registry


class SubagentResult:
    """子 Agent 执行结果。"""
    def __init__(self, task_id: str, session_id: str, content: str,
                 success: bool = True, error: str = ""):
        self.task_id = task_id
        self.session_id = session_id
        self.content = content
        self.success = success
        self.error = error


class SubagentManager:
    """子 Agent 管理器。

    管理后台子任务的创建、跟踪和结果注入。
    """

    def __init__(self, max_concurrent: int = 4):
        self._max_concurrent = max_concurrent
        self._running: dict[str, threading.Thread] = {}
        self._status: dict[str, dict] = {}
        self._session_tasks: dict[str, list[str]] = {}
        self._results: dict[str, SubagentResult] = {}
        self._lock = threading.Lock()

    def spawn(
        self,
        task: str,
        session_id: str,
        label: str = "",
        tools: Optional[list[str]] = None,
    ) -> str:
        """创建子 Agent 任务。

        参数:
            task: 子任务的 prompt
            session_id: 所属会话 ID
            label: 任务标签（用于日志）
            tools: 允许子 agent 使用的工具列表（None=全部）

        返回:
            task_id: 任务 ID
        """
        task_id = "sub_" + uuid.uuid4().hex[:8]

        with self._lock:
            self._status[task_id] = {
                "task": task[:60],
                "label": label or task[:20],
                "session_id": session_id,
                "status": "running",
                "started_at": None,
            }
            self._session_tasks.setdefault(session_id, []).append(task_id)

        # 启动后台线程
        t = threading.Thread(
            target=self._run,
            args=(task_id, task, session_id, tools or []),
            daemon=True,
        )
        t.start()

        with self._lock:
            self._running[task_id] = t
            self._status[task_id]["started_at"] = time.time()

        logger.info(f"子 Agent 已启动: {task_id} label={label} session={session_id[:8]}")
        return task_id

    def _run(
        self, task_id: str, task: str,
        session_id: str, allowed_tools: list[str],
    ):
        """子 Agent 执行体（在后台线程中运行）。"""
        try:
            # 精简的系统提示
            prompt = (
                "你是一个子任务助手。请只专注于完成分配给你的子任务，"
                "不要提问，直接输出结果。\n\n"
                f"子任务: {task}"
            )

            # 限制工具集
            from .tools import registry as reg
            from .tools.registry import ToolContext as TC
            from base.config import conf
            from rag.llm_client import OpenAIClient

            client = OpenAIClient(
                api_key=conf.openai_api_key,
                base_url=conf.openai_base_url,
            )

            messages = [{"role": "system", "content": prompt}]
            messages.append({"role": "user", "content": task})

            # 限制工具集
            tools = [s for s in reg.schemas if s["function"]["name"] in allowed_tools] if allowed_tools else reg.schemas

            result_text = ""
            max_iter = 3
            for _ in range(max_iter):
                resp = client.chat_with_tools(
                    messages=messages,
                    model=conf.chat_model,
                    tools=tools,
                    tool_choice="auto",
                    stream=False,
                    temperature=0.5,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )

                if not resp["tool_calls"]:
                    result_text = resp["content"] or ""
                    break

                # 执行允许的工具
                for tc in resp["tool_calls"]:
                    tool_name = tc.get("name", "")
                    if allowed_tools and tool_name not in allowed_tools:
                        result_text += f"\n[工具 {tool_name} 不在允许列表中]"
                        continue
                    try:
                        result = reg.dispatch(
                            tool_name, tc.get("arguments", "{}"),
                            ctx=TC(vector_store=None, partition=session_id),
                        )
                    except Exception as e:
                        result = f"(工具执行失败: {e})"
                    messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})

            # 记录结果
            result_obj = SubagentResult(
                task_id=task_id,
                session_id=session_id,
                content=result_text,
                success=True,
            )

        except Exception as e:
            logger.error(f"子 Agent 执行失败 {task_id}: {e}")
            result_obj = SubagentResult(
                task_id=task_id,
                session_id=session_id,
                content=f"",
                success=False,
                error=str(e),
            )

        with self._lock:
            self._results[task_id] = result_obj
            self._status[task_id]["status"] = "completed"

        logger.info(f"子 Agent 完成: {task_id} success={result_obj.success}")

    def drain_results(self, session_id: str, max_count: int = 5) -> list[SubagentResult]:
        """获取指定会话的所有已完成子 agent 结果。"""
        results = []
        with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            for tid in task_ids:
                if len(results) >= max_count:
                    break
                if tid in self._results:
                    results.append(self._results.pop(tid))
        return results

    def get_running_count(self, session_id: str) -> int:
        """获取指定会话正在运行的子 agent 数量。"""
        with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            return sum(
                1 for tid in task_ids
                if self._status.get(tid, {}).get("status") == "running"
            )

    def cancel_session(self, session_id: str) -> int:
        """取消指定会话的所有正在运行的子 agent。"""
        cancelled = 0
        with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            for tid in task_ids:
                status = self._status.get(tid, {})
                if status.get("status") == "running":
                    thread = self._running.get(tid)
                    if thread and thread.is_alive():
                        # 无法强制终止 threading 线程，标记取消
                        self._status[tid]["status"] = "cancelled"
                        cancelled += 1
        return cancelled
