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
    ):
        self.chat_model = chat_model or conf.chat_model
        self.embedding_model = embedding_model or conf.openai_embedding_model
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim

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
        if wf_name:
            wf_content = self.workflow_router.get_workflow_content(wf_name)
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

        state = AgentState(
            messages=messages,
            partition=partition,
            style=style,
            short_term_tasks=short_term_tasks or [],
            long_term_tasks=long_term_tasks or [],
        )

        if stream:
            return self._run_tool_loop_stream(state, force_retrieve)
        return self._run_tool_loop(state, force_retrieve)

    # ─── Tool-call 循环 (非流式) ─────────────────

    def _run_tool_loop(self, state: AgentState, force_retrieve: bool) -> str:
        tool_choice = "required" if force_retrieve else "auto"

        while state.should_continue():
            _log_input(state.messages, round=state.iteration)
            try:
                resp = self.client.chat_with_tools(
                    messages=state.messages, model=self.chat_model,
                    tools=registry.schemas, tool_choice=tool_choice,
                    stream=False, temperature=0.7, max_tokens=2048,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.iteration}): {e}")
                return "抱歉，模型处理请求时发生了错误。"

            if not resp["tool_calls"]:
                return resp["content"]

            logger.info(f"tool-loop {state.iteration} LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            for tc in resp["tool_calls"]:
                result = registry.dispatch(
                    tc["name"], tc["arguments"],
                    ctx=ToolContext(
                        vector_store=self.vector_store,
                        partition=state.partition,
                    )
                )
                state.add_tool_result(tc["id"], result)

            tool_choice = "auto"  # 首轮过后不再强制

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")
        try:
            resp = self.client.chat_with_tools(
                messages=state.messages, model=self.chat_model,
                tools=[], tool_choice="none",
                stream=False, temperature=0.7, max_tokens=2048,
                reasoning_effort=conf.chat_reasoning_effort,
            )
            return resp["content"]
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
            try:
                events = self.client.chat_with_tools(
                    messages=state.messages, model=self.chat_model,
                    tools=registry.schemas, tool_choice=tool_choice,
                    stream=True, temperature=0.7, max_tokens=2048,
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

            for tc in tool_calls:
                # 通知前端正在调工具
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
                yield {"type": "status", "status": "calling_tool", **tool_info}

                result = registry.dispatch(
                    tc["name"], tc["arguments"],
                    ctx=ToolContext(
                        vector_store=self.vector_store,
                        partition=state.partition,
                    )
                )
                state.add_tool_result(tc["id"], result)

                # 通知前端工具完成，附结果摘要
                import re as _re
                if tc["name"] == "search_knowledge_base":
                    _cnt = len(_re.findall(r"【片段 \d+", result))
                    if _cnt:
                        tool_info["chunks"] = _cnt
                elif tc["name"] == "web_search":
                    _cnt = len(_re.findall(r"\[搜索结果 \d+\]", result))
                    if _cnt:
                        tool_info["chunks"] = _cnt
                yield {"type": "status", "status": "tool_result", **tool_info}

            tool_choice = "auto"

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")
        try:
            events = self.client.chat_with_tools(
                messages=state.messages, model=self.chat_model,
                tools=[], tool_choice="none",
                stream=True, temperature=0.7, max_tokens=2048,
                reasoning_effort=conf.chat_reasoning_effort,
            )
            for ev in events:
                if ev["type"] == "content":
                    yield {"type": "token", "text": ev["text"]}
        except Exception as e:
            logger.error(f"最终回答流式生成失败: {e}")
            yield {"type": "token", "text": "\n\n抱歉，生成最终回答时发生了错误。"}


if __name__ == "__main__":
    rag = RAGSystem()
    res = rag.generate_answer("你好", force_retrieve=False)
    print(res)
