"""RAG agent: tool-calling 循环驱动 LLM 自主决策是否检索 / 如何拆解查询 / 最终答案。

流程:
  1. identity + 当前分区文档清单 → system message
  2. [system, ...history, user(query)] → LLM (带 search_knowledge_base 工具)
  3. LLM 决定是否调工具 / 调几次 → 工具结果回灌 messages
  4. 无更多工具调用 → streamed 最终答案

AgentState 封装了循环中的 messages / 轮次 / 上下文参数。
"""
import os
from typing import List, Optional

from base.config import conf
from base.logger import logger

from rag.core.local_vector_store import VectorStore
from rag.core.openai_client import OpenAIClient

from .context_builder import ContextBuilder
from .state import AgentState
from .registry import ToolContext
from .tools import registry
from .workflow_router import WorkflowRouter

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 输入日志（每次调 LLM 的完整 messages）
_input_log_path = os.path.join(_BACKEND_ROOT, "logs", "input.log")


def _log_input(messages: list, round: int = 0):
    """将 messages 追加到 input.log。"""
    import json as _json, datetime as _dt
    try:
        os.makedirs(os.path.dirname(_input_log_path), exist_ok=True)
        with open(_input_log_path, "a", encoding="utf-8") as _f:
            _f.write(f"\n=== {_dt.datetime.now().isoformat()} round={round} ===\n")
            _f.write(_json.dumps(messages, ensure_ascii=False, indent=2))
            _f.write("\n")
    except Exception:
        pass


