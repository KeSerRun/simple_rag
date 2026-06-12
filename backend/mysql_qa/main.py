# 导入 MySQL 客户端
from .db import mysql_client
# 导入 Redis 客户端
from .cache import redis_client
# 导入 BM25搜索模块
from .retrieval import bm25_search
# 导入日志
from base.logger import logger
# 导入时间模块
import time

class MySQLQA:
    def __init__(self):
        # 初始化 MySQL 客户端
        self.mysql_client = mysql_client.MySQLClient()
        # 初始化 Redis 客户端
        self.redis_client = redis_client.RedisClient()
        # 初始化 BM25 搜索模块
        self.bm25_search = bm25_search.BM25Search(self.redis_client, self.mysql_client)
    
    def query(self, question):
        """处理用户查询，返回答案"""
        # 记录查询开始日志
        logger.info(f"收到查询: {question}")
        # 记录查询开始时间
        start_time = time.time()
        # 使用 BM25 搜索获取答案
        answer, found = self.bm25_search.search(question)
        # 记录查询结束时间
        end_time = time.time()
        # 记录查询完成日志
        if found:
            logger.info(f"查询完成，找到答案: {answer} (耗时: {end_time - start_time:.2f}秒)")
            return answer
        else:
            logger.warning(f"查询完成，未找到答案 (耗时: {end_time - start_time:.2f}秒)")
            return "抱歉，我无法回答这个问题。"

def main():
    # 初始化问答系统
    qa_system = MySQLQA()
    try:
        # 模拟用户查询
        while True:
            user_input = input("请输入您的问题（输入 'exit' 退出）：")
            if user_input.lower() == 'exit':
                logger.info("用户退出系统")
                break
            response = qa_system.query(user_input)
            print(f"回答: {response}")
    except KeyboardInterrupt:
        logger.info("用户通过键盘中断退出系统")

if __name__ == "__main__":
    main()