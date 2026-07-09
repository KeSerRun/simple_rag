# ========== 模块导入 ==========

# 从当前包（backend/base）的 config 模块中导入 conf 对象
# conf 是项目的全局配置对象，里面存放了日志路径、日志级别等配置信息
from .config import conf

# 导入 Python 内置的 logging 日志模块，用于记录程序运行时的日志信息
import logging

# 导入 os 模块，用于处理文件和路径相关的操作（比如拼接路径、创建目录）
import os


# ========== 主日志记录器设置函数 ==========

# 定义一个函数，用于设置和创建项目的主日志记录器（logger）
# log_path 参数是可选的，如果不传则使用配置文件中默认的日志路径
def setup_logger(log_path=None):
    # 判断调用者是否传入了 log_path 参数
    if log_path is None:
        # 如果没有传入 log_path，则从全局配置对象 conf 中读取默认的日志目录路径
        log_path = conf.log_path

    # 把日志目录路径和文件名 'app.log' 拼接在一起，得到完整的日志文件路径
    # os.path.join 能自动处理不同操作系统下的路径分隔符（Windows 用 \，Linux/Mac 用 /）
    log_file = os.path.join(log_path, 'app.log')

    # 创建日志目录（如果目录已存在则不会报错，exist_ok=True 的作用）
    # os.makedirs 会递归创建多级目录，比如如果父目录不存在也会一并创建
    os.makedirs(log_path, exist_ok=True)

    # 通过 logging.getLogger 获取一个名为 'RAGLogger' 的日志记录器实例
    # 如果同名 logger 已存在则直接返回，不存在则创建一个新的
    logger = logging.getLogger('RAGLogger')

    # 设置日志记录器的最低级别为 DEBUG（表示记录所有级别的日志）
    # 只有级别 >= DEBUG 的日志才会被处理，级别从低到高：DEBUG < INFO < WARNING < ERROR < CRITICAL
    logger.setLevel(logging.DEBUG)

    # 创建一个文件处理器（FileHandler），负责把日志写入到指定的文件中
    # encoding='utf-8' 指定文件编码为 UTF-8，防止中文日志出现乱码
    file_handler = logging.FileHandler(log_file, encoding='utf-8')

    # 创建一个控制台处理器（StreamHandler），负责把日志输出到终端/控制台
    console_handler = logging.StreamHandler()

    # 设置文件处理器的日志级别，从配置对象 conf.app_log_level 中读取
    # 只有达到这个级别及以上的日志才会被写入文件
    file_handler.setLevel(conf.app_log_level)

    # 设置控制台处理器的日志级别，从配置对象 conf.console_log_level 中读取
    # 只有达到这个级别及以上的日志才会在控制台显示
    console_handler.setLevel(conf.console_log_level)

    # 定义日志写入文件时的格式，格式模板从配置对象 conf.log_file_format 中读取
    # 常见的格式包含：时间、日志级别、模块名、行号、日志消息等
    file_formatter = logging.Formatter(conf.log_file_format)

    # 定义日志在控制台输出时的格式，格式模板从配置对象 conf.log_console_format 中读取
    # 控制台格式通常比文件格式更简洁，方便开发时查看
    console_formatter = logging.Formatter(conf.log_console_format)

    # 将上面定义好的文件格式器（file_formatter）绑定到文件处理器上
    # 这样文件处理器就知道用什么样的格式来写日志了
    file_handler.setFormatter(file_formatter)

    # 将上面定义好的控制台格式器（console_formatter）绑定到控制台处理器上
    # 这样控制台处理器就知道用什么样的格式来输出日志了
    console_handler.setFormatter(console_formatter)

    # 把文件处理器添加到日志记录器中，这样日志就会同时写入文件
    # 一个 logger 可以添加多个处理器，实现日志的多重输出（文件 + 控制台等）
    logger.addHandler(file_handler)

    # 把控制台处理器也添加到日志记录器中，这样日志会在控制台显示
    logger.addHandler(console_handler)

    # 返回配置好的日志记录器实例，供调用者使用
    return logger


# ========== 创建全局主日志记录器 ==========

# 调用上面定义的 setup_logger 函数，创建全局唯一的日志记录器实例
# 这个 logger 会在模块加载时自动创建，其他文件通过 "from base.logger import logger" 来使用
logger = setup_logger()


# ========== HTTP 请求专用日志记录器 ==========

# 把配置中的日志目录路径和文件名 'http.log' 拼接起来，得到 HTTP 日志的完整文件路径
_http_log_path = os.path.join(conf.log_path, 'http.log')

# 获取（或创建）一个名为 'HTTPLogger' 的日志记录器，专门用于记录 HTTP 请求日志
_http_logger = logging.getLogger('HTTPLogger')

# 设置 HTTP 日志记录器的日志级别，从配置对象 conf.http_log_level 中读取
# 只有达到这个级别及以上的 HTTP 日志才会被记录下来
_http_logger.setLevel(conf.http_log_level)

