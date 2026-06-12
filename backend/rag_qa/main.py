# 导入配置模块
from base.config import conf
# 导入日志模块
from base.logger import logger
# 导入向量存储模块
from .core.vector_store import VectorStore
# 导入RAG系统模块
from .core.rag_system import RAGSystem

def main(mode:str="query"):
    '''
    主函数，负责启动RAG系统的不同模式
    :param mode: 运行模式，默认为"query"，可选"add_document"
    '''
    if mode == "query":
        # 初始化RAG系统
        rag_system = RAGSystem(
            query_classifier_model=conf.query_classifier_model,  # 使用配置文件中的查询分类器模型路径
            strategy_selector_model=conf.strategy_selector_model,  # 使用配置文件中的检索策略选择模型路径
            embedding_model=conf.embedding_model,   # 使用配置文件中的嵌入模型
            reranker_model=conf.reranker_model,  # 使用配置文件中的重排序模型
            llm_model=conf.llm_model,    # 使用配置文件中的LLM模型路径
            classifier_label_list=conf.query_classifier_label_list  # 使用配置文件中的查询分类器标签列表
        )
        # 进入查询模式
        while True:
            # 提示用户输入查询问题
            user_query = input("请输入您的问题（输入exit退出）：")
            # 记录用户查询日志
            logger.info(f"用户查询：{user_query}")
            # 如果用户输入exit，退出查询模式
            if user_query.lower() == "exit":
                # 记录退出日志
                logger.info("退出查询模式。")
                break
            # 生成RAG系统的回答
            response = rag_system.generate_answer(user_query,force_retrieve=True)
            # 记录RAG系统回答日志
            logger.info(f"RAG系统回答：{response}")
    if mode == "add_document":
        # 进入添加文档模式
        vector_store = VectorStore(
            embedding_model=conf.embedding_model,   # 使用配置文件中的嵌入模型
            reranker_model=conf.reranker_model  # 使用配置文件中的重排序模型
            )
        # 从指定目录加载文档并存储到向量数据库
        directory = input(f"请输入文档目录路径：(default: {conf.milvus_vector_store_path}) ")
        if not directory:
            directory = conf.milvus_vector_store_path
        # 记录日志
        logger.info(f"开始从目录 {directory} 加载文档并存储到向量数据库。")
        vector_store.store_documents_from_dir(directory)
        logger.info("文档添加完成。")