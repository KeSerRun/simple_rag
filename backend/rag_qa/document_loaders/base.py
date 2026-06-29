from typing import Iterator, List

from base.logger import logger

from ..core.document import Document

'''
paddleocr：解析图片中的文字，也可以进行表格识别
rapidocr_paddle 和 rapidocr_onnxruntime 两种导入方式
主要区别在于它们所使用的推理引擎和硬件支持，选择哪种方式最合适取决于你的硬件环境和性能需求。
- 当你有 GPU 且追求速度时：使用 rapidocr_paddle。PaddlePaddle 原生支持在 GPU 上推理 PaddleOCR 模型，速度更快。
- 当只有 CPU 且需要高效推理时：使用 rapidocr_onnxruntime。它在 CPU 上进行了优化，资源占用较低.
'''

# 忽略 PaddlePaddle 相关的用户警告
import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='paddle.utils.cpp_extension')


class BaseLoader:
    """轻量 BaseLoader,替代 langchain_core.document_loaders.BaseLoader。

    子类需实现 `lazy_load()` -> Iterator[Document]。`load()` 提供默认实现。
    """

    def lazy_load(self) -> Iterator[Document]:
        raise NotImplementedError

    def load(self) -> List[Document]:
        return list(self.lazy_load())


# 选择合适的 OCR 引擎
def get_ocr_engine(device='cpu'):
    if device == 'gpu':
        try:
            from rapidocr_paddle import RapidOCR
            logger.info("成功加载 GPU 加速的 OCR 引擎")
            return RapidOCR()
        except ImportError:
            logger.warning("ocr 引擎 gpu 选择失败，回退到 cpu")
            from rapidocr_onnxruntime import RapidOCR
            return RapidOCR()
    else:
        from rapidocr_onnxruntime import RapidOCR
        logger.info("成功加载 CPU 版本的 OCR 引擎")
        return RapidOCR()


if __name__ == "__main__":
    ocr_engine = get_ocr_engine(device='gpu')
    test_image = "test_image.png"
    result = ocr_engine(test_image)
    print(result)
