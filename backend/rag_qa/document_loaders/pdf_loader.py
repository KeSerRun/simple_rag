# edu_document_loaders/edu_pdfloader.py 源码
import cv2
import fitz  # pip install pyMuPDF
import numpy as np
from PIL import Image
from tqdm import tqdm
from typing import Iterator
from .base import get_ocr_engine as get_ocr, BaseLoader
from ..core.document import Document
# PDF OCR 控制：只对宽高超过页面一定比例（图片宽/页面宽，图片高/页面高）的图片进行 OCR。
# 这样可以避免 PDF 中一些小图片的干扰，提高非扫描版 PDF 处理速度
# 默认图片宽/页面宽 < 0.1 或 图片高/页面高 < 0.05 则跳过 OCR
PDF_OCR_THRESHOLD = (0.1, 0.05)  

class OCRPDFLoader(BaseLoader):
    """An example document loader that reads a file line by line."""

    def __init__(self, file_path: str) -> None:
        """Initialize the loader with a file path.

        Args:
            file_path: The path to the file to load.
        """
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        # <-- Does not take any arguments
        """A lazy loader that reads a file line by line.

        When you're implementing lazy load methods, you should use a generator
        to yield documents one by one.
        """

        line = self.pdf2text()
        yield Document(page_content=line, metadata={"source": self.file_path})

    def pdf2text(self):
        '''将 PDF 文件中的文本和图片中的文本提取出来，返回一个字符串'''
        ocr = get_ocr()
        # 打开pdf文件
        doc = fitz.open(self.file_path)
        ## 获取页数
        # print(f'len(doc)-->{len(doc)}')
        resp = ""
        b_unit = tqdm(total=doc.page_count, desc="OCRPDFLoader context page index: 0")
        for i, page in enumerate(doc):
            b_unit.set_description("OCRPDFLoader context page index: {}".format(i))
            b_unit.refresh()
            # 提取文本：默认使用 "text" 模式提取文本。
            text = page.get_text("text")
            resp += text + "\n"
            # print(f'resp-->{resp}')
            # 获取图片：获得所有显示的图像的元信息列表。
            # 它适用于所有文档类型，不仅限于 PDF。
            img_list = page.get_image_info(xrefs=True)
            # print(f'img_list ==> {img_list}')
            # print(f'img_list ==> {len(img_list)}')
            for img in img_list:
                # xref一种编号，指向该图像对象在PDF文件中的位置，程序可以通过这个编号快速定位和提取图像数据。
                if xref := img.get("xref"):
                    # 图像在页面上的位置和尺寸。
                    bbox = img["bbox"]
                    # 检查图片尺寸是否超过设定的阈值
                    if ((bbox[2] - bbox[0]) / (page.rect.width) < PDF_OCR_THRESHOLD[0]
                            or (bbox[3] - bbox[1]) / (page.rect.height) < PDF_OCR_THRESHOLD[1]):
                        continue
                    pix = fitz.Pixmap(doc, xref)
                    # print(f'page.rotation-->{page.rotation}')
                    if int(page.rotation) != 0:  # 如果Page有旋转角度，则旋转图片
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)
                        tmp_img = Image.fromarray(img_array)
                        ori_img = cv2.cvtColor(np.array(tmp_img), cv2.COLOR_RGB2BGR)
                        rot_img = self.rotate_img(img=ori_img, angle=360 - page.rotation)
                        img_array = cv2.cvtColor(rot_img, cv2.COLOR_RGB2BGR)
                    else:
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)

                    # result：包含了图像中检测到的所有文本框的位置、文本内容和置信度信息。
                    # _：它是一个包含了时间数据的列表，可以用于优化模型运行速度。
                    result, _ = ocr(img_array)
                    if result:
                        ocr_result = [line[1] for line in result]
                        resp += "\n".join(ocr_result)
            # 更新进度
            b_unit.update(1)
        return resp

if __name__ == '__main__':
    from rich import print
    pdf_loader = OCRPDFLoader(file_path="./data/test.pdf")
    doc = pdf_loader.load()

    print(type(doc))
    print(doc[0].page_content)
