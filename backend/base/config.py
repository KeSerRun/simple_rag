# ===== 导入标准库模块 =====
# 导入配置解析模块，用于读取 .ini 格式的配置文件
import configparser
# 导入路径操作模块，用于处理文件和目录路径
import os
# 导入系统模块，用于访问 Python 解释器相关的功能（如 sys.path）
import sys

# ===== 定义项目路径 =====
# '''定义工程路径入口''' — 这三行确定项目根目录和配置文件的位置
# 获取当前配置文件（config.py）所在的目录路径（绝对路径）
_config_dir = os.path.dirname(os.path.abspath(__file__))

# 获取项目根目录路径（_config_dir 的上一级目录，即 backend/）
_project_root = os.path.dirname(_config_dir)

# 定义配置文件路径（将项目根目录和 config.ini 拼接成完整路径）
_config_file = os.path.join(_project_root, 'config.ini')

# 将项目根目录添加到系统模块搜索路径列表（sys.path）中，确保其他模块可以正确导入
sys.path.append(_project_root)

# ===== 路径规范化函数 =====
# 定义函数，规范化路径，将相对路径转换为绝对路径
def normalize_path(path:str) -> str:
    # 如果路径已经是绝对路径，就直接返回原路径；如果是相对路径，则将其与项目根目录拼接成绝对路径（三元表达式实现）
    path = os.path.isabs(path) and path or os.path.join(_project_root, path)
    # 将路径中的所有反斜杠 \ 替换为正斜杠 /，确保在不同操作系统（Windows / Linux / macOS）上的兼容性
    path = path.replace('\\', '/')
    # 返回规范化后的路径字符串
    return path

# ===== 配置文件读取函数 =====
# 定义函数，从配置文件中获取指定节（section）和键（option）的值，并将该路径规范化
def get_file(config:configparser.ConfigParser, section:str, option:str) -> str:
    # 从 ConfigParser 对象中读取指定 section 和 option 的原始字符串值
    path = config.get(section, option)
    # 调用 normalize_path 将路径规范化为绝对路径（支持相对路径转绝对路径）
    return normalize_path(path)

# ===== 引号去除工具函数 =====
# 定义内部函数，去掉字符串首尾可能存在的成对引号
def _strip_quotes(value: str) -> str:
    """去掉配置值首尾可能的成对引号(configparser 不会自动处理)"""
    # 如果值为空（None 或空字符串），直接返回，不做任何处理
    if not value:
        return value
    # 去掉字符串首尾的空白字符（空格、换行、制表符等）
    value = value.strip()
    # 判断字符串长度是否 >=2，且首尾字符相同，且该字符是单引号或双引号
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        # 去掉首尾的引号，返回中间的内容（切片从索引1到倒数第1）
        return value[1:-1]
    # 如果不满足引号条件，直接返回原字符串
    return value

# ===== .env 文件加载函数 =====
# 定义内部函数，加载项目根目录下的 .env 文件，以字典形式返回所有环境变量键值对
def _load_dotenv(path: str = None) -> dict[str, str]:
    """加载 .env 文件, 返回 {KEY: value} 字典。

    格式: KEY=VALUE, 支持 # 注释, 忽略空行。引号会被自动去除。
    """
    # 如果没有传入 path 参数，则使用默认路径：项目根目录下的 .env 文件
    if path is None:
        path = os.path.join(_project_root, '.env')
    # 初始化一个空字典，用来存储解析出来的键值对，类型注解为 str->str 的字典
    result: dict[str, str] = {}
    # 检查 .env 文件是否存在，如果不存在则直接返回空字典
    if not os.path.exists(path):
        return result
    # 以只读模式（'r'）打开 .env 文件，指定编码为 utf-8（支持中文等字符）
    with open(path, 'r', encoding='utf-8') as f:
        # 逐行遍历文件内容
        for line in f:
            # 去除当前行首尾的空白字符（空格、换行等）
            line = line.strip()
            # 如果是空行，或者以 # 开头（注释行），则跳过不处理
            if not line or line.startswith('#'):
                continue
            # 如果行中不包含等号 =，说明不是合法的 KEY=VALUE 格式，跳过
            if '=' not in line:
                continue
            # 用 partition 以第一个等号为分隔符，将行拆分为三部分：key, 分隔符(=), value
            key, _, value = line.partition('=')
            # 去掉 key 首尾的空白字符
            key = key.strip()
            # 去掉 value 首尾的空白字符
            value = value.strip()
            # 调用 _strip_quotes 函数，去除 value 首尾可能存在的引号
            value = _strip_quotes(value)
            # 如果 key 和 value 都不为空，则将这对键值对存入结果字典
            if key and value:
                result[key] = value
    # 返回存储了所有环境变量的字典
    return result

