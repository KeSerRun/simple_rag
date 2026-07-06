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


def _load_dotenv(path: str = None) -> dict[str, str]:
    """加载 .env 文件, 返回 {KEY: value} 字典。

    格式: KEY=VALUE, 支持 # 注释, 忽略空行。引号会被自动去除。
    """
    if path is None:
        path = os.path.join(_project_root, '.env')
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            value = _strip_quotes(value)
            if key and value:
                result[key] = value
    return result


class Config:
    # 初始化配置，加载 config.ini + .env 文件
    def __init__(self, config_file=_config_file):
        config = configparser.ConfigParser()
        config.read(config_file, encoding='utf-8')
        dotenv = _load_dotenv()

        def env(key: str) -> str | None:
            """优先级: 系统环境变量 > .env 文件 > 无。"""
            return os.environ.get(key) or dotenv.get(key) or None

        # Storage 配置（文件存储路径）
        self.data_dir = get_file(config, 'storage', 'data_dir')
        self.vector_store_dir = get_file(config, 'storage', 'vector_store_dir')

        # RAG 检索配置
        self.parent_chunk_size = config.getint('retrieval', 'parent_chunk_size', fallback=100)
        self.child_chunk_size = config.getint('retrieval', 'child_chunk_size', fallback=20)
        self.chunk_overlap = config.getint('retrieval', 'chunk_overlap', fallback=10)
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)

        # 日志配置（目录路径）
        self.log_path = normalize_path(config.get('logger', 'log_path', fallback='logs'))
        self.app_log_level = config.get('logger', 'app_log_level', fallback='INFO')
        self.http_log_level = config.get('logger', 'http_log_level', fallback='INFO')
        self.user_log_level = config.get('logger', 'user_log_level', fallback='INFO')
        self.console_log_level = config.get('logger', 'console_log_level', fallback='DEBUG')
        self.log_file_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'
        self.log_console_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'

        # OpenAI API 配置 — Chat 端（env > .env > config.ini）
        self.openai_api_key = (
            env('OPENAI_API_KEY')
            or _strip_quotes(config.get('api', 'chat_api_key', fallback=''))
            or _strip_quotes(config.get('api', 'api_key', fallback=''))
            or None
        )
        self.openai_base_url = (
            env('OPENAI_BASE_URL')
            or _strip_quotes(config.get('api', 'chat_base_url', fallback=''))
            or _strip_quotes(config.get('api', 'base_url', fallback='https://api.openai.com/v1'))
            or None
        )
        self.chat_model = _strip_quotes(config.get('api', 'chat_model', fallback='gpt-4o-mini'))

        # OpenAI API 配置 — Embedding 端
        self.embedding_api_key = (
            env('OPENAI_EMBEDDING_API_KEY')
            or _strip_quotes(config.get('api', 'embedding_api_key', fallback=''))
            or self.openai_api_key
        )
        self.embedding_base_url = (
            env('OPENAI_EMBEDDING_BASE_URL')
            or _strip_quotes(config.get('api', 'embedding_base_url', fallback=''))
            or self.openai_base_url
        )
        self.openai_embedding_model = _strip_quotes(config.get('api', 'embedding_model', fallback='text-embedding-3-small'))
        self.openai_embedding_dim = config.getint('api', 'embedding_dim', fallback=1536)
        self.openai_timeout = config.getfloat('api', 'timeout', fallback=60.0)
        self.openai_max_retries = config.getint('api', 'max_retries', fallback=3)
        self.chat_reasoning_effort = _strip_quotes(config.get('api', 'chat_reasoning_effort', fallback='')) or None

        # 对话历史配置
        self.max_history_length = config.getint('conversation_history', 'max_history_length', fallback=10)
        self.max_history_chars = config.getint('conversation_history', 'max_history_chars', fallback=10000)

        # 联网搜索配置
        self.search_backend = _strip_quotes(config.get('search', 'backend', fallback='duckduckgo'))
        self.searxng_url = _strip_quotes(config.get('search', 'searxng_url', fallback=''))
        self.bocha_api_key = (
            env('BOCHA_API_KEY')
            or _strip_quotes(config.get('search', 'bocha_api_key', fallback=''))
            or None
        )
        self.bing_api_key = (
            env('BING_API_KEY')
            or _strip_quotes(config.get('search', 'bing_api_key', fallback=''))
            or None
        )
        self.search_timeout = config.getfloat('search', 'timeout', fallback=15)

        # Agent 配置
        self.max_tool_iter = config.getint('agent', 'max_tool_iter', fallback=6)
        self.max_calls_per_tool = config.getint('agent', 'max_calls_per_tool', fallback=3)
        self.max_output_tokens = config.getint('agent', 'max_output_tokens', fallback=8192)

        # HTML主页文件路径（相对于 backend/ 根目录）
        self.index_file = normalize_path("dist/index.html")

        # jwt配置（优先 .env，否则自动生成）
        _jwt = env('JWT_SECRET_KEY')
        if not _jwt:
            import secrets as _sec
            _jwt = _sec.token_hex(32)
            # 写入 .env 文件以便后续持久化
            _env_path = os.path.join(_project_root, '.env')
            try:
                with open(_env_path, 'a', encoding='utf-8') as _f:
                    _f.write(f"\n# 自动生成的 JWT 密钥（如要更换请删除此行）\nJWT_SECRET_KEY={_jwt}\n")
                print(f"[config] 已自动生成 JWT_SECRET_KEY 并写入 {_env_path}")
            except Exception:
                pass  # 写入失败不影响运行
        self.jwt_secret_key = _jwt

        # superuser配置
        self.superuser_usernames = [u.strip() for u in config.get('superuser', 'users').split(',')]
        self.superuser_passwords = [p.strip() for p in config.get('superuser', 'passwords').split(',')]

        # MinerU 配置
        self.mineru_base_url = (
            env('MINERU_BASE_URL')
            or _strip_quotes(config.get('api', 'mineru_base_url', fallback='https://mineru.net/api/v4'))
        )
        self.mineru_api_key = (
            env('MINERU_API_KEY')
            or _strip_quotes(config.get('api', 'mineru_api_key', fallback=''))
        )
        self.mineru_token_name = _strip_quotes(config.get('api', 'mineru_token_name', fallback='default'))
        self.mineru_model_version = _strip_quotes(config.get('api', 'mineru_model_version', fallback='vlm'))
        self.mineru_language = _strip_quotes(config.get('api', 'mineru_language', fallback='ch'))

        # 上传限制配置
        self.max_user_storage_mb = config.getint('upload', 'max_user_storage_mb', fallback=10)

# 创建全局配置实例，供其他模块使用
conf = Config()

if __name__ == "__main__":
    from rich import print
    print(conf.__dict__)
