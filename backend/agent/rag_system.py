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
from .tools import TOOL_SCHEMAS, execute_tool

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
            dirs = [os.path.join(_BACKEND_ROOT, "prompts")]
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

        logger.info(
            f"RAG agent 就绪, chat_model={self.chat_model}, "
            f"工具={[t['function']['name'] for t in TOOL_SCHEMAS]}"
        )

        if conf.mineru_token_key:
            tok_preview = f"{conf.mineru_token_key[:12]}...({conf.mineru_token_name})"
            logger.info(f"PDF 解析: MinerU [{conf.mineru_model_version}/{conf.mineru_language}] token={tok_preview}")
        else:
            logger.info("PDF 解析: OCRPDFLoader (MinerU token 未配置)")

    def _build_system_message(self, doc_names: List[str], style: Optional[str] = None) -> str:
        """构造 system message: identity + 文档清单 + 可选回答风格。

        style 为 None / "style-default" 时跳过风格注入。
        """
        parts = [self.context_builder.identity or ""]
        parts.append("\n\n## 当前知识库的文档清单\n")
        if doc_names:
            parts.append("\n".join(f"- {n}" for n in doc_names))
        else:
            parts.append("(用户尚未上传任何文档)")
        # 注入回答风格
        if style and style != "style-default":
            skill = self.context_builder.skills.get(style)
            if skill and skill.template:
                parts.append(f"\n\n{skill.template}")
        return "".join(parts)

    # ─── 答案生成入口 ───────────────────────────

    def generate_answer(
        self, query, force_retrieve: bool = False,
        source_filter=None, stream=False, history: list = None,
        partition: str = None, style: Optional[str] = None,
    ):
        logger.info(f"收到用户查询: {query} (style={style})")
        doc_names = self.vector_store.get_documents_by_partition(partition=partition) or []
        logger.info(f"分区 {partition} 可见文档 {len(doc_names)} 份")

        system_msg = self._build_system_message(doc_names, style=style)
        messages: List[dict] = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        state = AgentState(
            messages=messages,
            partition=partition,
            source_filter=source_filter,
            style=style,
        )

        if stream:
            return self._run_tool_loop_stream(state, force_retrieve)
        return self._run_tool_loop(state, force_retrieve)

    # ─── Tool-call 循环 (非流式) ─────────────────

    def _run_tool_loop(self, state: AgentState, force_retrieve: bool) -> str:
        tool_choice = "required" if force_retrieve else "auto"

        while state.should_continue():
            try:
                resp = self.client.chat_with_tools(
                    messages=state.messages, model=self.chat_model,
                    tools=TOOL_SCHEMAS, tool_choice=tool_choice,
                    stream=False, temperature=0.7, max_tokens=2048,
                )
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.iteration}): {e}")
                return "抱歉，模型处理请求时发生了错误。"

            if not resp["tool_calls"]:
                return resp["content"]

            logger.info(f"[tool-loop {state.iteration}] LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            for tc in resp["tool_calls"]:
                result = execute_tool(
                    tc["name"], tc["arguments"],
                    vector_store=self.vector_store,
                    partition=state.partition,
                    source_filter=state.source_filter,
                )
                state.add_tool_result(tc["id"], result)

            tool_choice = "auto"  # 首轮过后不再强制

        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 强制返回")
        return "（已达到工具调用上限，请重新提问。）"

    # ─── Tool-call 循环 (流式) ─────────────────

    def _run_tool_loop_stream(self, state: AgentState, force_retrieve: bool):
        tool_choice = "required" if force_retrieve else "auto"
        total: list = []

        while state.should_continue():
            accumulated_content = ""
            tool_calls: List[dict] = []

            try:
                events = self.client.chat_with_tools(
                    messages=state.messages, model=self.chat_model,
                    tools=TOOL_SCHEMAS, tool_choice=tool_choice,
                    stream=True, temperature=0.7, max_tokens=2048,
                )
                for ev in events:
                    if ev["type"] == "content":
                        accumulated_content += ev["text"]
                        total.append(ev["text"])
                        yield total
                    elif ev["type"] == "tool_calls":
                        tool_calls = ev["calls"]
            except Exception as e:
                logger.error(f"LLM tool 流式调用失败 (round {state.iteration}): {e}")
                total.append("\n\n抱歉，模型处理请求时发生了错误。")
                yield total
                return

            if not tool_calls:
                return  # 终态

            logger.info(f"[tool-loop {state.iteration}] LLM 请求 {len(tool_calls)} 个工具调用")
            state.add_assistant_response(accumulated_content, tool_calls)

            for tc in tool_calls:
                result = execute_tool(
                    tc["name"], tc["arguments"],
                    vector_store=self.vector_store,
                    partition=state.partition,
                    source_filter=state.source_filter,
                )
                state.add_tool_result(tc["id"], result)

            tool_choice = "auto"

        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 强制返回")
        total.append("\n\n（已达到工具调用上限，请重新提问。）")
        yield total


if __name__ == "__main__":
    rag = RAGSystem()
    res = rag.generate_answer("你好", force_retrieve=False)
    print(res)