# ===== 配置类定义 =====
# 定义整个应用的配置类，集中管理所有配置项（config.ini + .env + 系统环境变量）
class Config:
    # 初始化配置，传入配置文件路径，加载 config.ini + .env 文件到实例属性中
    def __init__(self, config_file=_config_file):
        # 保存传入的配置文件路径到实例属性 _config_file
        self._config_file = config_file
        # 创建一个 ConfigParser 对象，用于解析 .ini 配置文件
        config = configparser.ConfigParser()
        # 使用 utf-8 编码读取配置文件，将配置内容加载到 ConfigParser 对象中
        config.read(config_file, encoding='utf-8')
        # 调用 _load_dotenv 函数加载 .env 文件，返回键值对字典
        dotenv = _load_dotenv()

        # 定义一个内部函数 env，用于按照优先级获取配置值
        def env(key: str) -> str | None:
            """优先级: 系统环境变量 > .env 文件 > 无。"""
            # 优先从系统环境变量 os.environ 中获取；如果没有，再从 .env 字典中获取；都没有则返回 None
            return os.environ.get(key) or dotenv.get(key) or None

        # ===== Storage 配置（文件存储路径） =====
        # 从配置文件中读取 storage 节下的 data_dir 选项，并规范化路径
        self.data_dir = get_file(config, 'storage', 'data_dir')
        # 从配置文件中读取 storage 节下的 vector_store_dir 选项，并规范化路径（向量数据库存储目录）
        self.vector_store_dir = get_file(config, 'storage', 'vector_store_dir')
        # 从配置文件中读取 storage 节下的 backend 选项，去除引号后赋值（默认 'json'，可选 'sqlite' 等）
        self.storage_backend = _strip_quotes(config.get('storage', 'backend', fallback='json'))

        # ===== RAG 检索配置 =====
        # 从配置文件中读取 retrieval 节下的 retrieval_top_k 选项，转为 int 类型，默认值为 10（检索返回的文档数量）
        self.retrieval_top_k = config.getint('retrieval', 'retrieval_top_k', fallback=10)
        # 从配置文件中读取 retrieval 节下的 candidate_top_k 选项，转为 int 类型，默认值为 5（候选文档数量）
        self.candidate_top_k = config.getint('retrieval', 'candidate_top_k', fallback=5)
        # 从配置文件中读取 retrieval 节下的 enable_llm_rerank 选项，转为 bool 类型，默认值为 False（是否启用 LLM 重排序）
        self.enable_llm_rerank = config.getboolean('retrieval', 'enable_llm_rerank', fallback=False)
        # 从配置文件中读取 retrieval 节下的 min_chunk_length 选项，转为 int 类型，默认值为 5（文本块最小长度）
        self.min_chunk_length = config.getint('retrieval', 'min_chunk_length', fallback=5)
        # 从配置文件中读取 retrieval 节下的 stop_words 选项，去除引号后赋值；如果不存在则默认为空字符串
        raw_stop = _strip_quotes(config.get('retrieval', 'stop_words', fallback=''))
        # 如果 raw_stop 不为空，则按逗号分割并去除每个词的空白，得到停用词列表；否则为空列表
        self.stop_words = [w.strip() for w in raw_stop.split(',') if w.strip()] if raw_stop else []

        # ===== 日志配置（目录路径和日志级别） =====
        # 从配置文件中读取 logger 节下的 log_path 选项，规范化路径后赋值，默认值为 'logs'
        self.log_path = normalize_path(config.get('logger', 'log_path', fallback='logs'))
        # 从配置文件中读取 logger 节下的 app_log_level 选项，设置应用日志级别，默认值为 'INFO'
        self.app_log_level = config.get('logger', 'app_log_level', fallback='INFO')
        # 从配置文件中读取 logger 节下的 http_log_level 选项，设置 HTTP 请求日志级别，默认值为 'INFO'
        self.http_log_level = config.get('logger', 'http_log_level', fallback='INFO')
        # 从配置文件中读取 logger 节下的 user_log_level 选项，设置用户操作日志级别，默认值为 'INFO'
        self.user_log_level = config.get('logger', 'user_log_level', fallback='INFO')
        # 从配置文件中读取 logger 节下的 console_log_level 选项，设置控制台输出日志级别，默认值为 'DEBUG'
        self.console_log_level = config.get('logger', 'console_log_level', fallback='DEBUG')
        # 定义日志文件输出格式模板：包含级别、时间、模块名、行号和消息内容
        self.log_file_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'
        # 定义控制台日志输出格式模板：与文件格式保持一致
        self.log_console_format = '%(levelname)s %(asctime)s %(module)s:%(lineno)d : %(message)s'

        # ===== OpenAI API 配置 — Chat 对话端（优先级：系统环境变量 > .env > config.ini） =====
        # 获取 OpenAI API 密钥：优先从系统环境变量或 .env 获取，其次从 config.ini 的 chat_api_key 获取，最后从 api_key 获取，都没有则为 None
        self.openai_api_key = (
            env('OPENAI_API_KEY')
            or _strip_quotes(config.get('api', 'chat_api_key', fallback=''))
            or _strip_quotes(config.get('api', 'api_key', fallback=''))
            or None
        )
        # 获取 OpenAI API 的基础 URL：优先从系统环境变量或 .env 获取，其次从 config.ini 的 chat_base_url 获取，最后从 base_url 获取（默认 OpenAI 官方地址）
        self.openai_base_url = (
            env('OPENAI_BASE_URL')
            or _strip_quotes(config.get('api', 'chat_base_url', fallback=''))
            or _strip_quotes(config.get('api', 'base_url', fallback='https://api.openai.com/v1'))
            or None
        )
        # 获取聊天模型的名称，从 config.ini 的 api 节下 chat_model 获取（去除引号），默认使用 'gpt-4o-mini'
        self.chat_model = _strip_quotes(config.get('api', 'chat_model', fallback='gpt-4o-mini'))

        # ===== OpenAI API 配置 — Embedding 向量嵌入端 =====
        # 获取 Embedding API 密钥：优先从系统环境变量或 .env 获取，其次从 config.ini 的 embedding_api_key 获取，最后回退使用 chat 的 API 密钥
        self.embedding_api_key = (
            env('OPENAI_EMBEDDING_API_KEY')
            or _strip_quotes(config.get('api', 'embedding_api_key', fallback=''))
            or self.openai_api_key
        )
        # 获取 Embedding API 的基础 URL：优先从系统环境变量或 .env 获取，其次从 config.ini 的 embedding_base_url 获取，最后回退使用 chat 的 base URL
        self.embedding_base_url = (
            env('OPENAI_EMBEDDING_BASE_URL')
            or _strip_quotes(config.get('api', 'embedding_base_url', fallback=''))
            or self.openai_base_url
        )
        # 获取嵌入向量模型的名称（去除引号），默认使用 OpenAI 的 'text-embedding-3-small'
        self.openai_embedding_model = _strip_quotes(config.get('api', 'embedding_model', fallback='text-embedding-3-small'))
        # 获取嵌入向量维度，从 config.ini 的 api 节下 embedding_dim 读取（转为 int），默认值为 1536
        self.openai_embedding_dim = config.getint('api', 'embedding_dim', fallback=1536)
        # 获取 OpenAI API 请求超时时间（秒），从 config.ini 读取（转为 float），默认值为 60.0 秒
        self.openai_timeout = config.getfloat('api', 'timeout', fallback=60.0)
        # 获取 OpenAI API 请求失败时的最大重试次数（转为 int），默认值为 3 次
        self.openai_max_retries = config.getint('api', 'max_retries', fallback=3)
        # 获取聊天模型的推理努力程度（reasoning_effort，去除引号），如果为空字符串则转为 None，表示不设置
        self.chat_reasoning_effort = _strip_quotes(config.get('api', 'chat_reasoning_effort', fallback='')) or None

        # ===== 对话历史配置 =====
        # 从 config.ini 的 conversation_history 节下读取 max_history_length（最大保留对话轮数），默认值为 10
        self.max_history_length = config.getint('conversation_history', 'max_history_length', fallback=10)
        # 从 config.ini 的 conversation_history 节下读取 max_history_chars（最大历史字符数），默认值为 10000
        self.max_history_chars = config.getint('conversation_history', 'max_history_chars', fallback=10000)

        # ===== 联网搜索配置 =====
        # 获取搜索后端名称（去除引号），默认使用 DuckDuckGo（免费，无需 API Key）
        self.search_backend = _strip_quotes(config.get('search', 'backend', fallback='duckduckgo'))
        # 获取 SearXNG 搜索服务的 URL（自托管元搜索引擎，去除引号），默认为空字符串
        self.searxng_url = _strip_quotes(config.get('search', 'searxng_url', fallback=''))
        # 获取博查搜索（bocha）的 API 密钥：优先从系统环境变量或 .env 获取，其次从 config.ini 读取，都没有则为 None
        self.bocha_api_key = (
            env('BOCHA_API_KEY')
            or _strip_quotes(config.get('search', 'bocha_api_key', fallback=''))
            or None
        )
        # 获取 Bing 搜索的 API 密钥：优先从系统环境变量或 .env 获取，其次从 config.ini 读取，都没有则为 None
        self.bing_api_key = (
            env('BING_API_KEY')
            or _strip_quotes(config.get('search', 'bing_api_key', fallback=''))
            or None
        )
        # 获取搜索请求的超时时间（秒），从 config.ini 读取（转为 float），默认值为 15 秒
        self.search_timeout = config.getfloat('search', 'timeout', fallback=15)

        # ===== Agent 配置（智能体） =====
        # 获取 Agent 最大工具调用迭代次数（转为 int），默认值为 6，防止无限循环
        self.max_tool_iter = config.getint('agent', 'max_tool_iter', fallback=6)
        # 获取每个工具的最大调用次数（转为 int），默认值为 3
        self.max_calls_per_tool = config.getint('agent', 'max_calls_per_tool', fallback=3)
        # 获取 Agent 输出最大 token 数（转为 int），默认值为 8192
        self.max_output_tokens = config.getint('agent', 'max_output_tokens', fallback=8192)
        # 获取 MinerU PDF 解析的并发工作线程数（转为 int），默认值为 3，设为 1 即串行
        self.parse_workers = config.getint('agent', 'parse_workers', fallback=3)
        # 获取工具调用并发数（转为 int），默认值为 4，LLM 每轮最多同时执行多少个工具
        self.tool_call_workers = config.getint('agent', 'tool_call_workers', fallback=4)

        # ===== 前端页面配置 =====
        # HTML 主页文件路径（相对于 backend/ 根目录的前端构建产物 dist/index.html）
        self.index_file = normalize_path("dist/index.html")

        # ===== JWT 密钥配置（优先使用 .env，否则自动生成） =====
        # 尝试从系统环境变量或 .env 文件中获取 JWT_SECRET_KEY（用于用户登录令牌签名）
        _jwt = env('JWT_SECRET_KEY')
        # 如果没有获取到 JWT_SECRET_KEY，则自动生成一个
        if not _jwt:
            # 导入 Python 内置的 secrets 模块，用于生成安全的随机字符串
            import secrets as _sec
            # 生成一个 256 位（32 字节）的十六进制随机字符串作为 JWT 密钥
            _jwt = _sec.token_hex(32)
            # 写入 .env 文件以便后续持久化使用（这样重启后密钥不会改变）
            _env_path = os.path.join(_project_root, '.env')
            # 尝试以追加模式（'a'）打开 .env 文件，将自动生成的密钥写入
            try:
                with open(_env_path, 'a', encoding='utf-8') as _f:
                    # 在 .env 文件末尾追加 JWT 密钥，并添加注释说明
                    _f.write(f"\n# 自动生成的 JWT 密钥（如要更换请删除此行）\nJWT_SECRET_KEY={_jwt}\n")
                # 在控制台输出提示信息，告知用户已自动生成并写入密钥
                print(f"[config] 已自动生成 JWT_SECRET_KEY 并写入 {_env_path}")
            # 捕获所有异常（如文件权限不足、磁盘已满等），写入失败不影响程序正常运行
            except Exception:
                pass  # 写入失败不影响运行
        # 将最终的 JWT 密钥（从环境变量获取或自动生成）保存到实例属性
        self.jwt_secret_key = _jwt

        # ===== 超级管理员（superuser）配置 =====
        # 从 config.ini 的 superuser 节下读取 users 选项，按逗号分割并去除空格，得到超级管理员用户名列表
        self.superuser_usernames = [u.strip() for u in config.get('superuser', 'users').split(',')]
        # 从 config.ini 的 superuser 节下读取 passwords 选项，按逗号分割并去除空格，得到超级管理员密码列表
        self.superuser_passwords = [p.strip() for p in config.get('superuser', 'passwords').split(',')]

        # ===== MinerU 配置（PDF 解析服务） =====
        # 获取 MinerU 服务的 API 基础 URL：优先从系统环境变量或 .env 获取，其次从 config.ini 读取（默认使用官方 v4 接口地址）
        self.mineru_base_url = (
            env('MINERU_BASE_URL')
            or _strip_quotes(config.get('api', 'mineru_base_url', fallback='https://mineru.net/api/v4'))
        )
        # 获取 MinerU 服务的 API 密钥：优先从系统环境变量或 .env 获取，其次从 config.ini 读取，默认为空字符串
        self.mineru_api_key = (
            env('MINERU_API_KEY')
            or _strip_quotes(config.get('api', 'mineru_api_key', fallback=''))
        )
        # 获取 MinerU 的令牌名称（token name，去除引号），默认值为 'default'
        self.mineru_token_name = _strip_quotes(config.get('api', 'mineru_token_name', fallback='default'))
        # 获取 MinerU 使用的模型版本（去除引号），默认值为 'vlm'（视觉语言模型）
        self.mineru_model_version = _strip_quotes(config.get('api', 'mineru_model_version', fallback='vlm'))
        # 获取 MinerU 处理文档的语言（去除引号），默认值为 'ch'（中文 Chinese）
        self.mineru_language = _strip_quotes(config.get('api', 'mineru_language', fallback='ch'))

        # ===== 上传限制配置 =====
        # 从 config.ini 的 upload 节下读取 max_user_storage_mb（每个用户最大存储空间，单位 MB），默认值为 10 MB
        self.max_user_storage_mb = config.getint('upload', 'max_user_storage_mb', fallback=10)

# ===== 全局配置实例 =====
# 创建 Config 类的全局实例 conf，供其他模块导入和使用（单例模式，整个应用共享同一个配置对象）
conf = Config()

# ===== 直接运行时的调试输出 =====
# 如果当前脚本被直接运行（而不是被其他模块导入），则执行以下调试代码
if __name__ == "__main__":
    # 导入 rich 库中的 print 函数，用于美化输出（彩色、格式化打印字典）
    from rich import print
    # 打印 conf 对象的所有属性（__dict__ 以字典形式展示所有配置项及其值）
    print(conf.__dict__)
