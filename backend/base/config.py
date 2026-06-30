# 导入配置解析模块
import configparser
# 导入路径操作模块
import os
# 导入系统模块
import sys

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
    path = config.get(section, option)
    return normalize_path(path)


def _strip_quotes(value: str) -> str:
    """去掉配置值首尾可能的成对引号(configparser 不会自动处理)"""
    if not value:
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value

class Config:
    # 初始化配置，加载 config.ini 文件
    def __init__(self, config_file=_config_file):
        config = configparser.ConfigParser()
        config.read(config_file, encoding='utf-8')

        # Storage 配置（文件存储路径）
        self.data_dir = get_file(config, 'storage', 'data_dir')
        self.vector_store_dir = get_file(config, 'storage', 'vector_store_dir')

        # RAG 检索配置
        self.parent_chunk_size = config.getint('retrieval', 'parent_chunk_size', fallback=100)
        self.child_chunk_size = config.getint('retrieval', 'child_chunk_size', fallback=20)
        self.chunk_overlap = config.getint('retrieval', 'chunk_overlap', fallback=10)
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)

        # 日志配置
        self.log_file = get_file(config, 'logger', 'log_file')
        self.log_file_level = config.get('logger', 'log_file_level', fallback='INFO')
        self.log_console_level = config.get('logger', 'log_console_level', fallback='DEBUG')
        self.log_file_format = '[%(levelname)s] %(asctime)s : %(message)s'
        self.log_console_format = '[%(levelname)s] %(asctime)s : %(message)s'

        # OpenAI API 配置 — Chat 端（环境变量优先）
        self.openai_api_key = os.environ.get('OPENAI_API_KEY') or _strip_quotes(config.get('api', 'api_key', fallback='')) or None
        self.openai_base_url = _strip_quotes(config.get('api', 'base_url', fallback='https://api.openai.com/v1')) or None
        self.chat_model = _strip_quotes(config.get('api', 'chat_model', fallback='gpt-4o-mini'))

        # OpenAI API 配置 — Embedding 端（可独立指向另一家服务商,留空则回退到 chat 端配置）
        self.embedding_api_key = (
            os.environ.get('OPENAI_EMBEDDING_API_KEY')
            or _strip_quotes(config.get('api', 'embedding_api_key', fallback=''))
            or self.openai_api_key
        )
        self.embedding_base_url = (
            _strip_quotes(config.get('api', 'embedding_base_url', fallback=''))
            or self.openai_base_url
        )
        self.openai_embedding_model = _strip_quotes(config.get('api', 'embedding_model', fallback='text-embedding-3-small'))
        self.openai_embedding_dim = config.getint('api', 'embedding_dim', fallback=1536)
        self.openai_timeout = config.getfloat('api', 'timeout', fallback=60.0)
        self.openai_max_retries = config.getint('api', 'max_retries', fallback=3)

        # 评估配置
        self.rag_evaluate_data = get_file(config, 'assessment', 'rag_evaluate_data')

        # 对话历史配置
        self.max_history_length = config.getint('conversation_history', 'max_history_length', fallback=10)

        # HTML主页配置
        self.index_file = get_file(config, 'html', 'index_file')

        # jwt配置
        self.jwt_secret_key = _strip_quotes(config.get('jwt', 'secret_key'))

        # superuser配置
        self.superuser_usernames = [u.strip() for u in config.get('superuser', 'users').split(',')]
        self.superuser_passwords = [p.strip() for p in config.get('superuser', 'passwords').split(',')]

        # MinerU 配置（PDF 高质量结构化解析；留空则回退到 OCRPDFLoader）
        self.mineru_token_key = (
            os.environ.get('MINERU_TOKEN_KEY')
            or _strip_quotes(config.get('mineru', 'token_key', fallback=''))
        )
        self.mineru_token_name = _strip_quotes(config.get('mineru', 'token_name', fallback='default'))
        self.mineru_model_version = _strip_quotes(config.get('mineru', 'model_version', fallback='vlm'))
        self.mineru_language = _strip_quotes(config.get('mineru', 'language', fallback='ch'))

# 创建全局配置实例，供其他模块使用
conf = Config()

if __name__ == "__main__":
    from rich import print
    print(conf.__dict__)
