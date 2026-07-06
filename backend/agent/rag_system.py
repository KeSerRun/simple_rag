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

# —— 配置与日志 ——
from base.config import conf          # 全局配置（模型名、超时、token 限制等）
from base.logger import logger        # 结构化日志

# —— RAG 核心组件 ——
from rag.core.local_vector_store import VectorStore  # 本地向量存储，用于语义搜索
from rag.core.openai_client import OpenAIClient      # OpenAI 兼容的 API 客户端（流式 / 非流式）
from rag.core.reranker import LLMReranker            # LLM Listwise Reranker（对检索结果重排序）

# —— Agent 内部组件 ——
from .context_builder import ContextBuilder  # 从 prompts 目录加载 identity / 风格模板
from .state import AgentState                # 工具循环的状态机（迭代计数、消息列表、工具调用记录）
from .registry import ToolContext            # 工具执行时的上下文（向量库、分区、数据存储）
from .tools import registry                  # 全局工具注册表，管理所有可用工具的 schema 和 dispatch
from .workflow_router import WorkflowRouter  # 路由引擎：根据用户问题匹配预设工作流

# 后端根目录（本项目 backend/ 目录的绝对路径）
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
    """RAG 系统的核心入口，管理 LLM 客户端、向量库、工具注册表和工作流路由。

    整体流程：
      generate_answer(query)
        └─ _build_system_message()          → 组装 system prompt（identity + 时间 + 任务 + 风格）
        └─ workflow_router.match()           → 匹配对应的工作流并注入 system prompt
        └─ AgentState 初始化                 → 封装 messages、分区、迭代限制
        └─ _run_tool_loop(state)            → 非流式：工具循环直到 LLM 不再调用工具
           └─ 循环内：LLM → tool_calls → 并发执行 → 结果回灌 → 重复
           └─ 达上限时：注入强制结束指令，生成最终回答
        └─ _run_tool_loop_stream(state)     → 流式：同上 + 逐 token yield + status 事件
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
        # —— 模型配置：如果未传入则从 global conf 读取默认值 ——
        self.chat_model = chat_model or conf.chat_model
        self.embedding_model = embedding_model or conf.openai_embedding_model
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim
        self.data_store = data_store

        # —— prompts 目录解析：支持单目录 / 多目录，默认为 backend/prompts/{,style/} ——
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

        # —— LLM 客户端（对话 / 工具调用） ——
        self.client = OpenAIClient(
            api_key=conf.openai_api_key, base_url=conf.openai_base_url,
            timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
        )

        # —— Embedding 客户端：如果 endpoint 与 chat 相同则复用，否则独立创建 ——
        if conf.embedding_api_key == conf.openai_api_key and conf.embedding_base_url == conf.openai_base_url:
            self.embed_client = self.client
            logger.info("Embedding 端与 chat 端共用同一 OpenAI 客户端")
        else:
            self.embed_client = OpenAIClient(
                api_key=conf.embedding_api_key, base_url=conf.embedding_base_url,
                timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
            )
            logger.info(f"Embedding 端使用独立客户端: base_url={conf.embedding_base_url}")

        # —— 向量存储：用于语义检索（RAG 的核心检索组件） ——
        self.vector_store = VectorStore(
            client=self.embed_client,
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
        )

        # —— 工作流路由器：根据 query 关键词匹配预设 workflow（如 USstocks、Autoplan） ——
        self.workflow_router = WorkflowRouter(
            os.path.join(_BACKEND_ROOT, "prompts")
        )

        # —— LLM Listwise Reranker：对检索结果做相关性重排序 ——
        # 如果配置开启，检索后的 chunks 会经过一次 LLM 排序，保留最相关的 Top-K 片段
        self.reranker = LLMReranker(
            client=self.client,
            model=self.chat_model,
            enable=conf.enable_llm_rerank,
        )

        logger.info(
            f"RAG agent 就绪, chat_model={self.chat_model}, "
            f"工具={[t['function']['name'] for t in registry.schemas]}"
        )

        # —— PDF 解析方案日志（MinerU vs OCRPDFLoader） ——
        if conf.mineru_api_key:
            tok_preview = f"{conf.mineru_api_key[:12]}...({conf.mineru_token_name})"
            logger.info(f"PDF 解析: MinerU {conf.mineru_model_version}/{conf.mineru_language} token={tok_preview}")
        else:
            logger.info("PDF 解析: OCRPDFLoader (MinerU token 未配置)")

    # ─── System Message 组装 ───────────────────────

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

        # —— 注入当前时间, 帮助 LLM 理解 "今年" "最近" "今天" 等时间指代 ——
        from datetime import datetime as _dt
        import time as _time
        _tz = _time.tzname
        parts.append(f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} (时区: {_tz[0] if _tz else 'UTC'})")

        # —— 注入短期/长期任务 ——
        # 短期任务：用户当前会话中交代的临时任务
        # 长期任务：跨会话持久化的任务描述
        tasks_lines = []
        if short_term_tasks:
            tasks_lines.append("短期任务：" + "；".join(short_term_tasks))
        if long_term_tasks:
            tasks_lines.append("长期任务：" + "；".join(long_term_tasks))
        if tasks_lines:
            parts.append("\n\n---\n" + "\n".join(tasks_lines))

        # —— 注入回答风格 ——
        # style 是预先定义好的 prompt 模板（如 "concise"、"detailed"、"friendly"）
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
        """生成答案的顶层入口。

        参数:
          query           : 用户当前问题
          force_retrieve  : 是否强制 LLM 必须调用检索工具（用于"必须查资料"的场景）
          stream          : 是否启用流式输出
          history         : 历史对话列表
          partition       : 知识库分区（用于多租户/多知识库场景）
          style           : 回答风格模板名称
          short_term_tasks: 本次会话的短期任务列表
          long_term_tasks : 跨会话的长期任务列表
        """
        logger.info(f"收到用户查询: {query} (style={style})")

        # —— 第一步：组装 system message ——
        system_msg = self._build_system_message(
            style=style,
            short_term_tasks=short_term_tasks,
            long_term_tasks=long_term_tasks,
        )

        # ── Workflow 路由注入 ─────────────────────────────────────────
        # 通过 WorkflowRouter 将 query 与预设工作流（如 "USstocks"、"Autoplan"）匹配
        # 匹配成功后，将对应工作流的提示文本注入到 system message 中
        wf_name = self.workflow_router.match(query)
        wf_config = {}
        if wf_name:
            wf_content = self.workflow_router.get_workflow_content(wf_name)  # 工作流指令文本
            wf_config = self.workflow_router.get_workflow_config(wf_name)    # 工作流配置（如迭代次数覆盖）
            if wf_content:
                system_msg += (
                    f"\n\n---\n## ⚠️ 必须遵守的工作流：{wf_name}\n"
                    f"{wf_content}"
                )
                logger.info(f"已注入 workflow [{wf_name}] 到 system message")

        # —— 第二步：组装完整的 messages ——
        # 结构：[system, ...历史对话, 当前用户问题]
        messages: List[dict] = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        # —— 第三步：确定迭代次数上限 ——
        # 优先使用 workflow 中定义的覆盖值，否则使用全局配置
        max_iter_val = wf_config.get("max_tool_iter")
        max_calls_val = wf_config.get("max_calls_per_tool")
        max_iter = int(max_iter_val) if max_iter_val is not None else conf.max_tool_iter
        max_calls = int(max_calls_val) if max_calls_val is not None else conf.max_calls_per_tool

        # —— 第四步：初始化 AgentState（工具循环的状态管理） ——
        state = AgentState(
            messages=messages,
            partition=partition,
            style=style,
            short_term_tasks=short_term_tasks or [],
            long_term_tasks=long_term_tasks or [],
            max_iterations=max_iter,
            max_calls_per_tool=max_calls,
        )

        # —— 第五步：分发到流式或非流式执行路径 ——
        if stream:
            return self._run_tool_loop_stream(state, force_retrieve)

        # 非流式：直接返回 tool loop 生成的最终答案
        return self._run_tool_loop(state, force_retrieve)

    # ─── 上下文裁剪 ───────────────────────────

    def _truncate_messages(self, messages: List[dict], max_chars: int = 40000) -> List[dict]:
        """按需裁剪消息长度。保留首尾（system, 最新用户提问），裁剪中间的检索结果。

        由于 LLM 上下文窗口有限，当 tool loop 多次迭代后，大量的检索结果和中间消息
        会撑爆上下文。该方法在每次调用 LLM 之前执行"瘦身"。

        裁剪策略：
          - system message 始终完整保留
          - 最后一条消息（最新用户问题）始终完整保留
          - 中间过长的 tool 消息截取首尾各 1500 字符，中间用省略提示替换
          - 非 tool 的中间消息保持不动
          - 如果裁剪后仍然超长，不做二次处理（仅记录日志）
        """
        # 简单粗暴的字符长度计算 (1 token ~ 2 汉字 / 4 英文字符，40000字符约合 1~2 万 token)
        total_len = sum(len(str(m.get("content", ""))) for m in messages)
        if total_len <= max_chars:
            return messages

        logger.warning(f"上下文总长度({total_len})超过阈值({max_chars})，进行截断...")

        new_messages = []
        # 始终保留 system 提示（必须是第一个）和最后一个用户的问题及周边
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None

        # 遍历每条消息，按规则决定保留或截断
        for idx, m in enumerate(messages):
            # 第一条 system 消息完整保留
            if idx == 0 and system_msg:
                new_messages.append(m)
                continue

            # 最后一个 message 总是保留完整（通常是用户的最新问题或 LLM 的最后回复）
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
        """非流式工具调用主循环。

        循环逻辑（LLM 驱动的工具调用循环）：
          1. LLM 收到完整的 messages（含历史和之前的工具结果）
          2. LLM 决定调用哪些工具 → 返回 tool_calls 列表
          3. 如果 tool_calls 为空：LLM 已准备好最终答案，直接返回
          4. 如果 tool_calls 包含 ask_user_for_clarification：提前终止，返回澄清问题
          5. 否则：并发执行所有工具调用（ThreadPoolExecutor），结果写回 state.messages
          6. 回到步骤 1，直到达到 max_iterations

        达上限处理：
          - 注入一条"不再允许调工具"的 user 消息
          - 调用纯 chat（不带 tools）让 LLM 基于已有信息生成最终答案
        """
        tool_choice = "required" if force_retrieve else "auto"

        # while 循环直到 should_continue() 返回 False（达上限或主动 break）
        while state.should_continue():
            _log_input(state.messages, round=state.iteration)

            # 发送前裁剪（避免上下文窗口溢出）
            truncated_messages = self._truncate_messages(state.messages)

            # —— 1. 调用 LLM，传入 tools 让 LLM 自主决定是否调用 ——
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

            # —— 2. 终止条件：LLM 不再请求调用工具，返回最终文本 ——
            if not resp["tool_calls"]:
                return resp["content"]

            logger.info(f"tool-loop {state.iteration} LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            # —— 3. 将 LLM 的响应（含 tool_calls）追加到 state ——
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            import concurrent.futures

            # —— 4. 定义单个工具的 dispatch 任务 ——
            def _dispatch_task(tc):
                # 防止重复调用或单工具超限
                is_blocked, block_msg = state.check_and_record_tool_call(tc["name"], tc["arguments"])
                if is_blocked:
                    logger.warning(f"工具调用被拦截: {tc['name']} 原因: {block_msg}")
                    return tc["id"], block_msg

                try:
                    # 通过注册表调度到具体的工具实现
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                            reranker=self.reranker,
                        )
                    )
                    return tc["id"], res
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 执行发生严重异常: {e}", exc_info=True)
                    return tc["id"], f"(系统提示: 执行工具 {tc['name']} 时发生了严重错误: {e}，请尝试使用其他工具或根据现有信息回答)"

            # —— 5. 并发执行所有工具（ThreadPoolExecutor） ——
            # 每个工具的执行是独立的 I/O 密集型任务，并发可以大幅减少总耗时
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(resp["tool_calls"])) as executor:
                futures = [executor.submit(_dispatch_task, tc) for tc in resp["tool_calls"]]
                for future in concurrent.futures.as_completed(futures):
                    tc_id, result = future.result()
                    state.add_tool_result(tc_id, result)

            # —— 6. 提前退出检查：如果包含 ask_user_for_clarification，则终止并抛出问题 ——
            # ask_user_for_clarification 是一个特殊工具，当 LLM 认为信息不足需要向用户提问时调用
            for tc in resp["tool_calls"]:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except:
                        q = "我需要您提供更多背景信息。"
                    logger.info("提前中断工具循环：LLM 需要澄清")
                    return q

            # 首轮过后不再强制 tool_choice，让 LLM 自由选择是否继续调用工具
            tool_choice = "auto"

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")

        # 强制切断模型对工具的执念
        # 注入一条 system 风格的 user 消息，明确告诉 LLM 不再允许调工具，
        # 让 LLM 退而基于已有信息（检索结果）综合回答
        final_messages = list(state.messages)
        final_messages.append({
            "role": "user",
            "content": "（系统指令：为保证对话效率，当前任务的检索环节已结束，不再允许调用任何工具。请立刻以自然语言回复用户。要求：1. 尽力综合已获取的信息提供有价值的答案；2. 如果信息相互矛盾或不完整，请客观指出，并用友善的语气主动引导用户补充更详细的条件或线索；3. 不要向用户提及“系统切断连接”或“调用次数达上限”等内部机制设定。）"
        })

        try:
            # 注意：此处调用的是 chat() 而非 chat_with_tools() —— 不再传 tools，
            # 相当于强制 LLM 无法再调用工具，只能基于已有内容生成自然语言回答
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

        与非流式版本的核心逻辑相同，但：
          - 使用 Python generator（yield）逐块返回
          - 产生 "token" 事件用于前端逐字展示
          - 产生 "status" 事件用于前端显示"思考中"、"调用工具"、"工具完成"等状态

        Yield 格式:
          {"type": "token", "text": "..."}
          {"type": "status", "status": "thinking"}
          {"type": "status", "status": "calling_tool", "tool": "search_knowledge_base", "args": [...]}
          {"type": "status", "status": "tool_result", "tool": "search_knowledge_base", "chunks": 5}
        """
        tool_choice = "required" if force_retrieve else "auto"

        # 使用 for 循环（range 方式）替代 while，上限即为 max_iterations
        for it in range(state.max_iterations):
            accumulated_content = ""
            tool_calls: List[dict] = []

            # —— 通知前端开始思考 ——
            yield {"type": "status", "status": "thinking"}
            _log_input(state.messages, round=it)

            # 发送前裁剪
            truncated_messages = self._truncate_messages(state.messages)

            # —— 1. 流式调用 LLM ——
            # 返回的是事件生成器：包含 "content"（文本 token）和 "tool_calls"（工具调用）
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

            # —— 2. 终止条件：无工具调用，流式答案已全部吐出，直接结束 ——
            if not tool_calls:
                return  # 终态: 无工具调用, 已流完答案

            logger.info(f"tool-loop {it} LLM 请求 {len(tool_calls)} 个工具调用")
            state.add_assistant_response(accumulated_content, tool_calls)

            import concurrent.futures

            # —— 3. 单个工具调度（流式版本多返回 tool_info 用于前端展示） ——
            def _dispatch_task_stream(tc):
                import json as _json
                tool_info = {"tool": tc["name"]}
                # 解析参数，提取关键信息用于前端展示
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
                            reranker=self.reranker,
                        )
                    )
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 异常: {e}", exc_info=True)
                    res = f"(系统提示: 执行工具 {tc['name']} 发生错误: {e}，请尝试其他策略)"

                return tc["id"], tool_info, res

            # —— 4. 先通知前端即将调用的所有工具 ——
            for tc in tool_calls:
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

            # —— 5. 并发执行所有工具 ——
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

            # —— 6. 提前退出检查：流式模式下 ——
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

            # 首轮过后不再强制调用工具
            tool_choice = "auto"

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")

        # 强制切断模型对工具的执念（同非流式版本）
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
