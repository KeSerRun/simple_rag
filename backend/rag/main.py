"""RAG CLI 入口 (query / add_document)"""
from base.config import conf
from base.logger import logger

from agent import RAGSystem
from rag.core.local_vector_store import VectorStore
from rag.core.openai_client import OpenAIClient


def main(mode: str = "query"):
    if mode == "query":
        rag_system = RAGSystem()
        while True:
            user_query = input("请输入您的问题（输入 exit 退出）：")
            logger.info(f"用户查询：{user_query}")
            if user_query.lower() == "exit":
                logger.info("退出查询模式。")
                break
            response = rag_system.generate_answer(user_query, force_retrieve=True)
            logger.info(f"RAG系统回答：{response}")

    if mode == "add_document":
        client = OpenAIClient(
            api_key=conf.openai_api_key, base_url=conf.openai_base_url,
            timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
        )
        vector_store = VectorStore(
            client=client,
            embedding_model=conf.openai_embedding_model,
            embedding_dim=conf.openai_embedding_dim,
        )
        directory = input(f"请输入文档目录路径：(default: {conf.vector_store_dir}) ")
        if not directory:
            directory = conf.vector_store_dir
        logger.info(f"开始从目录 {directory} 加载文档并存储到向量数据库。")
        vector_store.store_documents_from_dir(directory)
        logger.info("文档添加完成。")


if __name__ == "__main__":
    main()
