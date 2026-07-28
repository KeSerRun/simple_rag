# ── 配置管理模块 ──────────────────────────────────────────────────
"""RAG Simple 配置管理。

提供统一的配置加载机制：从 config.ini、.env 文件及系统环境变量
三层叠加加载所有运行时配置项，支持热重载与启动时校验。
"""

import configparser
import os
import sys


# ── 项目路径初始化 ────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：根目录就是 exe 所在目录
    _project_root = os.path.dirname(sys.executable)
else:
    _config_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_config_dir)
_config_file = os.path.join(_project_root, 'config.ini')
sys.path.append(_project_root)


# ── 路径工具函数 ──────────────────────────────────────────────────

def normalize_path(path: str) -> str:
    """将相对路径标准化为基于项目根目录的绝对路径。

    Args:
        path: 原始路径（绝对路径保持不变，相对路径拼接项目根目录）。

    Returns:
        标准化后的路径，使用正斜杠分隔。
    """
    path = os.path.isabs(path) and path or os.path.join(_project_root, path)
    path = path.replace('\\', '/')
    return path


def get_file(config: configparser.ConfigParser, section: str, option: str) -> str:
    """从配置文件中读取文件路径并标准化。

    Args:
        config: ConfigParser 实例。
        section: 配置节名称。
        option: 配置项名称。

    Returns:
        标准化后的绝对路径。
    """
    path = config.get(section, option)
    return normalize_path(path)


# ── 环境变量解析工具 ──────────────────────────────────────────────

