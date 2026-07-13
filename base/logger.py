
# conf 是项目的全局配置对象，里面存放了日志路径、日志级别等配置信息
from .config import conf

import logging

import os


def setup_logger(log_path=None):
    if log_path is None:
        # 如果没有传入 log_path，则从全局配置对象 conf 中读取默认的日志目录路径
        log_path = conf.log_path

    # 把日志目录路径和文件名 'app.log' 拼接在一起，得到完整的日志文件路径
    # os.path.join 能自动处理不同操作系统下的路径分隔符（Windows 用 \，Linux/Mac 用 /）
    log_file = os.path.join(log_path, 'app.log')

    # os.makedirs 会递归创建多级目录，比如如果父目录不存在也会一并创建
    os.makedirs(log_path, exist_ok=True)

    # 通过 logging.getLogger 获取一个名为 'RAGLogger' 的日志记录器实例
    logger = logging.getLogger('RAGLogger')

    # 只有级别 >= DEBUG 的日志才会被处理，级别从低到高：DEBUG < INFO < WARNING < ERROR < CRITICAL
    logger.setLevel(logging.DEBUG)

    # encoding='utf-8' 指定文件编码为 UTF-8，防止中文日志出现乱码
    file_handler = logging.FileHandler(log_file, encoding='utf-8')

    console_handler = logging.StreamHandler()

    file_handler.setLevel(conf.app_log_level)

    console_handler.setLevel(conf.console_log_level)

    # 常见的格式包含：时间、日志级别、模块名、行号、日志消息等
    file_formatter = logging.Formatter(conf.log_file_format)

    # 控制台格式通常比文件格式更简洁，方便开发时查看
    console_formatter = logging.Formatter(conf.log_console_format)

    file_handler.setFormatter(file_formatter)

    # 将上面定义好的控制台格式器（console_formatter）绑定到控制台处理器上
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)

    logger.addHandler(console_handler)

    return logger


# 这个 logger 会在模块加载时自动创建，其他文件通过 "from base.logger import logger" 来使用
logger = setup_logger()


# 把配置中的日志目录路径和文件名 'http.log' 拼接起来，得到 HTTP 日志的完整文件路径
_http_log_path = os.path.join(conf.log_path, 'http.log')

_http_logger = logging.getLogger('HTTPLogger')

_http_logger.setLevel(conf.http_log_level)

_http_logger.propagate = False

# encoding='utf-8' 确保日志中的中文字符能正常显示
_http_handler = logging.FileHandler(_http_log_path, encoding='utf-8')

# '[%(asctime)s] %(message)s' 表示输出格式为 "[2024-01-01 12:00:00] 消息内容"
# datefmt='%Y-%m-%d %H:%M:%S' 指定了时间的显示格式：年-月-日 时:分:秒
_http_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# 把 HTTP 文件处理器添加到 HTTP 日志记录器中，使其生效
_http_logger.addHandler(_http_handler)


# 把配置中的日志目录路径和文件名 'user.log' 拼接起来，得到用户问答日志的完整文件路径
_user_log_path = os.path.join(conf.log_path, 'user.log')

_user_logger = logging.getLogger('UserLogger')

_user_logger.setLevel(conf.user_log_level)

_user_logger.propagate = False

# encoding='utf-8' 确保中文问题和答案能正常写入日志文件
_user_handler = logging.FileHandler(_user_log_path, encoding='utf-8')

_user_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# 把用户问答文件处理器添加到用户问答日志记录器中，使其生效
_user_logger.addHandler(_user_handler)


# method: HTTP 请求方法（GET、POST、PUT、DELETE 等）
# path: 请求的 URL 路径
# status: HTTP 响应状态码（200 表示成功，404 表示找不到页面，500 表示服务器错误等）
# username: 发起请求的用户名，默认值为 '-'（表示未登录或匿名用户）
def log_http(method: str, path: str, status: int, username: str = '-'):
    """记录 HTTP 请求"""

    # 使用 _http_logger 的 info 级别记录一条日志
    # f-string 格式化输出：左对齐补全到 6 位的方法名、状态码、左对齐补全到 12 位的用户名、请求路径
    # 例如：'GET     200  admin         /api/documents'
    _http_logger.info(f'{method:6s} {status}  {username:12s}  {path}')


# username: 提问的用户名
# question: 用户提出的问题内容
# answer: 系统/模型给出的回答内容
def log_qa(username: str, session_id: str, question: str, answer: str):
    """记录用户 QA 问答对"""

    # 使用 _user_logger 的 info 级别记录一条用户问答日志
    # 日志格式为多行文本，包含用户名、会话 ID、问题和答案
    _user_logger.info(
        # 第一行：用方括号括起来的用户名和会话 ID
        f"[{username}][{session_id}]\n"
        # 第二行：以 "Q: " 开头的问题内容
        f"Q: {question}\n"
        # 第三行：以 "A: " 开头的答案内容
        f"A: {answer}"
    )


# level: 要设置的日志级别，默认为 logging.WARNING（只记录警告及以上级别的日志）
# propagate: 是否允许日志冒泡到父级 logger，默认为 False（不允许冒泡）
def batch_configure_loggers(level=logging.WARNING, propagate=False):
    """
    批量配置所有已注册的 logger，设置 propagate=False，防止日志冒泡到根 logger。
    """

    _protected = {'RAGLogger', 'HTTPLogger', 'UserLogger'}

    # type: logging.Manager 只是类型注解，提示开发者这个对象的类型
    manager = logging.Logger.manager  # type: logging.Manager

    # 遍历 manager 中存储的所有 logger
    # manager.loggerDict 是一个字典，key 是 logger 的名称，value 是 logger 对象
    for name, logger_obj in manager.loggerDict.items():
        # 判断获取到的对象是否是 logging.Logger 的实例（防止混入其他类型的对象）
        if isinstance(logger_obj, logging.Logger):
            # 判断当前 logger 的名称是否不在受保护的集合中
            if logger_obj.name not in _protected:
                logger_obj.propagate = propagate
                logger_obj.level = level


# __name__ 是 Python 内置变量，当文件被直接运行时值为 '__main__'
if __name__ == "__main__":
    logger.debug("这是一个调试日志")
    logger.info("这是一个信息日志")
    logger.warning("这是一个警告日志")
    logger.error("这是一个错误日志")
