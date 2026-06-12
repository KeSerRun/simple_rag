# 导入日志解析器
import configparser
# 导入路径操作模块
import os
# 导入系统模块
import sys
# 导入随机数模块
import random

'''定义工程路径入口'''
# 获取当前配置文件所在目录
_config_dir = os.path.dirname(os.path.abspath(__file__))

# 获取项目根目录路径
_project_root = os.path.dirname(_config_dir)

# 定义配置文件路径
_config_file = os.path.join(_project_root, 'config.ini')

# 将项目根目录添加到系统路径中，确保其他模块可以正确导入
sys.path.append(_project_root)

# 定义函数，规范化路径，将相对路径转换为绝对路径
def normalize_path(path:str) -> str:
    # 如果路径是绝对路径，直接返回；如果是相对路径，则将其与项目根目录拼接成绝对路径
    path = os.path.isabs(path) and path or os.path.join(_project_root, path)
    # 将路径中的反斜杠替换为正斜杠，确保在不同操作系统上的兼容性
    path = path.replace('\\', '/')  
    return path

# 定义函数，从配置文件中获取指定路径，并规范化路径
def get_file(config:configparser.ConfigParser, section:str, option:str) -> str:
    # 从配置文件中获取指定路径，并规范化路径
    path = config.get(section, option)
    # 规范化路径，确保路径正确无误
    return normalize_path(path)

class Config:
    # 初始化配置，加载 config.ini 文件
    def __init__(self, config_file=_config_file):
        # 创建配置解析器
        config = configparser.ConfigParser()
        # 读取配置文件
        config.read(config_file, encoding='utf-8')

        # MySQL 配置
        # MySQL 主机地址,默认为 localhost
        self.mysql_host = config.get('mysql', 'host', fallback='localhost')
        # MySQL 端口号
        self.mysql_port = config.getint('mysql', 'port', fallback=3306)
        # MySQL 用户名
        self.mysql_user = config.get('mysql', 'user', fallback='root')
        # MySQL 密码
        self.mysql_password = config.get('mysql', 'password', fallback='')
        # MySQL 数据库名称
        self.mysql_database = config.get('mysql', 'database', fallback='')

        # Redis 配置
        # Redis 主机地址
        self.redis_host = config.get('redis', 'host', fallback='localhost')
        # Redis 端口号
        self.redis_port = config.getint('redis', 'port', fallback=6379)
        # Redis 密码
        self.redis_password = config.get('redis', 'password', fallback=None)
        # Redis 数据库索引
        self.redis_db = config.getint('redis', 'db', fallback=0)

        # Milvus 配置
        # Milvus 主机地址
        self.milvus_host = config.get('milvus', 'host', fallback='localhost')
        # Milvus 端口号
        self.milvus_port = config.getint('milvus', 'port', fallback=19530)
        # Milvus 数据库名称
        self.milvus_database = config.get('milvus', 'database', fallback='qa')
        # Milvus 集合名称
        self.milvus_collection = config.get('milvus', 'collection', fallback='qa_collection')
        # Milvus 向量维度
        self.milvus_dimension = config.getint('milvus', 'vector_dim', fallback=128)
        # Milvus 向量距离度量方式
        self.milvus_metric_type = config.get('milvus', 'metric_type', fallback='COSINE')
        # Milvus 索引类型
        self.milvus_index_type = config.get('milvus', 'index_type', fallback='IVF_FLAT')
        # Milvus 向量存储的文档路径
        self.milvus_vector_store_path = get_file(config, 'milvus', 'vector_store_path')

        # RAG 检索配置
        # 父块切分大小
        self.parent_chunk_size = config.getint('retrieval', 'parent_chunk_size', fallback=100)
        # 子块切分大小
        self.child_chunk_size = config.getint('retrieval', 'child_chunk_size', fallback=20)
        # 块重叠大小
        self.chunk_overlap = config.getint('retrieval', 'chunk_overlap', fallback=10)
        # 检索结果数量
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        # 候选结果数量
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)
        # 混合检索中稠密向量的权重
        self.dense_weight = config.getfloat('retrieval', 'dense_weight', fallback=1.0)
        # 混合检索中稀疏向量的权重
        self.sparse_weight = config.getfloat('retrieval', 'sparse_weight', fallback=0.7)

        # 日志配置
        # 日志文件路径
        self.log_file = get_file(config, 'logger', 'log_file')
        # 文件日志级别
        self.log_file_level = config.get('logger', 'log_file_level', fallback='INFO')
        # 控制台日志级别
        self.log_console_level = config.get('logger', 'log_console_level', fallback='DEBUG')
        # 文件日志格式
        self.log_file_format = '[%(levelname)s] %(asctime)s : %(message)s'
        # 控制台日志格式
        self.log_console_format = '[%(levelname)s] %(asctime)s : %(message)s'

        # 数据文件配置
        # 数据文件路径
        self.data_file = get_file(config, 'qa_data', 'qa_data_file')
        # 数据列名
        self.class_head_name = config.get('qa_data', 'class_head_name')
        self.question_head_name = config.get('qa_data', 'question_head_name')
        self.answer_head_name = config.get('qa_data', 'answer_head_name')

        # BM25 配置
        # BM25 搜索相似度阈值
        self.bm25_threshold = config.getfloat('bm25', 'similarity_threshold', fallback=0.85)

        # model 配置
        self.segment_model = get_file(config, 'model', 'segment_model')
        # BGE-Reranker 重排序模型路径
        self.reranker_model = get_file(config, 'model', 'reranker_model')
        # BGE-M3 词嵌入模型路径
        self.embedding_model = get_file(config, 'model', 'embedding_model')
        # Qwen2.5-1.5B-Instruct 检索策略选择模型路径
        self.strategy_selector_model = get_file(config, 'model', 'strategy_selector_model')
        # LLM 模型路径
        self.llm_model = get_file(config, 'model', 'llm_model')

        # 意图识别训练数据配置
        # BERT-BASE-CHINESE 预训练模型路径
        self.query_classifier_pretrained = get_file(config, 'query_classifier', 'query_classifier_pretrained')
        # BERT-BASE-CHINESE 分类器
        self.query_classifier_model = get_file(config, 'query_classifier', 'query_classifier_model')
        # BERT 训练数据文件路径
        self.query_classifier_train_data_file = get_file(config, 'query_classifier', 'query_classifier_train_data_file')
        # BERT 评估数据文件路径
        self.query_classifier_eval_data_file = get_file(config, 'query_classifier', 'query_classifier_eval_data_file')
        # BERT 训练标签列表
        self.query_classifier_label_list = [label.strip() for label in config.get('query_classifier', 'query_classifier_labels').split(',')]

        # 评估配置
        # RAGAS 评估数据文件路径
        self.rag_evaluate_data = get_file(config, 'assessment', 'rag_evaluate_data')

        # 对话历史配置
        # 最大历史记录长度
        self.max_history_length = config.getint('conversation_history', 'max_history_length', fallback=10)

        # HTML主页配置
        # HTML主页文件路径
        self.index_file = get_file(config, 'html', 'index_file')

        # jwt配置
        # jwt密钥
        self.jwt_secret_key = config.get('jwt', 'secret_key')

        # superuser配置
        # 超级管理员用户名
        self.superuser_usernames = [username.strip() for username in config.get('superuser', 'users').split(',')]
        # 超级管理员密码
        self.superuser_passwords = [password.strip() for password in config.get('superuser', 'passwords').split(',')]

# 创建全局配置实例，供其他模块使用
conf = Config()   

if __name__ == "__main__":
    from rich import print
    print(conf.__dict__)