def _strip_quotes(value: str) -> str:
    """去除字符串首尾匹配的引号。

    Args:
        value: 原始字符串。

    Returns:
        去除引号后的字符串。
    """
    if not value:
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_dotenv(path: str = None) -> dict[str, str]:
    """解析 .env 文件为键值字典。

    Args:
        path: .env 文件路径，默认使用项目根目录下的 .env。

    Returns:
        解析得到的键值对字典，空文件返回空 dict。
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


# ── 配置类 ────────────────────────────────────────────────────────

class Config:
    """全局配置管理器，从三层来源（config.ini / .env / 系统环境变量）加载所有配置。

    支持热重载：调用 reload_if_changed() 可在运行时检测配置文件变更并重新加载。

    Attributes:
        data_dir: 数据存储根目录。
        vector_store_dir: 向量索引文件目录。

        retrieval_top_k: 检索返回 Top-K 条数。
        candidate_top_k: 检索候选集大小。
        min_chunk_length: 最短分块字符数。
        log_path: 日志文件输出目录。
        app_log_level: 应用日志级别。
        console_log_level: 控制台日志级别。
        user_log_level: 用户操作日志级别。
        log_file_format: 文件日志格式字符串。
        log_console_format: 控制台日志格式字符串。
        openai_api_key: OpenAI / 兼容 API 密钥。
        openai_base_url: OpenAI / 兼容 API 端点地址。
        chat_model: 对话模型名称。
        embedding_api_key: 嵌入 API 密钥（默认复用 openai_api_key）。
        embedding_base_url: 嵌入 API 端点地址（默认复用 openai_base_url）。
        openai_embedding_model: 嵌入模型名称。
        openai_embedding_dim: 嵌入向量维度。
        openai_timeout: API 请求超时秒数。
        openai_max_retries: API 最大重试次数。
        chat_reasoning_effort: 推理模型 effort 参数。
        max_history_length: 最大对话历史轮数。
        context_window_chars: 上下文窗口字符数上限。

        storage_backend: 持久化存储后端类型（如 'json'）。
        search_backend: 搜索后端类型（如 'duckduckgo'）。
        searxng_url: SearXNG 实例 URL。
        bocha_api_key: 博查 API 密钥。
        bing_api_key: Bing 搜索 API 密钥。
        search_timeout: 搜索超时秒数。
        max_tool_iter: Agent 最大工具迭代次数。
        max_output_chars: 模型最大输出字符数。
        max_output_tokens: 模型最大输出 token 数。
        eval_max_workers: 评估并发工作线程数。
        superuser_usernames: 超级用户用户名列表。
        superuser_passwords: 超级用户密码列表。
        mineru_base_url: MinerU API 端点地址。
        mineru_api_key: MinerU API 密钥。
        mineru_token_name: MinerU 令牌名称。
        mineru_model_version: MinerU 模型版本（如 'vlm'）。
        mineru_language: MinerU 解析语言（如 'ch'）。
        mineru_max_concurrency: MinerU 最大并发数。
        max_user_storage_mb: 用户存储上限（MB）。
        tool_page_chars: 工具分页字符数。
        index_file: 前端入口文件路径。
        jwt_secret_key: JWT 签名密钥（自动生成）。
        _config_hash: 配置文件 MD5 哈希，用于热重载检测。
    """

    def __init__(self, config_file=_config_file):
        """初始化 Config 实例。

        Args:
            config_file: config.ini 路径，默认使用项目根目录下的文件。
        """
        self._config_file = config_file
        self._load_config()
        self._init_runtime()
        self._update_config_hash()

    # ── 配置加载 ──────────────────────────────────────────────────

    def _load_config(self):
        """从 config.ini + .env + 系统环境变量加载所有配置项。"""
        config = configparser.ConfigParser()
        config.read(self._config_file, encoding='utf-8')
        dotenv = _load_dotenv()

        def env(key: str) -> str | None:
            """按优先级获取环境变量值。

            Args:
                key: 环境变量名称。

            Returns:
                变量值，未找到返回 None。
            """
            val = os.environ.get(key)
            if val is not None:
                return _strip_quotes(val) if val else None
            val = dotenv.get(key)
            return val if val else None

        # ── 存储配置 ──
        self.data_dir = get_file(config, 'storage', 'data_dir')
        self.vector_store_dir = get_file(config, 'storage', 'vector_store_dir')


        # ── 检索配置 ──
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)
        self.min_chunk_length = config.getint('retrieval', 'min_chunk_length', fallback=5)
        raw_stop = _strip_quotes(config.get('retrieval', 'stop_words', fallback=''))
        self.stop_words = [w.strip() for w in raw_stop.split(',') if w.strip()] if raw_stop else []

        # ── 日志配置 ──
        self.log_path = normalize_path(config.get('logger', 'log_path', fallback='logs'))
        self.app_log_level = config.get('logger', 'app_log_level', fallback='INFO')
        self.http_log_level = config.get('logger', 'http_log_level', fallback='INFO')
        self.console_log_level = config.get('logger', 'console_log_level', fallback='DEBUG')
        self.user_log_level = config.get('logger', 'user_log_level', fallback='INFO')
        self.log_file_format = '%(asctime)s | %(levelname)-5s | %(module)s:%(lineno)d | %(message)s'
        self.log_console_format = '%(levelname)-5s %(module)s:%(lineno)d | %(message)s'

        # ── API 配置 ──
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

        # ── 对话历史配置 ──
        self.max_history_length = config.getint('governance', 'max_history_length', fallback=500)
        raw = config.get('governance', 'context_window_chars', fallback='32768')
        self.context_window_chars = int(raw.strip())
        self.context_input_ratio = config.getfloat('governance', 'context_input_ratio', fallback=0.8)

        # ── 搜索配置 ──
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

        # ── Agent 配置 ──
        self.max_tool_iter = config.getint('agent', 'max_tool_iter', fallback=15)
        raw_out = config.get('agent', 'max_output_chars', fallback=None)
        if raw_out is None:
            raw_out = config.get('agent', 'max_output_tokens', fallback='8192')
        self.max_output_chars = int(raw_out.strip())
        self.max_output_tokens = self.max_output_chars
        self.eval_max_workers = config.getint('agent', 'eval_max_workers', fallback=3)

        # ── 超级用户配置 ──
        self.superuser_usernames = [u.strip() for u in config.get('superuser', 'users').split(',')]
        self.superuser_passwords = [p.strip() for p in config.get('superuser', 'passwords').split(',')]

        # ── MinerU 配置 ──
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
        self.mineru_max_concurrency = config.getint('api', 'mineru_max_concurrency', fallback=3)

        # ── 上传配置 ──
        self.max_user_storage_mb = config.getint('upload', 'max_user_storage_mb', fallback=10)

        # ── 治理配置 ──
        self.tool_page_chars = config.getint('governance', 'tool_page_chars', fallback=5000)
        self.compression_ratio = config.getfloat('governance', 'compression_ratio', fallback=0.3)

        # ── 日志滚动配置 ──
        self.log_max_mb = config.getint('logger', 'log_max_mb', fallback=10)
        self.log_backup_count = config.getint('logger', 'log_backup_count', fallback=3)

        self._validate()

    def _init_runtime(self):
        """运行时一次性初始化（JWT 密钥生成等，不随热重载重复执行）。"""
        self.dist_dir = normalize_path("dist")
        self.assets_dir = normalize_path("dist/assets")
        self.index_file = normalize_path("dist/index.html")
        self.desktop_mode = False  # 由 desktop.py 设为 True

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

    def _validate(self):
        """启动时校验关键配置项，避免运行时才暴露问题。

        Raises:
            ValueError: 包含所有配置错误的描述信息。
        """
        errors: list[str] = []

        if not self.openai_api_key:
            errors.append("openai_api_key / chat_api_key 未配置")
        if not self.embedding_api_key:
            errors.append("embedding_api_key 未配置")
        if not self.mineru_api_key:
            errors.append("mineru_api_key 未配置（PDF 解析将不可用）")
        elif not self.mineru_api_key.startswith("eyJ"):
            errors.append(f"mineru_api_key 格式异常（应为 JWT，当前前缀={self.mineru_api_key[:8]}...）")

        for name, val, minimum in [
            ("retrieval_top_k", self.retrieval_top_k, 1),
            ("context_window_chars", self.context_window_chars, 1024),
            ("max_output_chars", self.max_output_chars, 128),
            ("max_tool_iter", self.max_tool_iter, 1),
            ("max_user_storage_mb", self.max_user_storage_mb, 1),
            ("openai_embedding_dim", self.openai_embedding_dim, 64),
        ]:
            if not isinstance(val, int) or val < minimum:
                errors.append(f"{name}={val!r} 无效（应 ≥ {minimum} 的整数）")

        dirs = [
            ("data_dir", self.data_dir),
            ("vector_store_dir", self.vector_store_dir),
            ("uploads_dir", os.path.join(self.data_dir, "uploads")),
            ("json_store_dir", os.path.join(self.data_dir, "json_store")),
            ("history_dir", os.path.join(self.data_dir, "json_store", "history")),
        ]
        for name, path in dirs:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as e:
                errors.append(f"{name}={path} 创建失败: {e}")
            if not os.access(path, os.W_OK):
                errors.append(f"{name}={path} 不可写")

        if len(self.superuser_usernames) != len(self.superuser_passwords):
            errors.append(
                f"superuser 用户名数({len(self.superuser_usernames)}) "
                f"与密码数({len(self.superuser_passwords)})不匹配"
            )

        if errors:
            msg = "\n  ".join(["配置校验失败:"] + errors)
            try:
                from base.logger import logger
                logger.error(msg)
            except Exception:
                pass
            raise ValueError(msg)

    # ── 热重载支持 ────────────────────────────────────────────────

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

        策略：比较当前文件 MD5 与上次记录的 hash。
        不一致时重新执行 _load_config()，覆盖所有 ini/.env/环境变量来源的属性。
        """
        import hashlib
        try:
            with open(self._config_file, 'rb') as f:
                new_hash = hashlib.md5(f.read()).hexdigest()
        except Exception:
            return
        if new_hash == self._config_hash:
            return

        from base.logger import logger
        logger.info(f"检测到配置变更 (hash: {self._config_hash[:8]} → {new_hash[:8]})，自动重载")
        self._load_config()
        self._config_hash = new_hash


# ── 全局单例 ──────────────────────────────────────────────────────

conf = Config()

