# 导入配置类
from base.config import conf
# 导入评估函数
from base.logger import logger
# 导入 MySQL 问答数据库操作类
from mysql_qa import MySQLQA
# 导入 RAG_QA 问答系统类
from rag_qa import RAGSystem
# 导入 uuid 模块用于生成唯一标识符
import uuid
# 导入时间模块用于记录时间戳
import time


'''集成系统类，结合 MySQL 问答数据库和 RAG_QA 问答系统，实现一个统一的问答接口'''
class IntegratedSystem:
    def __init__(self):
        # 初始化 MySQL 问答数据库
        self.mysql_qa = MySQLQA()
        # 初始化 MySQL 客户端
        self.mysql_client = self.mysql_qa.mysql_client
        # 初始化 Redis 客户端
        self.redis_client = self.mysql_qa.redis_client
        # 初始化 BM25 检索器
        self.bm25_retriever = self.mysql_qa.bm25_search
        # 初始化 RAG_QA 问答系统
        self.rag_qa = RAGSystem()
        # 初始化向量存储
        self.vector_store = self.rag_qa.vector_store

    def get_history(self, session_id):
            # 获取会话历史记录，供 RAG_QA 生成答案时参考
            history = self.mysql_client.get_session_history(session_id)
            # 限制历史记录长度，避免过长的历史影响模型性能
            if history and len(history) > conf.max_history_length:
                history = history[-conf.max_history_length:]
            # 格式化历史记录为模型输入的格式 [{"user": "问题", "assistant": "答案"},...]
            history = [[{'role':'user','content':h['user']},{'role':'assistant','content':h['assistant']}] for h in history]
            # [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"},...]
            history = [item for sublist in history for item in sublist]  # 将嵌套列表展开为单层列表
            # 返回历史记录
            return history

    def get_answer(self, session_id, question, partition:str=None):
        """处理用户查询，返回答案"""
        # 获取当前会话的历史记录，供 RAG_QA 生成答案时参考
        history = self.get_history(session_id)
        # 记录查询开始日志
        logger.info(f"收到查询: {question}")
        # 首先使用 BM25 检索器尝试获取答案
        answer, found = self.bm25_retriever.search(question)
        # 如果 BM25 检索到答案，则直接返回答案
        if found:
            # 记录 BM25 检索到答案的日志
            logger.info(f"BM25 检索到答案: {answer}")
        else:
            # 记录 BM25 未检索到答案的日志
            logger.info("BM25 未检索到答案，使用 RAG_QA 生成答案")
            # 使用 RAG_QA 生成答案，在所有Milvus的所有分区进行检索
            answer = self.rag_qa.generate_answer(question, stream=False, history=history, partition=partition)
            # 记录生成完成的日志
            logger.info(f"生成的回答: {answer}")
            # 仅仅保存高质量的问答对，避免过多无用数据占用数据库空间
            if len(answer) > 32:
                # 将问答对存储在 MySQL 数据库中
                self.mysql_client.insert_qa_pair(question, answer)
        # 将会话历史记录存储到 MySQL 数据库中，记录 session_id 以关联同一会话的问答对
        self.mysql_client.insert_session_history(session_id, question, answer)
        # 返回生成的答案
        return answer

    def answer_generator(self, session_id, question, partition:str=None):
        # 定义一个生成器函数，用于流式返回答案
        # 获取当前会话的历史记录，供 RAG_QA 生成答案时参考
        history = self.get_history(session_id)
        # 记录查询开始日志
        logger.info(f"收到查询: {question}")
        # 首先使用 BM25 检索器尝试获取答案
        answer, found = self.bm25_retriever.search(question)
        if found:
            # 记录 BM25 检索到答案的日志
            logger.info(f"BM25 检索到答案: {answer}")
            # 输出答案
            yield answer
        else:
            # 记录 BM25 未检索到答案的日志
            logger.info("BM25 未检索到答案，使用 RAG_QA 生成答案")
            # 使用 RAG_QA 生成答案，在所有Milvus的所有分区进行检索
            answer = self.rag_qa.generate_answer(question, stream=True, history=history, partition=partition)
            # 输出生成的答案
            for ans in answer:
                # 只发送最新生成的答案文本部分
                yield ans[-1]
            # 得到完整答案
            answer = ''.join(ans)
            # 生成完成后，记录生成完成的日志
            logger.info(f"生成的回答: {answer}")
            # 仅仅保存高质量的问答对，避免过多无用数据占用数据库空间
            if len(answer) > 32:
                # 将问答对存储在 MySQL 数据库中
                self.mysql_client.insert_qa_pair(question, answer)
            # 将会话历史记录存储到 MySQL 数据库中，记录 session_id 以关联同一会话的问答对
            self.mysql_client.insert_session_history(session_id, question, answer)

    def run(self, session_id):
        """运行集成系统，等待用户输入查询"""
        while True:
            # 获取用户输入
            question = input("请输入查询 (输入 'exit' 退出): ")
            # 如果用户输入 'exit'，则退出系统
            if question.lower() == 'exit':
                print("退出系统")
                break
            # 处理查询并获取答案
            answer = self.get_answer(session_id, question)
            # 输出答案
            print(f"答案: {answer}")

if __name__ == "__main__":
    # 创建集成系统实例
    system = IntegratedSystem()
    # 生成一个唯一的 session_id，用于关联同一会话的问答对
    session_id = str(uuid.uuid4())  
    # 运行集成系统
    system.run(session_id)