# 设置 propagate = False，禁止日志冒泡传递给父级 logger（即根 logger）
# 如果不设置这个，HTTP 日志会同时出现在 app.log 里，造成重复记录
_http_logger.propagate = False

# 创建一个文件处理器，专门把 HTTP 日志写入到 _http_log_path 指定的文件中
# encoding='utf-8' 确保日志中的中文字符能正常显示
_http_handler = logging.FileHandler(_http_log_path, encoding='utf-8')

# 设置 HTTP 日志处理器的日志格式：时间戳 + 消息内容
# '[%(asctime)s] %(message)s' 表示输出格式为 "[2024-01-01 12:00:00] 消息内容"
# datefmt='%Y-%m-%d %H:%M:%S' 指定了时间的显示格式：年-月-日 时:分:秒
_http_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# 把 HTTP 文件处理器添加到 HTTP 日志记录器中，使其生效
_http_logger.addHandler(_http_handler)


# ========== 用户 QA 问答专用日志记录器 ==========

# 把配置中的日志目录路径和文件名 'user.log' 拼接起来，得到用户问答日志的完整文件路径
_user_log_path = os.path.join(conf.log_path, 'user.log')

# 获取（或创建）一个名为 'UserLogger' 的日志记录器，专门用于记录用户问答日志
_user_logger = logging.getLogger('UserLogger')

# 设置用户问答日志记录器的日志级别
_user_logger.setLevel(conf.app_log_level)

# 设置 propagate = False，禁止日志冒泡传递给父级 logger
# 这样用户问答日志只会写入 user.log，不会出现在 app.log 里
_user_logger.propagate = False

# 创建一个文件处理器，专门把用户问答日志写入到 _user_log_path 指定的文件中
# encoding='utf-8' 确保中文问题和答案能正常写入日志文件
_user_handler = logging.FileHandler(_user_log_path, encoding='utf-8')

# 设置用户问答日志处理器的格式：时间戳 + 消息内容，与 HTTP 日志格式一致
_user_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# 把用户问答文件处理器添加到用户问答日志记录器中，使其生效
_user_logger.addHandler(_user_handler)


# ========== HTTP 请求日志记录函数 ==========

# 定义一个函数，用于记录 HTTP 请求的日志（比如哪个用户访问了什么地址、返回什么状态码）
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


# ========== 用户 QA 问答日志记录函数 ==========

# 定义一个函数，用于记录用户的问答对（问题和答案），方便后续分析和排查
# username: 提问的用户名
# session_id: 会话 ID，用于标识是同一次对话中的多个问答
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


# ========== 批量配置所有日志记录器 ==========

# 定义一个函数，用于批量修改所有已注册的日志记录器的日志级别和 propagate 属性
# level: 要设置的日志级别，默认为 logging.WARNING（只记录警告及以上级别的日志）
# propagate: 是否允许日志冒泡到父级 logger，默认为 False（不允许冒泡）
def batch_configure_loggers(level=logging.WARNING, propagate=False):
    """
    批量配置所有已注册的 logger，设置 propagate=False，防止日志冒泡到根 logger。
    """

    # 定义一个集合（set），存放需要保护的 logger 名称
    # 这些 logger 不会被批量修改，避免影响项目核心功能
    _protected = {'RAGLogger', 'HTTPLogger', 'UserLogger'}

    # 获取 logging 模块的日志记录器管理器（Logger.manager）
    # manager 是一个全局的管理器，管理着所有已注册的 logger 对象
    # type: logging.Manager 只是类型注解，提示开发者这个对象的类型
    manager = logging.Logger.manager  # type: logging.Manager

    # 遍历 manager 中存储的所有 logger
    # manager.loggerDict 是一个字典，key 是 logger 的名称，value 是 logger 对象
    for name, logger_obj in manager.loggerDict.items():
        # 判断获取到的对象是否是 logging.Logger 的实例（防止混入其他类型的对象）
        if isinstance(logger_obj, logging.Logger):
            # 判断当前 logger 的名称是否不在受保护的集合中
            if logger_obj.name not in _protected:
                # 设置该 logger 的 propagate 属性（是否冒泡）
                logger_obj.propagate = propagate
                # 设置该 logger 的日志级别（只记录 >= 该级别的日志）
                logger_obj.level = level


# ========== 脚本自测代码 ==========

# 判断当前文件是否被直接运行（而不是被其他模块导入）
# __name__ 是 Python 内置变量，当文件被直接运行时值为 '__main__'
if __name__ == "__main__":
    # 记录一条 DEBUG 级别的测试日志（最低级别，用于调试）
    logger.debug("这是一个调试日志")
    # 记录一条 INFO 级别的测试日志（用于记录一般信息）
    logger.info("这是一个信息日志")
    # 记录一条 WARNING 级别的测试日志（用于记录警告，表示可能有潜在问题）
    logger.warning("这是一个警告日志")
    # 记录一条 ERROR 级别的测试日志（用于记录错误，表示程序出现了问题）
    logger.error("这是一个错误日志")
