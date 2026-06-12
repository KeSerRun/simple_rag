# 导入配置类
from base.config import conf
# 导入日志 
from base.logger import logger
# 导入提示词模板
from .prompts import RAGPrompts
# 导入查询分类器
from .query_classifier import QueryClassifier
# 导入检索策略选择器
from .strategy_selector import StrategySelector
# 导入向量存储模块
from .vector_store import VectorStore
# 导入 LLM 模型
from .llm import LLMModel
# 导入 Pytorch 模块
import torch

# 定义 RAG 系统类，封装 RAG 系统的基本参数
class RAGSystem:
    def __init__(self,query_classifier_model=None, # 查询分类器模型路径
                 strategy_selector_model=None,  # 检索策略选择模型路径
                 embedding_model=None,  # 向量存储使用的词嵌入模型路径
                 reranker_model=None,   # 向量存储使用的重排序模型路径
                 llm_model=None,        # LLM 模型路径
                 classifier_label_list=None):   # 查询分类器标签列表
        # 查询分类器模型路径
        self.query_classifier_model = query_classifier_model or conf.query_classifier_model   
        # 检索策略选择模型路径  
        self.strategy_selector_model = strategy_selector_model or conf.strategy_selector_model
        # 向量存储使用的词嵌入模型路径   
        self.embedding_model = embedding_model or conf.embedding_model
        # 向量存储使用的重排序模型路径  
        self.reranker_model = reranker_model or conf.reranker_model
        # LLM 模型路径     
        self.llm_model = llm_model or conf.llm_model  
        # 初始化提示词模板
        self.rag_prompts = RAGPrompts()
        # 查询分类器标签列表
        self.classifier_label_list = classifier_label_list or conf.query_classifier_label_list
        # 初始化查询分类器
        self.query_classifier = QueryClassifier(model_path=self.query_classifier_model, label_list=self.classifier_label_list,device='cpu')
        # 记录查询分类器加载完成的日志
        logger.info(f"查询分类器初始化完成，使用模型：{self.query_classifier_model}，使用设备: {self.query_classifier.device}")
        # 初始化检索策略选择器
        self.strategy_selector = StrategySelector(model_path=self.strategy_selector_model, device='cpu')
        # 记录检索策略选择器加载完成的日志
        logger.info(f"策略选择器模型加载完成，使用模型：{self.strategy_selector_model}，使用设备: {self.strategy_selector.device}")
        # 初始化向量存储
        self.vector_store = VectorStore(embedding_model=self.embedding_model, reranker_model=self.reranker_model)
        # 初始化 LLM 模型
        self.llm = LLMModel(model_path=self.llm_model,device='cuda' if torch.cuda.is_available() else 'cpu')
        # 记录 LLM 模型加载完成的日志
        logger.info(f"LLM 模型加载完成，使用模型：{self.llm_model}，使用设备: {self.llm.device}")

    def call_llm(self, prompt, stream=False, history:list=None):
        '''调用 LLM 模型生成答案，支持流式输出'''
        if not stream:
            # 调用 LLM 模型生成答案
            answer = self.llm._call_llm_model(prompt, stream=stream, history=history)
            # 返回生成的答案
            return answer
        else:
            # 否则返回一个生成器，逐步生成答案并输出
            return self.generater(prompt, history)

    def generater(self, prompt, history:list = None):
        # 初始化一个列表来存储生成的答案的每个 token
        total_answer = []
        # 启用流式输出，逐步生成答案并输出
        for token in self.llm._call_llm_model(prompt, stream=True, history=history):
            # 将生成的 token 添加到 total_answer 列表中
            total_answer.append(token)
            # 每生成一个 token 就输出当前的答案
            yield total_answer

    # 定义问答接口，接受用户输入的查询，并返回生成的答案
    def generate_answer(self, query, force_retrieve: bool = False, source_filter=None, stream=False, history:list=None, partition:str=None):
        '''
        query: 用户输入的查询文本
        force_retrieve: 是否强制进行检索，默认为 False，如果为 True 则无论查询分类结果如何都进行检索
        source_filter: 可选的来源过滤器，用于限制检索结果的来源
        stream: 是否启用流式输出，默认为 False
        history: 会话历史记录列表，供生成答案时参考
        partition: 分区标识，用于确定检索范围
        '''
        logger.info(f"收到用户查询: {query}")
        # 如果查询的是通用知识
        if  not force_retrieve:  
            try:
                # 判断查询类型
                query_category = self.query_classifier.predict(query)
                # 记录查询分类结果
                logger.info(f"查询分类结果: {query_category}")
                # 如果查询分类结果是通用知识，则直接使用 LLM 模型生成答案，不进行检索
                if query_category == self.classifier_label_list[1]:
                    # 格式化提示词
                    prompt = self.rag_prompts.context_prompt().format(query=query, context="")
                    return self.call_llm(prompt, stream=stream, history=history)
            except Exception as e:
                # 记录错误日志
                logger.error(f"生成答案时发生错误: {e}")
                # 发生错误时返回默认的错误提示
                return "抱歉，我无法生成答案。"

        # 选择检索策略: "直接检索", "假设问题检索", "子查询检索", "回溯问题检索"
        strategy = self.strategy_selector.select_strategy(query)
        # 记录选择的策略
        logger.info(f"选择的策略: {strategy}")
        # 根据选择的策略进行检索，并融合检索结果生成最终答案
        retrieve_chunks = self.retrieve_and_merge(query, strategy, source_filter, partition=partition)
        # 构建上下文
        context = "\n\n".join([chunk.page_content for chunk in retrieve_chunks])
        # 记录检索到的上下文信息
        logger.info(f"从知识库中检索到的上下文信息: {context}")
        # 构建上下文提示词
        prompt = self.rag_prompts.context_prompt().format(query=query, context=context)
        # 调用 LLM 模型生成答案
        return self.call_llm(prompt, stream=stream, history=history)

    '''根据选择的策略进行检索，并将检索结果与用户查询进行融合，生成最终答案'''
    def retrieve_and_merge(self,query,strategy,source_filter=None, partition:str=None):
        '''
        query: 用户输入的查询文本
        strategy: 选择的检索策略
        source_filter: 可选的来源过滤器，用于限制检索结果的来源
        partition: 分区标识，用于确定检索范围
        '''
        # 根据选择的策略进行检索
        if strategy == "假设问题检索":
            ranked_chunks = self._retrieve_with_hyde_strategy(query, source_filter, partition=partition)
        elif strategy == "子查询检索":
            ranked_chunks = self._retrieve_with_subquery_strategy(query, source_filter, partition=partition)
        elif strategy == "回溯问题检索":
            ranked_chunks = self._retrieve_with_backtracking_strategy(query, source_filter, partition=partition)
        else:   # 默认使用直接检索策略
            ranked_chunks = self._retrieve_with_direct_strategy(query, source_filter, partition=partition)
        # 记录检索结果数量
        logger.info(f"使用策略 {strategy} 检索到 {len(ranked_chunks)} 条相关信息")
        # 返回检索结果
        return ranked_chunks

    '''直接检索策略: 直接使用用户查询进行检索'''
    def _retrieve_with_direct_strategy(self, query, source_filter, partition:str=None)-> list:
        # 使用向量存储进行检索，获取相关的文本块
        try:
            ranked_chunks = self.vector_store.hybrid_search_with_rerank(
                query=query,
                top_k=conf.retrieval_top_k,
                source_filter=source_filter,
                partition=partition
            )
            return ranked_chunks
        except Exception as e:
            # 记录错误日志
            logger.error(f"RAG检索时发生错误: {e}")
            # 发生错误时返回空列表
            return []

    '''假设问题检索策略: 先生成一个相关的假设问题，然后使用这个假设问题进行检索'''
    def _retrieve_with_hyde_strategy(self, query, source_filter, partition:str=None):
        # 获取假设问题生成的提示词
        hyde_prompt = self.rag_prompts.hyde_prompt().format(query=query)
        # 调用 LLM 模型生成假设问题
        query = self.llm._call_llm_model(hyde_prompt)
        logger.info(f"生成的假设问题: {query}")
        # 使用生成的假设问题进行检索，调用直接检索策略的方法
        return self._retrieve_with_direct_strategy(query=query, source_filter=source_filter, partition=partition)

    '''子查询检索策略: 先生成一个或多个相关的子查询，然后使用这些子查询进行检索，并将结果融合'''
    def _retrieve_with_subquery_strategy(self, query, source_filter, partition:str=None):
        # 获取子查询提示词模板
        subquery_prompt = self.rag_prompts.subquery_prompt().format(query=query)
        # 调用 LLM 模型生成一个或多个子查询，子查询之间用 "\n" 分隔
        subqueries = self.llm._call_llm_model(subquery_prompt).split("\n")
        logger.info(f"生成的子查询: {subqueries}")
        # 子检索结果数量
        candidate_top_k_per_subquery = conf.candidate_top_k // len(subqueries) or 1
        # 初始化一个列表来存储所有子查询的检索结果
        ranked_chunks = []
        # 遍历每一个子查询
        for subquery in subqueries:
            # 使用每个子查询进行检索，调用直接检索策略的方法，并将结果添加到 ranked_chunks 列表中
            ranked_chunks.extend(self._retrieve_with_direct_strategy(query=subquery, source_filter=source_filter, partition=partition)[:candidate_top_k_per_subquery])
        # 基于子查询结果进行去重，避免返回重复的文本块
        unique_chunks = list({chunk.metadata['id']: chunk for chunk in ranked_chunks}.values())
        # 只返回排名前 conf.candidate_top_k 的结果，避免返回过多的冗余信息
        return unique_chunks

    '''回溯问题检索策略: 先生成一个相关的回溯问题，然后使用这个回溯问题进行检索'''
    def _retrieve_with_backtracking_strategy(self, query, source_filter, partition:str=None):
        # 生成回溯问题提示词
        backtracking_prompt = self.rag_prompts.backtracking_prompt().format(query=query)
        # 调用 LLM 模型生成回溯问题
        query = self.llm._call_llm_model(backtracking_prompt)
        logger.info(f"生成的回溯问题: {query}")
        # 调用 LLM 模型使用这个回溯问题进行检索
        return self._retrieve_with_direct_strategy(query=query, source_filter=source_filter, partition=partition)

if __name__ == "__main__":
    rag = RAGSystem()
    res = rag.generate_answer("空气柱PCSEL的结构", force_retrieve=True)
    print(res)