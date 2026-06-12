# 导入配置
from base.config import conf
# 导入 BM25 算法
from rank_bm25 import BM25Okapi
# 导入数值计算库
import numpy as np
# 导入文本预处理函数
from ..utils import preprocess
# 导入日志
from base.logger import logger
# 导入随机数模块
import random

class BM25Search:
    def __init__(self, redis_client, mysql_client):
        # 初始化 Redis 客户端
        self.redis_client = redis_client
        # 初始化 MySQL 客户端
        self.mysql_client = mysql_client
        # 初始化 BM25 模型
        self.bm25 = None
        # 初始化原始问题键名
        self.original_questions_key = 'qa_original_questions'
        # 初始化分词后问题键名
        self.tokenized_questions_key = 'qa_tokenized_questions'
        # 初始化问题列表
        self.questions = []
        # 初始化原始问题
        self.original_questions = []
        # 初始化分词后的问题
        self.tokenized_questions = []
        # 加载数据
        self._load_data()

    # 从 MySQL 数据库加载数据并缓存到 Redis 中，定期刷新数据以确保时效性
    def _load_data(self):
        # 刷新数据，从 Redis 获取数据，如果 Redis 中数据失效，则从 MySQL 数据库加载数据并缓存到 Redis 中
        self._refresh_data()
        # 确保有足够的数据来训练 BM25 模型
        if len(self.tokenized_questions) > 20:  
            self.bm25 = BM25Okapi(self.tokenized_questions)
        # 记录加载数据完成日志
        logger.info("BM25 数据加载完成")

    def _refresh_data(self):
        # 从 Redis 获取原始问题列表
        self.original_questions = self.redis_client.get(self.original_questions_key)
        # 从 Redis 获取分词后的问题列表
        self.tokenized_questions = self.redis_client.get(self.tokenized_questions_key)
        # 如果 Redis 中数据失效，则从 MySQL 数据库加载数据
        if self.original_questions is None or self.tokenized_questions is None:
            # 从 MySQL 数据库获取所有问题
            questions = self.mysql_client.fetch_all_questions()
            # 提取原始问题列表
            self.original_questions = [q['question'] for q in questions] 
            # 对原始问题进行分词预处理
            self.tokenized_questions = [preprocess.preprocess_text(q, info=False) for q in self.original_questions]
            # 定期更新缓存，确保数据的时效性
            expire_time = 60  # 设置缓存过期时间为 1 分钟, 即 1 分钟刷新一次数据
            # 将原始问题列表和分词后的问题列表存储到 Redis 中
            self.redis_client.set(self.original_questions_key, self.original_questions, ex=expire_time)
            self.redis_client.set(self.tokenized_questions_key, self.tokenized_questions, ex=expire_time)
            # 记录从 MySQL 加载数据并缓存到 Redis 的日志
            logger.info(f"从 MySQL 加载数据并缓存到 Redis, 共 {len(self.original_questions)} 条问题, 缓存过期时间: {expire_time} 秒")
            # 更新 BM25 模型
            # 确保有足够的数据来训练 BM25 模型
            if len(self.tokenized_questions) > 20:  
                self.bm25 = BM25Okapi(self.tokenized_questions)

    def _softmax(self, scores):
        """对 BM25 分数进行 softmax 归一化"""
        # 计算 Softmax 分数
        exp_scores = np.exp(scores - np.max(scores)) 
        # 返回归一化后的分数
        return exp_scores / np.sum(exp_scores)

    def search(self, query, threshold=conf.bm25_threshold):
        # 搜索查询
        if not query or not isinstance(query, str):
            # 记录无效查询输入日志
            logger.warning("无效的查询输入")
            # 返回 None 和 False
            return None, False
        # 检查 Redis 缓存
        cached_answer = self.redis_client.get(f"bm25_cache:{query}")
        if cached_answer:
            # 记录缓存命中日志
            logger.info("BM25 搜索命中缓存")
            # 返回缓存的答案和 True
            return cached_answer, True
        try:
            # 刷新 BM25 数据，确保数据的时效性
            self._refresh_data()
            if self.bm25 is None:
                # 如果 BM25 模型未初始化，记录警告日志并返回 None 和 False
                logger.warning("当前数据量过少，BM25 模型未初始化，无法进行搜索")
                return None, False
            # 对查询进行分词预处理
            tokenized_query = preprocess.preprocess_text(query)
            # 计算 BM25 分数
            scores = self.bm25.get_scores(tokenized_query)
            # 计算 Softmax 分数
            softmax_scores = self._softmax(scores)
            # 获取最高分数的索引
            best_idx = np.argmax(softmax_scores)
            # 获取最高分数
            best_score = softmax_scores[best_idx]
            # 如果最高分数超过阈值，则返回对应的问题和答案
            if best_score >= threshold:
                # 获取匹配的问题
                matched_question = self.original_questions[best_idx]
                # 从 MySQL 数据库获取对应的答案
                answer = self.mysql_client.fetch_answer_by_question(matched_question)
                if answer:
                    # 记录搜索成功日志
                    logger.info(f"BM25 搜索成功, score: {best_score:.4f}")
                    # 返回答案和 True
                    return answer, True
            # 记录搜索未找到合适答案日志
            logger.info(f"BM25 搜索未找到合适答案, best score: {best_score:.4f}")
            return None, False
        except Exception as e:
            logger.error(f"BM25 搜索失败: {e}")
            return None, False

if __name__ == "__main__":
    from mysql_qa.cache import redis_client
    from mysql_qa.db import mysql_client
    # 创建 Redis 客户端实例
    redis_client = redis_client.RedisClient()
    # 创建 MySQL 客户端实例
    mysql_client = mysql_client.MySQLClient()
    # 创建 BM25 搜索实例
    bm25_search = BM25Search(redis_client, mysql_client)
    # 测试搜索功能
    test_query = "live serve是什么,有什么作用？"
    answer, found = bm25_search.search(test_query)
    print(answer)