import json as _json
import datetime as _dt
from .config import conf

import logging

import os


# ─── LLM 输入日志 ──────────────────────────────────
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_input_log_path = os.path.join(_BACKEND_ROOT, "logs", "input.log")


def log_llm_input(messages: list, round: int = 0, suffix: str = ""):
    """将 LLM 输入消息追加到 input.log。"""
    try:
        os.makedirs(os.path.dirname(_input_log_path), exist_ok=True)
        tag = f" round={round}{suffix}" if suffix else f" round={round}"
        with open(_input_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {_dt.datetime.now().isoformat()}{tag} ===\n")
            f.write(_json.dumps(messages, ensure_ascii=False, indent=2))
            f.write("\n")
    except Exception:
        pass


# ─── 结构化日志 ────────────────────────────────────

def setup_logger(log_path=None):
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


_http_log_path = os.path.join(conf.log_path, 'http.log')

_http_logger = logging.getLogger('HTTPLogger')

_http_logger.setLevel(conf.http_log_level)

_http_logger.propagate = False

_http_handler = logging.FileHandler(_http_log_path, encoding='utf-8')

_http_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

_http_logger.addHandler(_http_handler)


_user_log_path = os.path.join(conf.log_path, 'user.log')

_user_logger = logging.getLogger('UserLogger')

_user_logger.setLevel(conf.user_log_level)

_user_logger.propagate = False

_user_handler = logging.FileHandler(_user_log_path, encoding='utf-8')

_user_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

_user_logger.addHandler(_user_handler)


def log_http(method: str, path: str, status: int, username: str = '-'):
    _http_logger.info(f'{method:6s} {status}  {username:12s}  {path}')


def log_qa(username: str, session_id: str, question: str, answer: str):
    _user_logger.info(
        f"[{username}][{session_id}]\n"
        f"Q: {question}\n"
        f"A: {answer}"
    )


def batch_configure_loggers(level=logging.WARNING, propagate=False):
    _protected = {'RAGLogger', 'HTTPLogger', 'UserLogger'}
    manager = logging.Logger.manager
    for name, logger_obj in manager.loggerDict.items():
        if isinstance(logger_obj, logging.Logger):
            if logger_obj.name not in _protected:
                logger_obj.propagate = propagate
                logger_obj.level = level


if __name__ == "__main__":
    logger.debug("这是一个调试日志")
    logger.info("这是一个信息日志")
    logger.warning("这是一个警告日志")
    logger.error("这是一个错误日志")
