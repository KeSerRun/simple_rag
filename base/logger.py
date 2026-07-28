"""日志系统：应用日志 / HTTP 请求日志 / 用户操作日志 / LLM 输入记录。

控制台输出带 ANSI 颜色：DEBUG=青色, INFO=绿色, WARNING=黄色, ERROR=红色。
文件输出带滚动窗口（RotatingFileHandler），超出大小自动轮转，保留最近 N 个备份。
"""
import json as _json
import logging
import logging.handlers
import os
import re
from .config import conf


# ── ANSI 颜色常量 ──────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    logging.DEBUG:    "\033[36m",      # 青色
    logging.INFO:     "\033[32m",      # 绿色
    logging.WARNING:  "\033[33m",      # 黄色
    logging.ERROR:    "\033[31m",      # 红色
    logging.CRITICAL: "\033[1;31m",    # 加粗红色
}


class ColorFormatter(logging.Formatter):
    """带 ANSI 颜色的日志格式化器。

    控制台输出：级别名着色、模块名加粗、消息中的 URL 自动加粗。
    文件 Handler 不受影响（使用普通 Formatter）。
    """

    # URL 模式：http/https/ftp 开头的链接
    _URL_RE = re.compile(r'(https?://[^\s,，。；;]+)')

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        orig_levelname = record.levelname
        orig_module = record.module
        orig_msg = record.msg
        # URL 加粗（仅对字符串消息，避免破坏格式化参数）
        if isinstance(record.msg, str):
            record.msg = self._URL_RE.sub(f'{_BOLD}\\1{_RESET}', record.msg)
        try:
            record.levelname = f"{color}{_BOLD}{record.levelname}{_RESET}"
            record.module = f"{_BOLD}{record.module}{_RESET}"
            return super().format(record)
        finally:
            record.levelname = orig_levelname
            record.module = orig_module
            record.msg = orig_msg


# ── 滚动窗口文件 Handler 工厂 ─────────────────────
def _rotating_handler(
    filename: str,
    level: int,
    fmt: logging.Formatter,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> logging.handlers.RotatingFileHandler:
    """创建一个带滚动窗口的文件 Handler。

    Args:
        filename: 日志文件路径（相对于 log_path）。
        level: 日志级别。
        fmt: Formatter 实例。
        max_bytes: 单文件最大字节数；默认取 conf.log_max_bytes。
        backup_count: 保留的备份文件数；默认取 conf.log_backup_count。

    Returns:
        RotatingFileHandler 实例。
    """
    max_bytes = (max_bytes or conf.log_max_mb) * 1024 * 1024
    backup_count = backup_count or conf.log_backup_count
    path = os.path.join(conf.log_path, filename)
    h = logging.handlers.RotatingFileHandler(
        path, encoding="utf-8",
        maxBytes=max_bytes, backupCount=backup_count,
    )
    h.setLevel(level)
    h.setFormatter(fmt)
    return h


# ── 应用日志器 ────────────────────────────────────
os.makedirs(conf.log_path, exist_ok=True)

logger = logging.getLogger("APPLogger")
logger.setLevel(logging.DEBUG)

# 文件 handler：带滚动窗口
_fh = _rotating_handler(
    "app.log", conf.app_log_level,
    logging.Formatter(conf.log_file_format),
)
# 控制台 handler：带颜色
_ch = logging.StreamHandler()
_ch.setLevel(conf.console_log_level)
_ch.setFormatter(ColorFormatter(conf.log_console_format))

logger.addHandler(_fh)
logger.addHandler(_ch)


# ── LLM 输入日志 ──────────────────────────────────
_llm_logger = logging.getLogger("LLMInputLogger")
_llm_logger.setLevel(logging.INFO)
_llm_logger.propagate = False
_lh = _rotating_handler(
    "input.log", logging.INFO,
    logging.Formatter(
        "=== %(asctime)s %(message)s ===\n%(msg_json)s\n",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ),
)
_llm_logger.addHandler(_lh)


# ── HTTP 请求日志器 ──────────────────────────────
_http_logger = logging.getLogger("HTTPLogger")
_http_logger.setLevel(conf.http_log_level)
_http_logger.propagate = False
_hh = _rotating_handler(
    "http.log", conf.http_log_level,
    logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ),
)
_http_logger.addHandler(_hh)


# ── 用户操作日志器 ──────────────────────────────
_user_logger = logging.getLogger("UserLogger")
_user_logger.setLevel(conf.user_log_level)
_user_logger.propagate = False
_uh = _rotating_handler(
    "user.log", conf.user_log_level,
    logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ),
)
_user_logger.addHandler(_uh)


# ── 公共日志接口 ────────────────────────────────
def log_http(method: str, path: str, status: int, username: str = "-"):
    """记录 HTTP 请求日志。"""
    _http_logger.info(f"{method:6s} {status}  {username:12s}  {path}")


def log_qa(username: str, session_id: str, question: str, answer: str):
    """记录用户问答日志。"""
    _user_logger.info(
        f"[{username}][{session_id}]\nQ: {question}\nA: {answer}"
    )


def log_llm_input(messages: list, round: int = 0, suffix: str = ""):
    """记录 LLM 输入消息到 input.log。"""
    try:
        tag = f" round={round}{suffix}" if suffix else f" round={round}"
        _llm_logger.info(
            tag,
            extra={"msg_json": _json.dumps(messages, ensure_ascii=False, indent=2)},
        )
    except Exception:
        pass


# ── Uvicorn / FastAPI 日志彩色化 ────────────────────


def get_uvicorn_log_config() -> dict:
    """生成 uvicorn 日志配置，使用 ColorFormatter 替代默认格式。

    传递给 ``uvicorn.run(log_config=...)`` 可从第一条日志起就应用颜色和统一格式。

    Returns:
        logging.config.dictConfig 兼容的配置字典。
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "base.logger.ColorFormatter",
                "fmt": conf.log_console_format,
            },
            "access": {
                "()": "base.logger.ColorFormatter",
                "fmt": conf.log_console_format,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def configure_third_party_logging():
    """将 ColorFormatter 注入 uvicorn / FastAPI 等已存在的 StreamHandler。

    作为兜底：当 uvicorn 未使用 ``get_uvicorn_log_config()`` 启动时，
    在 lifespan 中调用此函数修复格式和颜色。
    """
    _targets = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")
    for name in _targets:
        lg = logging.getLogger(name)
        for h in lg.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setFormatter(ColorFormatter(conf.log_console_format))