class RAGSystem:
    def __init__(
        self,
        chat_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        prompts_dir: Optional[str] = None,
        prompts_dirs: Optional[List[str]] = None,
        data_store: Optional[object] = None,
    ):
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
            api_key=conf.openai_api_key, base_url=conf.openai_base_url,
            timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
        )

        if conf.embedding_api_key == conf.openai_api_key and conf.embedding_base_url == conf.openai_base_url:
            self.embed_client = self.client
            logger.info("Embedding 端与 chat 端共用同一 OpenAI 客户端")
        else:
            self.embed_client = OpenAIClient(
                api_key=conf.embedding_api_key, base_url=conf.embedding_base_url,
                timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
            )
            logger.info(f"Embedding 端使用独立客户端: base_url={conf.embedding_base_url}")

        self.vector_store = VectorStore(
            client=self.embed_client,
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
        )

        # 初始化 WorkflowRouter
        self.workflow_router = WorkflowRouter(
            os.path.join(_BACKEND_ROOT, "prompts")
        )

        logger.info(
            f"RAG agent 就绪, chat_model={self.chat_model}, "
            f"工具={[t['function']['name'] for t in registry.schemas]}"
        )

        if conf.mineru_api_key:
            tok_preview = f"{conf.mineru_api_key[:12]}...({conf.mineru_token_name})"
            logger.info(f"PDF 解析: MinerU {conf.mineru_model_version}/{conf.mineru_language} token={tok_preview}")
        else:
            logger.info("PDF 解析: OCRPDFLoader (MinerU token 未配置)")

    def _build_system_message(
        self,
        style: Optional[str] = None,
        short_term_tasks: Optional[List[str]] = None,
        long_term_tasks: Optional[List[str]] = None,
    ) -> str:
        """构造 system message: identity + 可选回答风格 + 短期/长期任务。

        style 为 None / "style-default" 时跳过风格注入。
        文档清单不再注入 system message，LLM 通过 list_documents 工具按需获取。
        """
        parts = [self.context_builder.identity or ""]
        # 注入当前时间, 帮助 LLM 理解 "今年" "最近" "今天" 等时间指代
        from datetime import datetime as _dt
        import time as _time
        _tz = _time.tzname
        parts.append(f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} (时区: {_tz[0] if _tz else 'UTC'})")

        # 注入短期/长期任务
        tasks_lines = []
        if short_term_tasks:
            tasks_lines.append("短期任务：" + "；".join(short_term_tasks))
        if long_term_tasks:
            tasks_lines.append("长期任务：" + "；".join(long_term_tasks))
        if tasks_lines:
            parts.append("\n\n---\n" + "\n".join(tasks_lines))

        # 注入回答风格
        if style and style != "style-default":
            skill = self.context_builder.skills.get(style)
            if skill and skill.template:
                parts.append(f"\n\n{skill.template}")
        return "".join(parts)

    # ─── 答案生成入口 ───────────────────────────

    def generate_answer(
        self, query, force_retrieve: bool = False,
        stream=False, history: list = None,
        partition: str = None, style: Optional[str] = None,
        short_term_tasks: Optional[List[str]] = None,
        long_term_tasks: Optional[List[str]] = None,
    ):
        logger.info(f"收到用户查询: {query} (style={style})")

        system_msg = self._build_system_message(
            style=style,
            short_term_tasks=short_term_tasks,
            long_term_tasks=long_term_tasks,
        )

        # ── Workflow 路由注入 ─────────────────────────────────────────
        wf_name = self.workflow_router.match(query)
        wf_config = {}
        if wf_name:
            wf_content = self.workflow_router.get_workflow_content(wf_name)
            wf_config = self.workflow_router.get_workflow_config(wf_name)
            if wf_content:
                system_msg += (
                    f"\n\n---\n## ⚠️ 必须遵守的工作流：{wf_name}\n"
                    f"{wf_content}"
                )
                logger.info(f"已注入 workflow [{wf_name}] 到 system message")

        messages: List[dict] = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        # 动态应用 Workflow 的特殊配置（如果有的话）
        max_iter_val = wf_config.get("max_tool_iter")
        max_calls_val = wf_config.get("max_calls_per_tool")
        max_iter = int(max_iter_val) if max_iter_val is not None else conf.max_tool_iter
        max_calls = int(max_calls_val) if max_calls_val is not None else conf.max_calls_per_tool

        state = AgentState(
            messages=messages,
            partition=partition,
            style=style,
            short_term_tasks=short_term_tasks or [],
            long_term_tasks=long_term_tasks or [],
            max_iterations=max_iter,
            max_calls_per_tool=max_calls,
        )

        if stream:
            return self._run_tool_loop_stream(state, force_retrieve)

        # 非流式：直接返回 tool loop 生成的最终答案
        return self._run_tool_loop(state, force_retrieve)

    def _truncate_messages(self, messages: List[dict], max_chars: int = 40000) -> List[dict]:
        """按需裁剪消息长度。保留首尾（system, 最新用户提问），裁剪中间的检索结果。"""
        # 简单粗暴的字符长度计算 (1 token ~ 2 汉字 / 4 英文字符，40000字符约合 1~2 万 token)
        total_len = sum(len(str(m.get("content", ""))) for m in messages)
        if total_len <= max_chars:
            return messages

        logger.warning(f"上下文总长度({total_len})超过阈值({max_chars})，进行截断...")

        new_messages = []
        # 始终保留 system 提示（必须是第一个）和最后一个用户的问题及周边
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None

        # 找出哪些可以压缩（优先压缩中间的 tool 结果，或者老旧的历史）
        for idx, m in enumerate(messages):
            if idx == 0 and system_msg:
                new_messages.append(m)
                continue

            # 最后一个 message 总是保留完整
            if idx == len(messages) - 1:
                new_messages.append(m)
                continue

            # 中间的 message，如果是 tool role 且过长，则截断
            if m.get("role") == "tool" and len(str(m.get("content", ""))) > 3000:
                truncated_content = m["content"][:1500] + "\n...(部分检索内容已因超长被系统截断)...\n" + m["content"][-1500:]
                m_copy = m.copy()
                m_copy["content"] = truncated_content
                new_messages.append(m_copy)
            else:
                new_messages.append(m)

        # 再次检查
        new_len = sum(len(str(m.get("content", ""))) for m in new_messages)
        logger.info(f"截断后上下文总长度为: {new_len}")
        return new_messages

    # ─── Tool-call 循环 (非流式) ─────────────────

    def _run_tool_loop(self, state: AgentState, force_retrieve: bool) -> str:
        tool_choice = "required" if force_retrieve else "auto"

        while state.should_continue():
            _log_input(state.messages, round=state.iteration)

            # 发送前裁剪
            truncated_messages = self._truncate_messages(state.messages)

            try:
                resp = self.client.chat_with_tools(
                    messages=truncated_messages, model=self.chat_model,
                    tools=registry.schemas, tool_choice=tool_choice,
                    stream=False, temperature=0.7, max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.iteration}): {e}")
                return "抱歉，模型处理请求时发生了错误。"

            if not resp["tool_calls"]:
                return resp["content"]

            logger.info(f"tool-loop {state.iteration} LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            import concurrent.futures

            def _dispatch_task(tc):
                # 防止重复调用或单工具超限
                is_blocked, block_msg = state.check_and_record_tool_call(tc["name"], tc["arguments"])
                if is_blocked:
                    logger.warning(f"工具调用被拦截: {tc['name']} 原因: {block_msg}")
                    return tc["id"], block_msg

                try:
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                        )
                    )
                    return tc["id"], res
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 执行发生严重异常: {e}", exc_info=True)
                    return tc["id"], f"(系统提示: 执行工具 {tc['name']} 时发生了严重错误: {e}，请尝试使用其他工具或根据现有信息回答)"

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(resp["tool_calls"])) as executor:
                futures = [executor.submit(_dispatch_task, tc) for tc in resp["tool_calls"]]
                for future in concurrent.futures.as_completed(futures):
                    tc_id, result = future.result()
                    state.add_tool_result(tc_id, result)

            # 提前退出检查：如果包含 ask_user_for_clarification，则终止并抛出问题
            for tc in resp["tool_calls"]:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except:
                        q = "我需要您提供更多背景信息。"
                    logger.info("提前中断工具循环：LLM 需要澄清")
                    return q

            tool_choice = "auto"  # 首轮过后不再强制

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")

        # 强制切断模型对工具的执念
        final_messages = list(state.messages)
        final_messages.append({
            "role": "user",
            "content": "（系统指令：为保证对话效率，当前任务的检索环节已结束，不再允许调用任何工具。请立刻以自然语言回复用户。要求：1. 尽力综合已获取的信息提供有价值的答案；2. 如果信息相互矛盾或不完整，请客观指出，并用友善的语气主动引导用户补充更详细的条件或线索；3. 不要向用户提及“系统切断连接”或“调用次数达上限”等内部机制设定。）"
        })

        try:
            resp = self.client.chat(
                messages=final_messages, model=self.chat_model,
                stream=False, temperature=0.7, max_tokens=conf.max_output_tokens,
                reasoning_effort=conf.chat_reasoning_effort,
            )
            return resp
        except Exception as e:
            logger.error(f"最终回答生成失败: {e}")
            return "抱歉，生成最终回答时发生了错误。"

    # ─── Tool-call 循环 (流式) ─────────────────

    def _run_tool_loop_stream(self, state: AgentState, force_retrieve: bool):
        """流式生成器: 逐 token 产出, 中间穿插 status 事件。

        Yield 格式:
          {"type": "token", "text": "..."}
          {"type": "status", "status": "thinking"}
          {"type": "status", "status": "calling_tool", "tool": "search_knowledge_base", "args": [...]}
          {"type": "status", "status": "tool_result", "tool": "search_knowledge_base", "chunks": 5}
        """
        tool_choice = "required" if force_retrieve else "auto"

        for it in range(state.max_iterations):
            accumulated_content = ""
            tool_calls: List[dict] = []

            # 通知前端开始思考
            yield {"type": "status", "status": "thinking"}
            _log_input(state.messages, round=it)

            # 发送前裁剪
            truncated_messages = self._truncate_messages(state.messages)

            try:
                events = self.client.chat_with_tools(
                    messages=truncated_messages, model=self.chat_model,
                    tools=registry.schemas, tool_choice=tool_choice,
                    stream=True, temperature=0.7, max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
                for ev in events:
                    if ev["type"] == "content":
                        accumulated_content += ev["text"]
                        yield {"type": "token", "text": ev["text"]}
                    elif ev["type"] == "tool_calls":
                        tool_calls = ev["calls"]
            except Exception as e:
                logger.error(f"LLM tool 流式调用失败 (round {it}): {e}")
                yield {"type": "token", "text": "\n\n抱歉，模型处理请求时发生了错误。"}
                return

            if not tool_calls:
                return  # 终态: 无工具调用, 已流完答案

            logger.info(f"tool-loop {it} LLM 请求 {len(tool_calls)} 个工具调用")
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

                # 防重检测与单工具超限
                is_blocked, block_msg = state.check_and_record_tool_call(tc["name"], tc["arguments"])
                if is_blocked:
                    logger.warning(f"工具调用被拦截: {tc['name']} 原因: {block_msg}")
                    return tc["id"], tool_info, block_msg

                try:
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                        )
                    )
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 异常: {e}", exc_info=True)
                    res = f"(系统提示: 执行工具 {tc['name']} 发生错误: {e}，请尝试其他策略)"

                return tc["id"], tool_info, res

            # 先通知前端正在调用的所有工具
            for tc in tool_calls:
                 # 这部分提取太重了，这里为了简便直接提取参数通知
                 import json as _json
                 tmp_info = {"tool": tc["name"]}
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
                 yield {"type": "status", "status": "calling_tool", **tmp_info}

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                futures = [executor.submit(_dispatch_task_stream, tc) for tc in tool_calls]
                for future in concurrent.futures.as_completed(futures):
                    tc_id, tool_info, result = future.result()
                    state.add_tool_result(tc_id, result)

                    # 收到结果，通知前端该工具完成并附上摘要
                    import re as _re
                    if tool_info.get("tool") == "search_knowledge_base":
                        _cnt = len(_re.findall(r"【片段 \d+", result))
                        if _cnt:
                            tool_info["chunks"] = _cnt
                    elif tool_info.get("tool") == "web_search":
                        _cnt = len(_re.findall(r"\[搜索结果 \d+\]", result))
                        if _cnt:
                            tool_info["chunks"] = _cnt
                    yield {"type": "status", "status": "tool_result", **tool_info}

            # 提前退出检查：流式模式下
            for tc in tool_calls:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except:
                        q = "我需要您提供更多背景信息。"
                    logger.info("流式提前中断工具循环：LLM 需要澄清")
                    yield {"type": "token", "text": "\n\n" + q}
                    return

            tool_choice = "auto"

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")

        # 强制切断模型对工具的执念
        final_messages = list(state.messages)
        final_messages.append({
            "role": "user",
            "content": "（系统指令：为保证对话效率，当前任务的检索环节已结束，不再允许调用任何工具。请立刻以自然语言回复用户。要求：1. 尽力综合已获取的信息提供有价值的答案；2. 如果信息相互矛盾或不完整，请客观指出，并用友善的语气主动引导用户补充更详细的条件或线索；3. 不要向用户提及“系统切断连接”或“调用次数达上限”等内部机制设定。）"
        })

        try:
            events = self.client.chat(
                messages=final_messages, model=self.chat_model,
                stream=True, temperature=0.7, max_tokens=conf.max_output_tokens,
                reasoning_effort=conf.chat_reasoning_effort,
            )
            for text in events:
                yield {"type": "token", "text": text}
        except Exception as e:
            logger.error(f"最终回答流式生成失败: {e}")
            yield {"type": "token", "text": "\n\n抱歉，生成最终回答时发生了错误。"}


if __name__ == "__main__":
    rag = RAGSystem()
    res = rag.generate_answer("你好", force_retrieve=False)
    print(res)
