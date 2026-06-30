from typing import Iterator, List

from base.logger import logger

from ..core.document import Document

import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='paddle.utils.cpp_extension')


class BaseLoader:
    def lazy_load(self) -> Iterator[Document]:
        raise NotImplementedError

    def load(self) -> List[Document]:
        return list(self.lazy_load())


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
