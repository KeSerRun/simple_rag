# 导入配置类
from .config import conf
# 导入日志模块
import logging
# 导入路径操作模块
import os

def setup_logger(log_file=conf.log_file):
    # 创建日志目录
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    # 配置日志记录器
    logger = logging.getLogger('RAGLogger')
    # 设置日志级别
    logger.setLevel(logging.DEBUG)
    # 创建日志文件处理器
    file_handler = logging.FileHandler(log_file,encoding='utf-8')
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    # 设置日志级别
    file_handler.setLevel(conf.log_file_level)
    console_handler.setLevel(conf.log_console_level)
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

def batch_configure_loggers(level=logging.WARNING,propagate=False):
    """
    批量配置所有已注册的 logger，设置 propagate=False，防止日志冒泡到根 logger。
    """
    # 获取所有已注册的 logger
    manager = logging.Logger.manager # type: logging.Manager
    # 遍历 loggerDict 中的所有 logger 对象
    for name, logger_obj in manager.loggerDict.items():
        # logger_obj 可能是 Logger 实例，也可能是 PlaceHolder（占位符），需要检查类型
        if isinstance(logger_obj, logging.Logger):
            if logger_obj.name != 'RAGLogger':  # 避免修改 RAGLogger 的配置
                # 关闭 propagate 属性，防止日志冒泡到根 logger
                logger_obj.propagate = propagate
                # 设置日志级别，过滤掉 DEBUG 和 INFO 日志
                logger_obj.level = level  


if __name__ == "__main__":
    logger.debug("这是一个调试日志")
    logger.info("这是一个信息日志")
    logger.warning("这是一个警告日志")
    logger.error("这是一个错误日志")