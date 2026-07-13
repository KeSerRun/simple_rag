# ── 日志系统 ──────────────────────────────────────────────────────
"""日志系统：配置、模块化日志器与 LLM 输入日志。

提供应用日志 / HTTP 请求日志 / 用户操作日志三个独立日志器，
以及 LLM 输入记录的辅助函数。
"""

import json as _json
import datetime as _dt
from .config import conf

import logging

import os


# ── LLM 输入日志 ──────────────────────────────────────────────────

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_input_log_path = os.path.join(_BACKEND_ROOT, "logs", "input.log")


def log_llm_input(messages: list, round: int = 0, suffix: str = ""):
    """将 LLM 输入消息追加到 input.log。

    Args:
        messages: OpenAI 格式的消息列表。
        round: 当前对话轮数。
        suffix: 日志标签后缀（可选）。
    """
    try:
        os.makedirs(os.path.dirname(_input_log_path), exist_ok=True)
        tag = f" round={round}{suffix}" if suffix else f" round={round}"
        with open(_input_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {_dt.datetime.now().isoformat()}{tag} ===\n")
            f.write(_json.dumps(messages, ensure_ascii=False, indent=2))
            f.write("\n")
    except Exception:
        pass


# ── 应用日志 ──────────────────────────────────────────────────────


def setup_logger(log_path=None):
    """创建并配置应用日志器（RAGLogger）。

    同时写入文件和控制台，分别使用独立的格式和日志级别。

    Args:
        log_path: 日志文件目录；默认使用 conf.log_path。

    Returns:
        配置完成的 logging.Logger 实例。
    """
    if log_path is None:
        log_path = conf.log_path

    log_file = os.path.join(log_path, 'app.log')

    os.makedirs(log_path, exist_ok=True)

    logger = logging.getLogger('RAGLogger')

    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')

    console_handler = logging.StreamHandler()

    file_handler.setLevel(conf.app_log_level)

    console_handler.setLevel(conf.console_log_level)

    file_formatter = logging.Formatter(conf.log_file_format)

    console_formatter = logging.Formatter(conf.log_console_format)

    file_handler.setFormatter(file_formatter)

    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)

    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


# ── HTTP 请求日志 ─────────────────────────────────────────────────

_http_log_path = os.path.join(conf.log_path, 'http.log')

_http_logger = logging.getLogger('HTTPLogger')

_http_logger.setLevel(conf.http_log_level)

_http_logger.propagate = False

_http_handler = logging.FileHandler(_http_log_path, encoding='utf-8')

_http_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

_http_logger.addHandler(_http_handler)


# ── 用户操作日志 ──────────────────────────────────────────────────

_user_log_path = os.path.join(conf.log_path, 'user.log')

_user_logger = logging.getLogger('UserLogger')

_user_logger.setLevel(conf.user_log_level)

_user_logger.propagate = False

_user_handler = logging.FileHandler(_user_log_path, encoding='utf-8')

_user_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

_user_logger.addHandler(_user_handler)


# ── 公共日志接口 ──────────────────────────────────────────────────


def log_http(method: str, path: str, status: int, username: str = '-'):
    """记录 HTTP 请求日志。

    Args:
        method: HTTP 方法（GET / POST 等）。
        path: 请求路径。
        status: HTTP 状态码。
        username: 请求用户名，默认 '-'。
    """
    _http_logger.info(f'{method:6s} {status}  {username:12s}  {path}')


def log_qa(username: str, session_id: str, question: str, answer: str):
    """记录用户问答日志。

    Args:
        username: 用户名。
        session_id: 会话 ID。
        question: 用户问题。
        answer: 助手回答。
    """
    _user_logger.info(
        f"[{username}][{session_id}]\n"
        f"Q: {question}\n"
        f"A: {answer}"
    )

