# 导入分词库
import jieba
# 导入日志
from base.logger import logger

def preprocess_text(text, info=True):
    """对输入文本进行预处理，包括分词和转换为小写"""
    # 记录预处理开始日志
    if info:
        logger.info(f"开始预处理文本")
    try:
        # 分词并转换为小写
        return jieba.lcut(text.lower())  # 转换为小写后分词

    except Exception as e:
        # 记录预处理失败日志
        logger.error(f"文本预处理失败: {e}")
        # 返回空列表
        return []

if __name__ == "__main__":
    # 测试预处理函数
    test_text = "这是一个测试文本。"
    processed = preprocess_text(test_text)
    print(processed)