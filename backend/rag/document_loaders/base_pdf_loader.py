"""Base PDF loader: OCR 引擎 + BaseLoader + OCRPDFLoader"""
from __future__ import annotations

from typing import Iterator, List

import cv2
import fitz
import numpy as np
from PIL import Image
from tqdm import tqdm

from base.logger import logger

import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='paddle.utils.cpp_extension')

# ─── OCR 引擎 ───────────────────────────────────

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

# ─── BaseLoader ─────────────────────────────────

class BaseLoader:
    """轻量 BaseLoader, 替代 langchain_core.document_loaders.BaseLoader。"""
    def lazy_load(self) -> Iterator[Document]:
        raise NotImplementedError

    def load(self) -> List[Document]:
        return list(self.lazy_load())

# ─── OCR PDF Loader ─────────────────────────────

PDF_OCR_THRESHOLD = (0.1, 0.05)


class OCRPDFLoader(BaseLoader):
    """PyMuPDF + OCR 兜底的 PDF 加载器。"""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        from ..core.document_process import Document
        line = self.pdf2text()
        yield Document(page_content=line, metadata={"source": self.file_path})

    def pdf2text(self):
        ocr = get_ocr_engine()
        doc = fitz.open(self.file_path)
        resp = ""
        b_unit = tqdm(total=doc.page_count, desc="OCRPDFLoader context page index: 0")
        for i, page in enumerate(doc):
            b_unit.set_description("OCRPDFLoader context page index: {}".format(i))
            b_unit.refresh()
            text = page.get_text("text")
            resp += text + "\n"
            img_list = page.get_image_info(xrefs=True)
            for img in img_list:
                if xref := img.get("xref"):
                    bbox = img["bbox"]
                    if ((bbox[2] - bbox[0]) / (page.rect.width) < PDF_OCR_THRESHOLD[0]
                            or (bbox[3] - bbox[1]) / (page.rect.height) < PDF_OCR_THRESHOLD[1]):
                        continue
                    pix = fitz.Pixmap(doc, xref)
                    if int(page.rotation) != 0:
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)
                        tmp_img = Image.fromarray(img_array)
                        ori_img = cv2.cvtColor(np.array(tmp_img), cv2.COLOR_RGB2BGR)
                        rot_img = self.rotate_img(img=ori_img, angle=360 - page.rotation)
                        img_array = cv2.cvtColor(rot_img, cv2.COLOR_RGB2BGR)
                    else:
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)
                    result, _ = ocr(img_array)
                    if result:
                        ocr_result = [line[1] for line in result]
                        resp += "\n".join(ocr_result)
            b_unit.update(1)
        return resp
