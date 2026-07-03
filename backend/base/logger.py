# 导入配置类
from .config import conf
# 导入日志模块
import logging
# 导入路径操作模块
import os

def setup_logger(log_path=None):
    if log_path is None:
        log_path = conf.log_path
    log_file = os.path.join(log_path, 'app.log')
    # 创建日志目录
    os.makedirs(log_path, exist_ok=True)
    # 配置日志记录器
    logger = logging.getLogger('RAGLogger')
    # 设置日志级别
    logger.setLevel(logging.DEBUG)
    # 创建日志文件处理器
    file_handler = logging.FileHandler(log_file,encoding='utf-8')
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    # 设置日志级别
    file_handler.setLevel(conf.app_log_level)
    console_handler.setLevel(conf.console_log_level)
    # 设置日志格式
    file_formatter = logging.Formatter(conf.log_file_format)
    console_formatter = logging.Formatter(conf.log_console_format)
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)
    # 将处理器添加到日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

logger = setup_logger()  # 创建全局日志记录器实例，供其他模块使用

# HTTP 请求日志专用
_http_log_path = os.path.join(conf.log_path, 'http.log')
_http_logger = logging.getLogger('HTTPLogger')
_http_logger.setLevel(conf.http_log_level)
_http_logger.propagate = False
_http_handler = logging.FileHandler(_http_log_path, encoding='utf-8')
_http_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
_http_logger.addHandler(_http_handler)

# 用户 QA 问答日志专用
_user_log_path = os.path.join(conf.log_path, 'user.log')
_user_logger = logging.getLogger('UserLogger')
_user_logger.setLevel(conf.user_log_level)
_user_logger.propagate = False
_user_handler = logging.FileHandler(_user_log_path, encoding='utf-8')
_user_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
_user_logger.addHandler(_user_handler)

def log_http(method: str, path: str, status: int, username: str = '-'):
    """记录 HTTP 请求"""
    _http_logger.info(f'{method:6s} {status}  {username:12s}  {path}')

def log_qa(username: str, session_id: str, question: str, answer: str):
    """记录用户 QA 问答对"""
    _user_logger.info(
        f"[{username}][{session_id}]\n"
        f"Q: {question}\n"
        f"A: {answer}"
    )

def batch_configure_loggers(level=logging.WARNING,propagate=False):
    """
    批量配置所有已注册的 logger，设置 propagate=False，防止日志冒泡到根 logger。
    """
    # 保护这些 logger 不被覆盖
    _protected = {'RAGLogger', 'HTTPLogger', 'UserLogger'}
    manager = logging.Logger.manager # type: logging.Manager
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