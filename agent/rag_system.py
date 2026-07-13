"""RAG agent: tool-calling 循环驱动 LLM 自主决策检索、拆解查询、生成最终答案。

流程:
  1. 构建 system message（身份 + 时间 + 风格 + 工作流 + 目标）
  2. 组装 messages: [system, ...history, user(query)]
  3. LLM 决定是否调工具 → 工具结果回灌 messages（循环）
  4. 无更多工具调用 → 输出最终答案

AgentState 封装循环中的 messages / 轮次 / 上下文参数。
"""
import hashlib
import json
import os
import threading
from pathlib import Path

from typing import Callable, List, Optional

from base.config import conf
from base.logger import logger, log_llm_input

from rag.vector_store import VectorStore
from base.llm_client import OpenAIClient

from .context_builder import ContextBuilder
from .state import AgentState
from .tools.registry import ToolContext
from .tools import registry
from .workflow import WorkflowRouter

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))





# ── 内部辅助函数 ──


def _count_message_chars(m: dict) -> int:
    """返回一条消息的字符数。

    Args:
        m: 消息字典，包含 "content" 键。

    Returns:
        消息内容的字符数。
    """
    content = m.get("content", "") or ""
    return len(content) if isinstance(content, str) else len(str(content))



_TOOL_RESULTS_DIR = Path("json_store") / "tool_results"


