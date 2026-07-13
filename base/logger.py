"""日志系统：应用日志 / HTTP 请求日志 / 用户操作日志 / LLM 输入记录。"""
import json as _json
import logging
import os
from .config import conf


# ── 应用日志器 ────────────────────────────────────
_app_log_path = os.path.join(conf.log_path, "app.log")
os.makedirs(conf.log_path, exist_ok=True)

logger = logging.getLogger("APPLogger")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(_app_log_path, encoding="utf-8")
_fh.setLevel(conf.app_log_level)
_fh.setFormatter(logging.Formatter(conf.log_file_format))

_ch = logging.StreamHandler()
_ch.setLevel(conf.console_log_level)
_ch.setFormatter(logging.Formatter(conf.log_console_format))

logger.addHandler(_fh)
logger.addHandler(_ch)


# ── LLM 输入日志 ──────────────────────────────────
_llm_logger = logging.getLogger("LLMInputLogger")
_llm_logger.setLevel(logging.INFO)
_llm_logger.propagate = False
_lh = logging.FileHandler(
    os.path.join(conf.log_path, "input.log"), encoding="utf-8"
)
_lh.setFormatter(logging.Formatter("=== %(asctime)s %(message)s ===\n%(msg_json)s\n", datefmt="%Y-%m-%dT%H:%M:%S"))
_llm_logger.addHandler(_lh)


# ── HTTP 请求日志器 ──────────────────────────────
_http_logger = logging.getLogger("HTTPLogger")
_http_logger.setLevel(conf.http_log_level)
_http_logger.propagate = False
_hh = logging.FileHandler(os.path.join(conf.log_path, "http.log"), encoding="utf-8")
_hh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_http_logger.addHandler(_hh)


# ── 用户操作日志器 ──────────────────────────────
_user_logger = logging.getLogger("UserLogger")
_user_logger.setLevel(conf.user_log_level)
_user_logger.propagate = False
_uh = logging.FileHandler(os.path.join(conf.log_path, "user.log"), encoding="utf-8")
_uh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_user_logger.addHandler(_uh)


# ── 公共日志接口 ────────────────────────────────
def log_http(method: str, path: str, status: int, username: str = "-"):
    """记录 HTTP 请求日志。"""
    _http_logger.info(f"{method:6s} {status}  {username:12s}  {path}")


def log_qa(username: str, session_id: str, question: str, answer: str):
    """记录用户问答日志。"""
    _user_logger.info(f"[{username}][{session_id}]\nQ: {question}\nA: {answer}")


def log_llm_input(messages: list, round: int = 0, suffix: str = ""):
    """记录 LLM 输入消息到 input.log。"""
    try:
        tag = f" round={round}{suffix}" if suffix else f" round={round}"
        _llm_logger.info(tag, extra={"msg_json": _json.dumps(messages, ensure_ascii=False, indent=2)})
    except Exception:
        pass
