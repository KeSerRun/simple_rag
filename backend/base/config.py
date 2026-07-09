# ===== 导入标准库模块 =====
import configparser
import os
import sys

# ===== 定义项目路径 =====
_config_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_config_dir)
_config_file = os.path.join(_project_root, 'config.ini')
sys.path.append(_project_root)

# ===== 路径规范化函数 =====
def normalize_path(path:str) -> str:
    path = os.path.isabs(path) and path or os.path.join(_project_root, path)
    path = path.replace('\\', '/')
    return path

# ===== 配置文件读取函数 =====
def get_file(config:configparser.ConfigParser, section:str, option:str) -> str:
    path = config.get(section, option)
    return normalize_path(path)

# ===== 引号去除工具函数 =====
def _strip_quotes(value: str) -> str:
    if not value:
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value

# ===== .env 文件加载函数 =====
def _load_dotenv(path: str = None) -> dict[str, str]:
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


# ===== 配置类定义 =====
class Config:

    def __init__(self, config_file=_config_file):
        self._config_file = config_file
        self._load_config()          # 从 ini/.env/环境变量加载全部配置
        self._init_runtime()         # 运行时一次性初始化（JWT 密钥等）
        self._update_config_hash()   # 记录 config.ini 文件 hash

    # ── 配置加载（可重复执行，用于热重载） ───────────────────

    def _load_config(self):
        """从 config.ini + .env + 系统环境变量加载所有配置项。"""
        config = configparser.ConfigParser()
        config.read(self._config_file, encoding='utf-8')
        dotenv = _load_dotenv()

        def env(key: str) -> str | None:
            """优先级: 系统环境变量 > .env 文件 > 无。"""
            return os.environ.get(key) or dotenv.get(key) or None

        # ===== Storage =====
        self.data_dir = get_file(config, 'storage', 'data_dir')
        self.vector_store_dir = get_file(config, 'storage', 'vector_store_dir')
        self.storage_backend = _strip_quotes(config.get('storage', 'backend', fallback='json'))

        # ===== Retrieval =====
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)
        self.min_chunk_length = config.getint('retrieval', 'min_chunk_length', fallback=5)
        raw_stop = _strip_quotes(config.get('retrieval', 'stop_words', fallback=''))
        self.stop_words = [w.strip() for w in raw_stop.split(',') if w.strip()] if raw_stop else []

        # ===== Logger =====
        self.log_path = normalize_path(config.get('logger', 'log_path', fallback='logs'))
        self.app_log_level = config.get('logger', 'app_log_level', fallback='INFO')
        self.http_log_level = config.get('logger', 'http_log_level', fallback='INFO')
        self.user_log_level = config.get('logger', 'user_log_level', fallback='INFO')
        self.console_log_level = config.get('logger', 'console_log_level', fallback='DEBUG')
        self.log_file_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'
        self.log_console_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'

        # ===== API — Chat =====
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

        # ===== API — Embedding =====
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

        # ===== Conversation History =====
        self.max_history_length = config.getint('conversation_history', 'max_history_length', fallback=10)
        self.max_history_chars = config.getint('conversation_history', 'max_history_chars', fallback=10000)

        # ===== Search =====
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

        # ===== Agent =====
        self.max_tool_iter = config.getint('agent', 'max_tool_iter', fallback=6)
        self.max_output_tokens = config.getint('agent', 'max_output_tokens', fallback=8192)
        self.parse_workers = config.getint('agent', 'parse_workers', fallback=3)
        self.tool_call_workers = config.getint('agent', 'tool_call_workers', fallback=4)

        # ===== Superuser =====
        self.superuser_usernames = [u.strip() for u in config.get('superuser', 'users').split(',')]
        self.superuser_passwords = [p.strip() for p in config.get('superuser', 'passwords').split(',')]

        # ===== MinerU =====
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

        # ===== Upload =====
        self.max_user_storage_mb = config.getint('upload', 'max_user_storage_mb', fallback=10)

    def _init_runtime(self):
        """运行时一次性初始化（JWT 密钥生成等，不随热重载重复执行）。"""
        self.index_file = normalize_path("dist/index.html")

        # JWT 密钥：优先环境变量/.env，没有则自动生成并写入 .env
        _jwt = os.environ.get('JWT_SECRET_KEY') or _load_dotenv().get('JWT_SECRET_KEY')
        if not _jwt:
            import secrets as _sec
            _jwt = _sec.token_hex(32)
            _env_path = os.path.join(_project_root, '.env')
            try:
                with open(_env_path, 'a', encoding='utf-8') as _f:
                    _f.write(f"\n# 自动生成的 JWT 密钥（如要更换请删除此行）\nJWT_SECRET_KEY={_jwt}\n")
                print(f"[config] 已自动生成 JWT_SECRET_KEY 并写入 {_env_path}")
            except Exception:
                pass
        self.jwt_secret_key = _jwt

    # ── Hash 热重载 ─────────────────────────────────

    def _update_config_hash(self):
        """用 config.ini 文件内容的 MD5 更新 _config_hash。"""
        import hashlib
        try:
            with open(self._config_file, 'rb') as f:
                self._config_hash = hashlib.md5(f.read()).hexdigest()
        except Exception:
            self._config_hash = ""

    def reload_if_changed(self):
        """如果 config.ini 文件已变更，自动重新加载全部配置项。

        策略: 比较当前文件 MD5 与上次记录的 hash。
        不一致时重新执行 _load_config()，覆盖所有 ini/.env/环境变量来源的属性。
        """
        import hashlib
        try:
            with open(self._config_file, 'rb') as f:
                new_hash = hashlib.md5(f.read()).hexdigest()
        except Exception:
            return  # 文件不可读则跳过
        if new_hash == self._config_hash:
            return  # 无变更

        from base.logger import logger
        logger.info(f"检测到配置变更 (hash: {self._config_hash[:8]} → {new_hash[:8]})，自动重载")
        self._load_config()
        self._config_hash = new_hash


# ===== 全局配置实例 =====
conf = Config()

if __name__ == "__main__":
    from rich import print
    print(conf.__dict__)
