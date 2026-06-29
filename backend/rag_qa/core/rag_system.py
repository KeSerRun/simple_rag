import os
from typing import List, Optional

from base.config import conf
from base.logger import logger

from .context_builder import ContextBuilder
from .llm import LLMModel
from .local_vector_store import VectorStore
from .openai_client import OpenAIClient
from .query_classifier import QueryClassifier
from .strategy_selector import StrategySelector

# backend 根目录(本文件位于 backend/rag_qa/core/rag_system.py)
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RAGSystem:
    """RAG 问答系统：所有 LLM/Embedding/Rerank 调用都走共享的 OpenAIClient,
    所有 prompt 都从 prompts/ 目录通过 ContextBuilder 加载。
    """

    def __init__(
        self,
        chat_model: Optional[str] = None,
        strategy_model: Optional[str] = None,
        classifier_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        enable_llm_rerank: Optional[bool] = None,
        classifier_label_list: Optional[List[str]] = None,
        prompts_dir: Optional[str] = None,
        prompts_dirs: Optional[List[str]] = None,
    ):
        # 模型/参数
        self.chat_model = chat_model or conf.chat_model
        self.strategy_model = strategy_model or conf.strategy_model
        self.classifier_model = classifier_model or conf.classifier_model
        self.embedding_model = embedding_model or conf.openai_embedding_model
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim
        self.enable_llm_rerank = (
            enable_llm_rerank if enable_llm_rerank is not None else conf.enable_llm_rerank
        )
        self.classifier_label_list = classifier_label_list or conf.query_classifier_label_list

        # ContextBuilder:加载 identity + skills
        # 优先级: prompts_dirs(列表,多目录) > prompts_dir(单目录,向后兼容) > 默认基线
        if prompts_dirs:
            dirs = prompts_dirs
        elif prompts_dir:
            dirs = [prompts_dir]
        else:
            dirs = [os.path.join(_BACKEND_ROOT, "prompts")]
        self.context_builder = ContextBuilder(dirs)

        # Chat 端 OpenAI 客户端(LLM / 策略 / 分类 / rerank)
        self.client = OpenAIClient(
            api_key=conf.openai_api_key,
            base_url=conf.openai_base_url,
            timeout=conf.openai_timeout,
            max_retries=conf.openai_max_retries,
        )

        # Embedding 端 OpenAI 客户端;若与 chat 端配置一致则复用同一实例
        if conf.embedding_api_key == conf.openai_api_key and conf.embedding_base_url == conf.openai_base_url:
            self.embed_client = self.client
            logger.info("Embedding 端与 chat 端共用同一 OpenAI 客户端")
        else:
            self.embed_client = OpenAIClient(
                api_key=conf.embedding_api_key,
                base_url=conf.embedding_base_url,
                timeout=conf.openai_timeout,
                max_retries=conf.openai_max_retries,
            )
            logger.info(f"Embedding 端使用独立客户端: base_url={conf.embedding_base_url}")

        # 查询分类器(走 chat 端)
        self.query_classifier = QueryClassifier(
            client=self.client,
            model=self.classifier_model,
            label_list=self.classifier_label_list,
            context_builder=self.context_builder,
        )
        logger.info(f"查询分类器初始化完成,使用模型: {self.classifier_model}")

        # 策略选择器(走 chat 端)
        self.strategy_selector = StrategySelector(
            client=self.client,
            model=self.strategy_model,
            context_builder=self.context_builder,
        )
        logger.info(f"策略选择器初始化完成,使用模型: {self.strategy_model}")

        # 向量存储:embedding 走 embed_client,rerank 走 chat 端的 client
        self.vector_store = VectorStore(
            client=self.embed_client,
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
            enable_llm_rerank=self.enable_llm_rerank,
            chat_model=self.chat_model,
            chat_client=self.client,
            context_builder=self.context_builder,
        )

        # 主 LLM(走 chat 端,注入 identity 作为 system message)
        self.llm = LLMModel(
            client=self.client,
            model=self.chat_model,
            identity=self.context_builder.identity,
        )
        logger.info(f"LLM 模型加载完成,使用模型: {self.chat_model}")

    # ─── 答案生成入口 ───────────────────────────

    def generate_answer(
        self,
        query,
        force_retrieve: bool = False,
        source_filter=None,
        stream=False,
        history: list = None,
        partition: str = None,
    ):
        logger.info(f"收到用户查询: {query}")
        if not force_retrieve:
            try:
                query_category = self.query_classifier.predict(query)
                logger.info(f"查询分类结果: {query_category}")
                if query_category == self.classifier_label_list[1]:
                    # 通用闲聊路径:直接走 LLMModel(带 identity + history)
                    return self.call_llm(query, stream=stream, history=history)
            except Exception as e:
                logger.error(f"生成答案时发生错误: {e}")
                return "抱歉，我无法生成答案。"

        strategy = self.strategy_selector.select_strategy(query)
        logger.info(f"选择的策略: {strategy}")
        retrieve_chunks = self.retrieve_and_merge(query, strategy, source_filter, partition=partition)
        context = "\n\n".join([chunk.page_content for chunk in retrieve_chunks])
        logger.info(f"从知识库中检索到的上下文信息: {context}")

        # 用 ContextBuilder 构建带 identity 的 messages
        messages = self.context_builder.build_messages(
            "answer_with_context",
            context=context,
            query=query,
            history=history,
        )
        return self._chat_with_messages(messages, stream=stream)

    # ─── LLM 调用辅助 ───────────────────────────

    def call_llm(self, prompt, stream=False, history: list = None):
        """通用 LLM 调用(用于闲聊路径,无知识库上下文)"""
        if not stream:
            return self.llm._call_llm_model(prompt, stream=False, history=history)
        return self._generator(prompt, history)

    def _generator(self, prompt, history: list = None):
        total_answer = []
        for token in self.llm._call_llm_model(prompt, stream=True, history=history):
            total_answer.append(token)
            yield total_answer

    def _chat_with_messages(self, messages: list, stream: bool = False):
        """直接基于 messages 调用 chat,用于 answer_with_context 等 ContextBuilder 构建的场景"""
        if not stream:
            try:
                return self.client.chat(
                    messages=messages,
                    model=self.chat_model,
                    stream=False,
                    temperature=0.8,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                return "抱歉，模型处理请求时发生了错误。"
        return self._generator_messages(messages)

    def _generator_messages(self, messages: list):
        total = []
        try:
            for token in self.client.chat(
                messages=messages,
                model=self.chat_model,
                stream=True,
                temperature=0.8,
                max_tokens=2048,
            ):
                total.append(token)
                yield total
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            yield ["抱歉，模型处理请求时发生了错误。"]

    # ─── 检索策略 ───────────────────────────────

    def retrieve_and_merge(self, query, strategy, source_filter=None, partition: str = None):
        if strategy == "假设问题检索":
            ranked_chunks = self._retrieve_with_hyde_strategy(query, source_filter, partition=partition)
        elif strategy == "子查询检索":
            ranked_chunks = self._retrieve_with_subquery_strategy(query, source_filter, partition=partition)
        elif strategy == "回溯问题检索":
            ranked_chunks = self._retrieve_with_backtracking_strategy(query, source_filter, partition=partition)
        else:
            ranked_chunks = self._retrieve_with_direct_strategy(query, source_filter, partition=partition)
        logger.info(f"使用策略 {strategy} 检索到 {len(ranked_chunks)} 条相关信息")
        return ranked_chunks

    def _retrieve_with_direct_strategy(self, query, source_filter, partition: str = None) -> list:
        try:
            return self.vector_store.hybrid_search_with_rerank(
                query=query,
                top_k=conf.retrieval_top_k,
                source_filter=source_filter,
                partition=partition,
            )
        except Exception as e:
            logger.error(f"RAG检索时发生错误: {e}")
            return []

    def _query_rewrite(self, skill: str, query: str) -> str:
        """用 ContextBuilder 加载的辅助 skill(hyde/subquery/backtracking)改写 query"""
        messages = self.context_builder.build_messages(skill, query=query)
        try:
            return self.client.chat(
                messages=messages,
                model=self.chat_model,
                stream=False,
                temperature=0.8,
                max_tokens=512,
            )
        except Exception as e:
            logger.error(f"{skill} 改写失败,回退原 query: {e}")
            return query

    def _retrieve_with_hyde_strategy(self, query, source_filter, partition: str = None):
        rewritten = self._query_rewrite("hyde", query)
        logger.info(f"生成的假设问题: {rewritten}")
        return self._retrieve_with_direct_strategy(query=rewritten, source_filter=source_filter, partition=partition)

    def _retrieve_with_subquery_strategy(self, query, source_filter, partition: str = None):
        rewritten = self._query_rewrite("subquery", query)
        subqueries = [s for s in rewritten.split("\n") if s.strip()]
        logger.info(f"生成的子查询: {subqueries}")
        if not subqueries:
            return []
        per_q = conf.candidate_top_k // len(subqueries) or 1
        ranked_chunks = []
        for subquery in subqueries:
            ranked_chunks.extend(
                self._retrieve_with_direct_strategy(
                    query=subquery, source_filter=source_filter, partition=partition
                )[:per_q]
            )
        seen = set()
        unique = []
        for chunk in ranked_chunks:
            key = chunk.metadata.get("id") or chunk.page_content
            if key not in seen:
                seen.add(key)
                unique.append(chunk)
        return unique

    def _retrieve_with_backtracking_strategy(self, query, source_filter, partition: str = None):
        rewritten = self._query_rewrite("backtracking", query)
        logger.info(f"生成的回溯问题: {rewritten}")
        return self._retrieve_with_direct_strategy(query=rewritten, source_filter=source_filter, partition=partition)


if __name__ == "__main__":
    rag = RAGSystem()
    res = rag.generate_answer("空气柱PCSEL的结构", force_retrieve=True)
    print(res)