def _persist_tool_result(session_id: str, tool_name: str, content: str) -> str:
    """将过长的工具结果写入文件，返回引用字符串。

    当内容长度超过 conf.persist_threshold 时，将其写入磁盘文件，
    返回包含文件路径和预览的引用文本。保留最近 50 个文件。

    Args:
        session_id: 会话 ID，用于隔离存储目录。
        tool_name: 工具名称，用于文件名标识。
        content: 工具结果内容。

    Returns:
        原始内容（未超限时）或包含文件路径和预览的引用文本。
    """
    if len(content) <= conf.persist_threshold:
        return content

    try:
        work_dir = Path(conf.data_dir) / _TOOL_RESULTS_DIR / (session_id or "default")
        work_dir.mkdir(parents=True, exist_ok=True)

        digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        path = work_dir / f"{tool_name}_{digest}.txt"

        if not path.exists():
            path.write_text(content, encoding="utf-8")
            files = sorted(work_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[50:]:
                old.unlink(missing_ok=True)

        preview = content[:conf.preview_chars].replace("\n", " ")
        reference = (
            f"[工具结果已保存至 {path}]\n"
            f"原始长度: {len(content)} 字符, 预览: {preview}..."
        )
        logger.debug(f"工具结果持久化: {tool_name} ({len(content)} chars → {path.name})")
        return reference
    except Exception as e:
        logger.warning(f"工具结果持久化失败: {e}, 返回原始内容")
        return content


# ── RAG 系统核心 ──


class RAGSystem:
    """RAG 系统核心入口，管理 LLM 客户端、向量库、工具注册表和工作流路由。

    整体流程:
      generate_answer(query)
        └─ _build_system_message()    → system prompt（身份 + 时间 + 风格）
        └─ Workflow 注入              → 指定工作流或 Auto 摘要
        └─ AgentState 初始化          → 封装 messages、分区、迭代限制
        └─ _run_tool_loop()           → 非流式：工具循环直到 LLM 不再调用工具
           └─ 循环内：LLM → tool_calls → 并发执行 → 结果回灌 → 重复
           └─ 达上限时：保存中断状态，用户可回复「继续」恢复
        └─ _run_tool_loop_stream()    → 流式：同上 + 逐 token yield + status 事件
    """

    def __init__(
        self,
        chat_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        prompts_dir: Optional[str] = None,
        prompts_dirs: Optional[List[str]] = None,
        data_store: Optional[object] = None,
    ):
        """初始化 RAGSystem 实例。

        创建 LLM 客户端、向量库、上下文构建器和工作流路由器。
        支持嵌入客户端与聊天客户端共用或独立配置。

        Args:
            chat_model: 聊天模型名称，默认使用配置中的 chat_model。
            embedding_model: 嵌入模型名称，默认使用配置中的 openai_embedding_model。
            embedding_dim: 嵌入向量维度，默认使用配置中的 openai_embedding_dim。
            prompts_dir: 提示词模板目录（单个），与 prompts_dirs 二选一。
            prompts_dirs: 提示词模板目录列表，与 prompts_dir 二选一。
            data_store: 数据存储实例，用于持久化对话和工具状态。
        """
        self.chat_model = chat_model or conf.chat_model
        self.embedding_model = embedding_model or conf.openai_embedding_model
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim
        self.data_store = data_store

        if prompts_dirs:
            dirs = prompts_dirs
        elif prompts_dir:
            dirs = [prompts_dir]
        else:
            dirs = [
                os.path.join(_BACKEND_ROOT, "prompts"),
                os.path.join(_BACKEND_ROOT, "prompts", "style"),
            ]
        self.context_builder = ContextBuilder(dirs)

        self.client = OpenAIClient(
            api_key=conf.openai_api_key,
            base_url=conf.openai_base_url,
            timeout=conf.openai_timeout,
            max_retries=conf.openai_max_retries,
        )

        if conf.embedding_api_key == conf.openai_api_key and conf.embedding_base_url == conf.openai_base_url:
            self.embed_client = self.client
            logger.debug("Embedding 端与 chat 端共用同一 OpenAI 客户端")
        else:
            self.embed_client = OpenAIClient(
                api_key=conf.embedding_api_key,
                base_url=conf.embedding_base_url,
                timeout=conf.openai_timeout,
                max_retries=conf.openai_max_retries,
            )
            logger.debug(f"Embedding 端使用独立客户端: base_url={conf.embedding_base_url}")

        self.vector_store = VectorStore(
            client=self.embed_client,
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
        )

        self.workflow_router = WorkflowRouter(
            os.path.join(_BACKEND_ROOT, "prompts")
        )

        logger.info(
            f"RAG agent 就绪, chat_model={self.chat_model}, "
            f"工具={[t['function']['name'] for t in registry.schemas]}"
        )

        if conf.mineru_api_key:
            tok_preview = f"{conf.mineru_api_key[:12]}...({conf.mineru_token_name})"
            logger.debug(f"PDF 解析: MinerU {conf.mineru_model_version}/{conf.mineru_language} token={tok_preview}")
        else:
            logger.debug("PDF 解析: OCRPDFLoader (MinerU token 未配置)")


    def _build_system_message(
        self,
        style: Optional[str] = None,
    ) -> str:
        """构造 system message: identity + 可选回答风格。

        style 为 None / "style-default" 时跳过风格注入。
        文档清单不再注入 system message，LLM 通过 list_documents 工具按需获取。

        Args:
            style: 回答风格模板名称。None 或 "style-default" 时跳过风格注入。

        Returns:
            拼接后的 system message 字符串。
        """
        parts = [self.context_builder.identity or ""]

        from datetime import datetime as _dt
        import time as _time
        _tz = _time.tzname
        parts.append(f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} (时区: {_tz[0] if _tz else 'UTC'})")


        if style and style != "style-default":
            skill = self.context_builder.skills.get(style)
            if skill and skill.template:
                parts.append(f"\n\n{skill.template}")
        return "".join(parts)


    def generate_answer(
        self, query,
        force_retrieve: bool = False,
        stream=False,
        history: list = None,
        partition: str = None,
        session_id: str = "default",
        style: Optional[str] = None,
        workflow_name: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_checkpoint: Optional[Callable[[str, dict], None]] = None,
        emit_event: Optional[Callable[[dict], None]] = None,
        data_store: Optional[object] = None,
    ) -> None:
        """生成答案的顶层入口。

        核心流程：
          1. 检测是否有中断状态需要恢复（继续请求）
          2. 构建 system message（身份 + 时间 + 风格 + 工作流）
          3. 组装 messages（system + history + query）
          4. 根据 stream 参数选择 _run_tool_loop 或 _run_tool_loop_stream

        Args:
            query: 用户当前问题。
            force_retrieve: 是否强制 LLM 必须调用检索工具。
            stream: 是否启用流式输出。
            history: 历史对话列表。
            partition: 知识库分区（用户名）。
            session_id: 会话 ID。
            style: 回答风格模板名称。
            workflow_name: 工作流名称（None 为自动识别）。
            cancel_check: 可选的中断检测函数，返回 True 时中断生成。
            on_checkpoint: 检查点回调，用于保存中间状态。
            emit_event: 事件推送回调（用于流式输出）。
            data_store: 数据存储实例。

        Returns:
            非流式模式返回答案字符串；流式模式返回生成器对象。
        """
        conf.reload_if_changed()
        from .tools import registry as _reg
        _reg.reset_external_lookup_counts()
        logger.debug(f"收到用户查询: {query} (style={style})")

        interrupted = self._load_interrupted_state(session_id)
        if interrupted and self._is_continue_request(query):
            logger.info(f"检测到继续请求，恢复中断的工具循环: session={session_id}")
            self._clear_interrupted_state(session_id)
            saved_system_msg = interrupted.get("system_msg", "")
            saved_messages = interrupted.get("messages", [])
            restored_messages = [{"role": "system", "content": saved_system_msg}]
            for m in saved_messages:
                if m.get("role") != "system":
                    restored_messages.append(m)
            restored_messages.append({
                "role": "user",
                "content": "继续之前的任务，不要重新开始，基于已有工具结果继续工作。可继续调用所需工具。",
            })
            state = AgentState(
                messages=restored_messages,
                partition=partition,
                session_id=session_id,
                style=style,
                max_iterations=conf.max_tool_iter,
            )
            return self._run_tool_loop(state, saved_system_msg, force_retrieve,
                on_checkpoint=on_checkpoint, data_store=data_store, save_start=len(state.messages) - 1)

        system_msg = self._build_system_message(
            style=style,
        )

        wf_name = workflow_name if workflow_name and workflow_name != "__auto__" else None
        if wf_name:
            wf_content = self.workflow_router.get_workflow_content(wf_name)
            if wf_content:
                system_msg += f"\n\n---\n# 工作流: {wf_name}\n{wf_content}"
                logger.info(f"工作流已加载: {wf_name}")
            else:
                logger.warning(f"工作流 '{wf_name}' 未找到")
        else:
            wf_summaries = self.workflow_router.get_workflow_summaries()
            if wf_summaries:
                system_msg += (
                    f"\n\n---\n# 工作流\n"
                    f"{wf_summaries}\n"
                    f"如需加载完整工作流指令，请调用 read_workflow 工具。"
                )

        if data_store and session_id:
            from .tools._infra_handlers import _get_goal_line
            goal_line = _get_goal_line(session_id, data_store)
            if goal_line:
                system_msg += goal_line
                logger.debug(f"注入活跃目标: session={session_id[:8]}")

        logger.debug(f"system_msg 长度: {len(system_msg)} 字符")

        messages: List[dict] = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        max_iter = conf.max_tool_iter

        state = AgentState(
            messages=messages,
            partition=partition,
            session_id=session_id,
            style=style,
            max_iterations=max_iter,
        )
        _save_start = len(state.messages) - 1

        if stream:
            return self._run_tool_loop_stream(
                state, force_retrieve,
                cancel_check=cancel_check,
                on_checkpoint=on_checkpoint,
                emit_event=emit_event,
                data_store=data_store,
                save_start=_save_start,
            )

        return self._run_tool_loop(state, system_msg, force_retrieve, on_checkpoint=on_checkpoint, data_store=data_store, save_start=_save_start)


    # ── 上下文治理 ──

    def _govern_context(self, messages: List[dict]) -> List[dict]:
        """在调用 LLM 前清理消息列表：截断过长工具结果 + 预算裁剪。

        Args:
            messages: 原始消息列表。

        Returns:
            治理后的消息列表。
        """
        governed = list(messages)

        # -- 1. 工具结果预算截断 --
        limit = conf.max_tool_result_chars
        for i, m in enumerate(governed):
            if m.get("role") == "tool":
                content = m.get("content", "") or ""
                if len(content) > limit:
                    governed[i] = dict(m)
                    governed[i]["content"] = content[:limit] + "\n\n...(工具结果过长，已截断)..."
                    logger.debug(f"工具结果预算截断: {len(content)} → {limit} 字符")

        # -- 2. 历史裁剪 --
        return self._truncate_messages(governed)

    def _truncate_messages(self, messages: List[dict]) -> List[dict]:
        """按字符预算裁剪消息。保留首尾，从最早的消息开始丢弃整轮对话。

        thresholds: conf.context_window_chars 的 context_input_ratio。
        丢弃策略：从最早的非 system 消息开始，按整轮（assistant + 后续的 tool）丢弃，
        保留最近的对话轮次完整。

        Args:
            messages: 原始消息列表。

        Returns:
            裁剪后的消息列表。
        """
        budget = int(conf.context_window_chars * conf.context_input_ratio)
        total = sum(_count_message_chars(m) for m in messages)
        if total <= budget:
            return messages
        
        logger.warning(
            f"上下文超预算: ~{total_chars} chars > {budget} "
            f"(context_window_chars={conf.context_window_chars}), 裁剪最早的消息..."
        )
        
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        rest = messages[1:] if system_msg else messages[:]
        last_msg = rest[-1]
        
        keep = rest[:-1]
        
        while keep:
            total_chars = sum(_count_message_chars(m) for m in keep)
            if system_msg:
                total_chars += _count_message_chars(system_msg)
            total_chars += _count_message_chars(last_msg)
            if total_chars <= budget:
                break
            dropped = keep.pop(0)
            if dropped.get("role") == "assistant":
                while keep and keep[0].get("role") == "tool":
                    keep.pop(0)
        
        result = []
        if system_msg:
            result.append(system_msg)
        result.extend(keep)
        after_chars = sum(_count_message_chars(m) for m in result)
        if total > 0:
            logger.debug(f"裁剪后: ~{after_chars} chars ({int((1-after_chars/total)*100)}% 压缩)")
        return result

    # ── 对话历史持久化 ──

    def _save_turn_messages(self, session_id: str, messages: list, data_store: Optional[object] = None, start: int = 0) -> None:
        """保存本轮完整消息序列（含工具调用和结果）到历史记录。

        跳过 system 消息（由后续回合重建）和 start 之前的消息（已持久化的历史），
        只保存本轮新增的 user / assistant / tool 消息。

        Args:
            session_id: 会话 ID。
            messages: 完整消息列表。
            data_store: 数据存储实例。
            start: 本轮起始索引，之前的消息被视为已持久化的历史。
        """
        if not data_store or not session_id:
            return
        try:
            turn_msgs = [m for m in messages[start:] if m.get("role") != "system"]
            if not turn_msgs:
                return
            data_store.insert_session_turn(session_id, turn_msgs)
            logger.debug(f"已保存完整对话回合: session={session_id[:8]}, {len(turn_msgs)} 条消息")
        except Exception as e:
            logger.warning(f"保存完整对话回合失败: {e}")

    # ── 非流式工具循环 ──

    def _run_tool_loop(self, state: AgentState, system_msg: str, force_retrieve: bool,
                       on_checkpoint: Optional[Callable[[str, dict], None]] = None,
                       data_store: Optional[object] = None,
                       save_start: int = 0) -> str:
        """非流式工具调用主循环。

        循环逻辑（LLM 驱动的工具调用循环）：
          1. LLM 收到完整的 messages（含历史和之前的工具结果）
          2. LLM 决定调用哪些工具 → 返回 tool_calls 列表
          3. 如果 tool_calls 为空：LLM 已准备好最终答案，直接返回
          4. 如果 tool_calls 包含 ask_user_for_clarification：提前终止，返回澄清问题
          5. 否则：并发执行所有工具调用（ThreadPoolExecutor），结果写回 state.messages
          6. 回到步骤 1，直到达到 max_iterations

        达上限处理：
          - 保存中断状态，返回提示文本让用户选择「继续」

        Args:
            state: AgentState 实例，包含 messages、partition、session_id 等。
            system_msg: system message 内容。
            force_retrieve: 是否强制 LLM 必须调用检索工具。
            on_checkpoint: 检查点回调。
            data_store: 数据存储实例。
            save_start: 本轮消息起始索引。

        Returns:
            LLM 生成的最终答案字符串，或达到上限时的提示文本。
        """
        tool_choice = "required" if force_retrieve else "auto"
        _empty_retries = 0
        _length_retries = 0

        while state.should_continue():

            truncated_messages = self._govern_context(state.messages)

            log_llm_input(truncated_messages, round=state.iteration, suffix="_sent")

            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"非流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:
                resp = self.client.chat_with_tools(
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
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        continue
                length_retries = _length_retries
                if resp.get("finish_reason") == "length" and content and length_retries < 3:
                    _length_retries = length_retries + 1
                    logger.warning(f"LLM 响应被截断 (length), 自动续写 ({_length_retries}/3)")
                    state.messages.append({"role": "assistant", "content": content})
                    state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                    continue
                state.messages.append({"role": "assistant", "content": content})
                self._save_turn_messages(state.session_id, state.messages, data_store, start=save_start)
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
                    if isinstance(res, str):
                        res = _persist_tool_result(state.session_id, tc["name"], res)
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
        state.tool_exhausted = True
        state.system_msg = system_msg
        self._save_interrupted_state(state)
        return self._TOOL_EXHAUSTED_MSG


    _TOOL_EXHAUSTED_MSG = (
        "[tool_exhausted] 本任务需要多轮工具调用，但已达单次上限。\n"
        "如需继续，请回复「继续」（将重置计数，基于当前进度继续）。\n"
        "如果已有信息足够，直接说出你的最终答案即可。"
    )

    _INTERRUPT_TAG = "_interrupted_tool_loop"

    # ── 中断状态管理 ──

    def _save_interrupted_state(self, state: AgentState) -> None:
        """保存被中断的工具循环状态到 data_store。

        Args:
            state: 包含当前 messages 和 system_msg 的 AgentState 实例。
        """
        try:
            if self.data_store:
                import json
                tasks = self.data_store.get_session_tasks(state.session_id) or {}
                tasks[self._INTERRUPT_TAG] = {
                    "messages": state.messages,
                    "system_msg": state.system_msg,
                }
                self.data_store.save_session_tasks(state.session_id, tasks)
        except Exception as e:
            logger.warning(f"保存中断状态失败: {e}")

    def _load_interrupted_state(self, session_id: str) -> dict | None:
        """读取被中断的工具循环状态。

        Args:
            session_id: 会话 ID。

        Returns:
            包含 messages 和 system_msg 的中断状态字典，无中断状态时返回 None。
        """
        try:
            if self.data_store:
                tasks = self.data_store.get_session_tasks(session_id) or {}
                return tasks.get(self._INTERRUPT_TAG)
        except Exception:
            pass
        return None

    def _clear_interrupted_state(self, session_id: str) -> None:
        """清除已恢复的中断状态。

        Args:
            session_id: 会话 ID。
        """
        try:
            if self.data_store:
                tasks = self.data_store.get_session_tasks(session_id) or {}
                tasks.pop(self._INTERRUPT_TAG, None)
                self.data_store.save_session_tasks(session_id, tasks)
        except Exception as e:
            logger.warning(f"清除中断状态失败: {e}")

    @staticmethod
    def _is_continue_request(query: str) -> bool:
        """检测用户是否要求继续工具循环。

        Args:
            query: 用户输入的字符串。

        Returns:
            如果用户输入匹配继续指令（如「继续」「continue」等），返回 True。
        """
        q = query.strip().lower()
        return q in ("继续", "continue", "继续做", "接着做", "继续完成", "好，继续", "继续吧")


    # ── 流式工具循环 ──

    def _run_tool_loop_stream(self, state: AgentState, force_retrieve: bool,
                               cancel_check: Optional[Callable[[], bool]] = None,
                               on_checkpoint: Optional[Callable[[str, dict], None]] = None,
                               emit_event: Optional[Callable[[dict], None]] = None,
                               data_store: Optional[object] = None,
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
            force_retrieve: 是否强制 LLM 必须调用检索工具。
            cancel_check: 中断检测函数，返回 True 时终止生成。
            on_checkpoint: 中间检查点保存回调。
            emit_event: 流式事件的发送函数。
            data_store: 数据存储实例。
            save_start: 本轮消息起始索引。
        """
        tool_choice = "required" if force_retrieve else "auto"
        _empty_retries = 0
        _length_retries = 0

        for it in range(state.max_iterations):
            if cancel_check and cancel_check():
                logger.info("工具循环被中断")
                if on_checkpoint and state.messages:
                    on_checkpoint("tools_completed", {
                        "iteration": it,
                        "model": self.chat_model,
                        "pending_calls": tool_calls if tool_calls else None,
                    })
                return
        
            accumulated_content = ""
            tool_calls: List[dict] = []

            if emit_event: emit_event({"type": "status", "status": "thinking"})
            yield {"type": "status", "status": "thinking"}

            truncated_messages = self._govern_context(state.messages)

            log_llm_input(truncated_messages, round=it, suffix="_sent")

            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:
                events = self.client.chat_with_tools(
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
                        if on_checkpoint:
                            on_checkpoint("awaiting_tools", {
                                "iteration": it,
                                "pending_calls": tool_calls,
                            })
                    elif ev["type"] == "finish" and ev.get("reason") == "length":
                        if accumulated_content.strip():
                            lr = _length_retries
                            if lr < 3:
                                _length_retries = lr + 1
                                state.messages.append({"role": "assistant", "content": accumulated_content})
                                state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                                accumulated_content = ""
                                tool_choice = "auto"
            except Exception as e:
                logger.error(f"LLM tool 流式调用失败 (round {it}): {e}")
                if on_checkpoint and state.messages:
                    on_checkpoint("tools_completed", {
                        "iteration": it,
                        "model": self.chat_model,
                        "pending_calls": tool_calls if tool_calls else None,
                    })
                yield {"type": "token", "text": "\n\n抱歉，模型处理请求时发生了错误。"}
                return

            if not tool_calls:
                if not accumulated_content.strip():
                    retries = _empty_retries
                    if retries < 2:
                        _empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({_empty_retries}/2)")
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        if emit_event: emit_event({"type": "status", "status": "retrying"})
                        yield {"type": "status", "status": "retrying"}
                        continue
                state.messages.append({"role": "assistant", "content": accumulated_content})
                self._save_turn_messages(state.session_id, state.messages, data_store, start=save_start)
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
                    if isinstance(res, str):
                        res = _persist_tool_result(state.session_id, tc["name"], res)
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
                        if on_checkpoint:
                            on_checkpoint("tools_completed", {
                                "iteration": it,
                                "tool_name": tool_info.get("tool", ""),
                            })
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
        state.system_msg = state.messages[0]["content"] if state.messages else ""
        self._save_interrupted_state(state)
        for ch in self._TOOL_EXHAUSTED_MSG:
            if emit_event:
                emit_event({"type": "token", "text": ch})
            yield {"type": "token", "text": ch}
        return

