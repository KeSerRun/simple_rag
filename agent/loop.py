"""RAG agent: tool-calling 循环驱动 LLM 自主决策检索、拆解查询、生成最终答案。

流程:
  1. 构建 system message（身份 + 时间 + 风格 + 工作流 + 目标）
  2. 组装 messages: [system, ...history, user(query)]
  3. LLM 决定是否调工具 → 工具结果回灌 messages（循环）
  4. 无更多工具调用 → 输出最终答案

AgentState 封装循环中的 messages / 轮次 / 上下文参数。
"""

import os
from typing import Callable, Optional, List
from datetime import datetime as _dt
import time as _time

from base.config import conf
from base.logger import logger, log_llm_input

from rag.vector_store import VectorStore
from base.llm_client import OpenAIClient

from .tools.registry import ToolContext
from .tools import registry
from .context import SkillLoader, WorkflowRouter
from .state import AgentState
from .tools._infra_handlers import _get_goal_line

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 工具循环 ──
class ToolLoop:
    """RAG 系统核心入口，管理 LLM 客户端、向量库、工具注册表和工作流路由。

    整体流程:
      generate_answer(query)
        └─ _build_system_message()    → system prompt（身份 + 时间 + 风格）
        └─ Workflow 注入              → 指定工作流或 Auto 摘要
        └─ AgentState 初始化          → 封装 messages、分区、迭代限制
        └─ _run_tool_loop()           → 非流式：工具循环直到 LLM 不再调用工具
           └─ 循环内：LLM → tool_calls → 并发执行 → 结果回灌 → 重复
           └─ 达上限时：返回提示文本，由用户决定如何继续
        └─ _run_tool_loop_stream()    → 流式：同上 + 逐 token yield + status 事件
    """

    def __init__(
        self,
        chat_client: OpenAIClient,
        embed_client: OpenAIClient,
        data_store: Optional[object] = None,
        vector_store: VectorStore = None,
    ):
        """初始化 RAGSystem 实例。

        创建 LLM 客户端、向量库、上下文构建器和工作流路由器。
        所有模型配置直接从全局配置读取。

        Args:
            chat_client: 对话客户端实例。
            embed_client: 词嵌入客户端实例。
            data_store: 数据存储实例。
            vector_store: 向量库实例。
        """
        self.chat_client = chat_client
        self.embed_client = embed_client
        self.data_store = data_store
        self.vector_store = vector_store
        self.skill_loader = SkillLoader(os.path.join(_BACKEND_ROOT, "prompts", "style"))
        self.workflow_router = WorkflowRouter(os.path.join(_BACKEND_ROOT, "prompts", "workflow"))
        self.chat_model = conf.chat_model

    def _build_system_message(
        self,
        style: Optional[str] = None,
        workflow_name: Optional[str] = None,
    ) -> str:
        """构造 system message: identity + 可选回答风格 + 可选工作流。

        Args:
            style: 回答风格模板名称。
            workflow_name: 工作流名称，None 或 "__auto__" 时加载摘要列表。

        Returns:
            拼接后的 system message 字符串。
        """
        parts = [self.skill_loader.identity or ""]

        _tz = _time.tzname
        parts.append(f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} (时区: {_tz[0] if _tz else 'UTC'})")

        if style and style != "style-default":
            skill = self.skill_loader.skills.get(style)
            if skill and skill.template:
                parts.append(f"\n\n{skill.template}")

        wf_name = workflow_name if workflow_name and workflow_name != "__auto__" else None
        if wf_name:
            wf_content = self.workflow_router.get_workflow_content(wf_name)
            if wf_content:
                parts.append(f"\n\n---\n# 工作流: {wf_name}\n{wf_content}")
                logger.info(f"工作流已加载: {wf_name}")
            else:
                logger.warning(f"工作流 '{wf_name}' 未找到")
        else:
            wf_summaries = self.workflow_router.get_workflow_summaries()
            if wf_summaries:
                parts.append(
                    f"\n\n---\n# 工作流\n"
                    f"{wf_summaries}\n"
                    f"如需加载完整工作流指令，请调用 read_workflow 工具。"
                )
        return "".join(parts)


    def generate_answer(
        self, query,
        stream=False,
        history: list = None,
        partition: str = None,
        session_id: str = "default",
        style: Optional[str] = None,
        workflow_name: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        emit_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        """生成答案的顶层入口。

        核心流程：
          1. 构建 system message（身份 + 时间 + 风格 + 工作流）
          2. 组装 messages（system + history + query）
          3. 根据 stream 参数选择 _run_tool_loop 或 _run_tool_loop_stream

        Args:
            query: 用户当前问题。
            stream: 是否启用流式输出。
            history: 历史对话列表。
            partition: 知识库分区（用户名）。
            session_id: 会话 ID。
            style: 回答风格模板名称。
            workflow_name: 工作流名称（None 为自动识别）。
            cancel_check: 可选的中断检测函数，返回 True 时中断生成。
            emit_event: 事件推送回调（用于流式输出）。

        Returns:
            非流式模式返回答案字符串；流式模式返回生成器对象。
        """
        conf.reload_if_changed()
        from .tools import registry as _reg
        _reg.reset_external_lookup_counts()
        logger.debug(f"收到用户查询: {query} (style={style})")

        system_msg = self._build_system_message(
            style=style,
            workflow_name=workflow_name
        )

        goal_line = _get_goal_line(session_id, self.data_store)
        if goal_line:
            system_msg += goal_line
            logger.debug(f"注入活跃目标: session={session_id[:8]}")

        logger.debug(f"system_msg 长度: {len(system_msg)} 字符")
        
        messages: List[dict] = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        max_iter = conf.max_tool_iter

        # 初始化状态机
        state = AgentState(
            messages=messages,
            partition=partition,
            session_id=session_id,
            style=style,
            workflow=workflow_name,
            max_iterations=max_iter,
        )
        _save_start = len(state.messages) - 1

        if stream:
            return self._run_stream(
                state,
                cancel_check=cancel_check,
                emit_event=emit_event,
                save_start=_save_start,
            )

        return self._run(state, system_msg, save_start=_save_start)


    # ── 对话历史持久化 ──

    def _save_turn_messages(self, session_id: str, messages: list, start: int = 0) -> None:
        """保存本轮完整消息序列（含工具调用和结果）到历史记录。

        跳过 system 消息（由后续回合重建）和 start 之前的消息（已持久化的历史），
        只保存本轮新增的 user / assistant / tool 消息。

        Args:
            session_id: 会话 ID。
            messages: 完整消息列表。
            data_store: 数据存储实例。
            start: 本轮起始索引，之前的消息被视为已持久化的历史。
        """
        if self.data_store is None:
            return
        try:
            turn_msgs = [m for m in messages[start:] if m.get("role") != "system"]
            if not turn_msgs:
                return
            self.data_store.insert_session_turn(session_id, turn_msgs)
            logger.debug(f"已保存完整对话回合: session={session_id[:8]}, {len(turn_msgs)} 条消息")
        except Exception as e:
            logger.warning(f"保存完整对话回合失败: {e}")

    # ── 非流式工具循环 ──

    def _run(self, state: AgentState, save_start: int = 0) -> str:
        """非流式工具调用主循环。

        循环逻辑（LLM 驱动的工具调用循环）：
          1. LLM 收到完整的 messages（含历史和之前的工具结果）
          2. LLM 决定调用哪些工具 → 返回 tool_calls 列表
          3. 如果 tool_calls 为空：LLM 已准备好最终答案，直接返回
          4. 如果 tool_calls 包含 ask_user_for_clarification：提前终止，返回澄清问题
          5. 否则：并发执行所有工具调用（ThreadPoolExecutor），结果写回 state.messages
          6. 回到步骤 1，直到达到 max_iterations

        Args:
            state: AgentState 实例，包含 messages、partition、session_id 等。
            system_msg: system message 内容。
            data_store: 数据存储实例。
            save_start: 本轮消息起始索引。

        Returns:
            LLM 生成的最终答案字符串，或达到上限时的提示文本。
        """
        tool_choice = "auto"
        _empty_retries = 0
        _length_retries = 0

        while state.should_continue():

            truncated_messages = state.messages

            log_llm_input(truncated_messages, round=state.iteration, suffix="_sent")

            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"非流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:
                resp = self.chat_client.chat_with_tools(
                    messages=truncated_messages,
                    model=self.chat_model,
                    tools=registry.schemas,
                    tool_choice=tool_choice,
                    stream=False,
                    temperature=0.7,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.iteration}): {e}")
                return "抱歉，模型处理请求时发生了错误。"

            if not resp["tool_calls"]:
                content = (resp.get("content") or "").strip()
                if not content:
                    retries = _empty_retries
                    if retries < 2:
                        _empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({_empty_retries}/2)")
                        state.add_user_query("请直接回答用户的问题，不要使用工具。")
                        continue
                length_retries = _length_retries
                if resp.get("finish_reason") == "length" and content and length_retries < 3:
                    _length_retries = length_retries + 1
                    logger.warning(f"LLM 响应被截断 (length), 自动续写 ({_length_retries}/3)")
                    state.messages.append({"role": "assistant", "content": content})
                    state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                    continue
                state.add_assistant_response(content)
                self._save_turn_messages(state.session_id, state.messages, start=save_start)
                return content

            logger.debug(f"tool-loop {state.iteration} LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            import concurrent.futures

            def _dispatch_task(tc):
                try:
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                            session_id=state.session_id,
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    logger.debug(f"工具 {tc['name']} 完成: result_len={len(res)} chars")
                    return tc["id"], res
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 执行发生严重异常: {e}", exc_info=True)
                    return tc["id"], f"(系统提示: 执行工具 {tc['name']} 时发生了严重错误: {e}，请尝试使用其他工具或根据现有信息回答)"

            from .tools.registry import ToolRegistry
            batches = ToolRegistry.partition_tool_batches(resp["tool_calls"])
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(resp["tool_calls"])
            ) as executor:
                for batch in batches:
                    futures = [executor.submit(_dispatch_task, tc) for tc in batch]
                    for future in concurrent.futures.as_completed(futures):
                        tc_id, result = future.result()
                        state.add_tool_result(tc_id, result)

            for tc in resp["tool_calls"]:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except Exception:
                        q = "我需要您提供更多背景信息。"
                    logger.debug("提前中断工具循环：LLM 需要澄清")
                    return q

            tool_choice = "auto"

        logger.warning(f"tool-loop 达到上限 {state.max_iterations}")
        return "已达单次工具调用上限，如已有足够信息可直接给出最终答案。"


    # ── 流式工具循环 ──

    def _run_stream(self, state: AgentState,
                               cancel_check: Optional[Callable[[], bool]] = None,
                               emit_event: Optional[Callable[[dict], None]] = None,
                               save_start: int = 0):
        """流式生成器：逐 token 产出，中间穿插 status 事件。

        与非流式版本的核心逻辑相同，但：
          - 使用 Python generator（yield）逐块返回
          - 产生 "token" 事件用于前端逐字展示
          - 产生 "status" 事件用于前端显示"思考中"、"调用工具"、"工具完成"等状态

        Yields:
            事件字典，可能包含以下类型：
            - {"type": "token", "text": "..."}: 输出文本片段
            - {"type": "reasoning", "text": "..."}: 推理过程文本
            - {"type": "status", "status": "thinking"}: AI 正在思考
            - {"type": "status", "status": "calling_tool", "tool": "...", ...}: 正在调用工具
            - {"type": "status", "status": "tool_result", "tool": "...", "chunks": N}: 工具执行完成
            - {"type": "status", "status": "retrying"}: 空内容时自动重试

        Args:
            state: AgentState 实例。
            cancel_check: 中断检测函数，返回 True 时终止生成。
            emit_event: 流式事件的发送函数。
            data_store: 数据存储实例。
            save_start: 本轮消息起始索引。
        """
        tool_choice = "auto"
        _empty_retries = 0
        _length_retries = 0

        for it in range(state.max_iterations):
            if cancel_check and cancel_check():
                logger.info("工具循环被中断")
                return
        
            accumulated_content = ""
            from typing import List
            tool_calls: List[dict] = []

            if emit_event: emit_event({"type": "status", "status": "thinking"})
            yield {"type": "status", "status": "thinking"}

            truncated_messages = state.messages

            log_llm_input(truncated_messages, round=it, suffix="_sent")

            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:
                events = self.chat_client.chat_with_tools(
                    messages=truncated_messages,
                    model=self.chat_model,
                    tools=registry.schemas,
                    tool_choice=tool_choice,
                    stream=True,
                    temperature=0.7,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
                for ev in events:
                    if cancel_check and cancel_check():
                        logger.info("token流被中断")
                        return
                    if ev["type"] == "content":
                        accumulated_content += ev["text"]
                        if emit_event: emit_event({"type": "token", "text": ev["text"]})
                        yield {"type": "token", "text": ev["text"]}
                    elif ev["type"] == "reasoning":
                        if emit_event: emit_event({"type": "reasoning", "text": ev["text"]})
                        yield {"type": "reasoning", "text": ev["text"]}
                    elif ev["type"] == "tool_calls":
                        tool_calls = ev["calls"]
                    elif ev["type"] == "finish" and ev.get("reason") == "length":
                        if accumulated_content.strip():
                            lr = _length_retries
                            if lr < 3:
                                _length_retries = lr + 1
                                state.add_assistant_response(accumulated_content)
                                state.add_user_query("继续，不要重复已写过的内容。")
                                accumulated_content = ""
                                tool_choice = "auto"
            except Exception as e:
                logger.error(f"LLM tool 流式调用失败 (round {it}): {e}")
                yield {"type": "token", "text": "\n\n抱歉，模型处理请求时发生了错误。"}
                return

            if not tool_calls:
                if not accumulated_content.strip():
                    retries = _empty_retries
                    if retries < 2:
                        _empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({_empty_retries}/2)")
                        state.add_user_query("请直接回答用户的问题，不要使用工具。")
                        if emit_event: emit_event({"type": "status", "status": "retrying"})
                        yield {"type": "status", "status": "retrying"}
                        continue
                state.add_assistant_response(accumulated_content)
                self._save_turn_messages(state.session_id, state.messages, start=save_start)
                return

            logger.debug(f"tool-loop {it} LLM 请求 {len(tool_calls)} 个工具调用")
            state.add_assistant_response(accumulated_content, tool_calls)

            import concurrent.futures

            def _dispatch_task_stream(tc):
                import json as _json
                tool_info = {"tool": tc["name"]}
                try:
                    _args = _json.loads(tc.get("arguments") or "{}")
                    if "queries" in _args:
                        tool_info["query"] = _args["queries"]
                    if "filename" in _args:
                        tool_info["filename"] = _args["filename"]
                    if "query" in _args:
                        tool_info["query"] = [_args["query"]]
                except Exception:
                    pass

                try:
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                            session_id=state.session_id,
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    logger.debug(f"流式工具 {tc['name']} 完成: result_len={len(res)} chars")
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 异常: {e}", exc_info=True)
                    res = f"(系统提示: 执行工具 {tc['name']} 发生错误: {e}，请尝试其他策略)"

                return tc["id"], tool_info, res

            _tool_total = len(tool_calls)
            for _tool_idx, tc in enumerate(tool_calls, start=1):
                 import json as _json
                 tmp_info = {"tool": tc["name"], "total": _tool_total}
                 try:
                     _args = _json.loads(tc.get("arguments") or "{}")
                     if "queries" in _args:
                         tmp_info["query"] = _args["queries"]
                     if "filename" in _args:
                         tmp_info["filename"] = _args["filename"]
                     if "query" in _args:
                         tmp_info["query"] = [_args["query"]]
                 except Exception:
                     pass
                 if emit_event: emit_event({"type": "status", "status": "calling_tool", **tmp_info})
                 yield {"type": "status", "status": "calling_tool", **tmp_info}

            from .tools.registry import ToolRegistry
            batches = ToolRegistry.partition_tool_batches(tool_calls)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(tool_calls)
            ) as executor:
                for batch in batches:
                    futures = [executor.submit(_dispatch_task_stream, tc) for tc in batch]
                    for future in concurrent.futures.as_completed(futures):
                        tc_id, tool_info, result = future.result()
                        state.add_tool_result(tc_id, result)

                        import re as _re
                        if tool_info.get("tool") == "search_knowledge_base":
                            _cnt = len(_re.findall(r"【片段 \d+", result))
                            if _cnt:
                                tool_info["chunks"] = _cnt
                        elif tool_info.get("tool") == "web_search":
                            _cnt = len(_re.findall(r"\[搜索结果 \d+\]", result))
                            if _cnt:
                                tool_info["chunks"] = _cnt
                        if emit_event: emit_event({"type": "status", "status": "tool_result", **tool_info})
                        yield {"type": "status", "status": "tool_result", **tool_info}
            for tc in tool_calls:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except Exception:
                        q = "我需要您提供更多背景信息。"
                    logger.debug("流式提前中断工具循环：LLM 需要澄清")
                    yield {"type": "token", "text": "\n\n" + q}
                    return

            tool_choice = "auto"

        logger.warning(f"tool-loop 达到上限 {state.max_iterations}")
        msg = "已达单次工具调用上限，如已有足够信息可直接给出最终答案。"
        for ch in msg:
            if emit_event:
                emit_event({"type": "token", "text": ch})
            yield {"type": "token", "text": ch}
        return

