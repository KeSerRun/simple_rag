# 导入配置类
from base.config import conf
# 导入日志
from base.logger import logger
# 导入 JSON 持久化存储
from storage import JSONFileStore
# 导入 RAG_QA 问答系统类
from rag_qa import RAGSystem
# 导入 uuid 模块用于生成唯一标识符
import uuid


'''集成系统类，封装数据存储 + RAG_QA,提供统一的问答接口'''
class IntegratedSystem:
    def __init__(self):
        # 数据存储（用户/会话/历史 JSON 文件版）
        self.data_store = JSONFileStore()
        # 初始化 RAG_QA 问答系统
        self.rag_qa = RAGSystem()
        # 初始化向量存储
        self.vector_store = self.rag_qa.vector_store

    def get_history(self, session_id):
        # 获取会话历史记录,供 RAG_QA 生成答案时参考
        history = self.data_store.get_session_history(session_id)
        # 限制历史记录长度,避免过长的历史影响模型性能
        if history and len(history) > conf.max_history_length:
            history = history[-conf.max_history_length:]
        # 格式化历史记录为模型输入的格式
        history = [[{'role': 'user', 'content': h['user']},
                    {'role': 'assistant', 'content': h['assistant']}] for h in (history or [])]
        # 展开为单层列表
        history = [item for sublist in history for item in sublist]
        return history

    def get_answer(self, session_id, question, partition: str = None):
        """处理用户查询,返回答案"""
        history = self.get_history(session_id)
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer = self.rag_qa.generate_answer(question, stream=False, history=history, partition=partition)
        logger.info(f"生成的回答: {answer}")
        # 将会话历史记录存储,记录 session_id 以关联同一会话的问答对
        self.data_store.insert_session_history(session_id, question, answer)
        return answer

    def answer_generator(self, session_id, question, partition: str = None):
        """流式返回答案的生成器"""
        history = self.get_history(session_id)
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer_iter = self.rag_qa.generate_answer(question, stream=True, history=history, partition=partition)
        ans = []
        for chunk in answer_iter:
            # generater() 每次 yield 的是累积 token 列表,取最新增量
            ans = chunk
            yield chunk[-1]
        answer = ''.join(ans)
        logger.info(f"生成的回答: {answer}")
        # 将会话历史记录存储
        self.data_store.insert_session_history(session_id, question, answer)

    def run(self, session_id):
        """运行集成系统,等待用户输入查询"""
        while True:
            question = input("请输入查询 (输入 'exit' 退出): ")
            if question.lower() == 'exit':
                print("退出系统")
                break
            answer = self.get_answer(session_id, question)
            print(f"答案: {answer}")


if __name__ == "__main__":
    system = IntegratedSystem()
    session_id = str(uuid.uuid4())
    system.run(session_id)
