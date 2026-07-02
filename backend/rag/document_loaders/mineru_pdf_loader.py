"""基于 MinerU API 的 PDF 加载器 (MinerU 优先, OCR 兜底)"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from base.config import conf
from base.logger import logger

from .base_pdf_loader import BaseLoader, OCRPDFLoader


class MinerUPDFLoader(BaseLoader):
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        from ..core.document_process import Document
        path = Path(self.file_path)
        try:
            from ..pdf_spliter.chunker import chunk_content_list
            from ..pdf_spliter.mineru_client import MinerUClient, MinerUError
        except ImportError as e:
            logger.warning(f"MinerU 依赖缺失 ({e}), 回退到 OCRPDFLoader: {path.name}")
            yield from OCRPDFLoader(self.file_path).lazy_load()
            return
        try:
            client = MinerUClient(token=conf.mineru_api_key or None)
        except MinerUError as e:
            logger.warning(f"MinerU 不可用 ({e}), 回退到 OCRPDFLoader: {path.name}")
            yield from OCRPDFLoader(self.file_path).lazy_load()
            return
        try:
            work_dir = path.parent / "chunk_out" / path.stem
            out_dir = client.parse_pdf(
                path, work_dir=work_dir,
                model_version=conf.mineru_model_version,
                language=conf.mineru_language,
            )
        except Exception as e:
            logger.warning(f"MinerU 解析失败 ({e}), 回退到 OCRPDFLoader: {path.name}")
            yield from OCRPDFLoader(self.file_path).lazy_load()
            return
        candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
        if not candidates:
            logger.warning(f"MinerU 输出未找到 content_list.json, 回退到 OCRPDFLoader: {path.name}")
            yield from OCRPDFLoader(self.file_path).lazy_load()
            return
        content = json.loads(candidates[0].read_text(encoding="utf-8"))
        doc_meta = {"doc_id": path.stem, "doc_title": path.stem}
        chunks = chunk_content_list(content, doc_meta)
        if not chunks:
            logger.warning(f"MinerU 切块结果为空, 回退到 OCRPDFLoader: {path.name}")
            yield from OCRPDFLoader(self.file_path).lazy_load()
            return
        logger.info(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        for ch in chunks:
            content_text = ch.get("content", "")
            if not content_text:
                continue
            yield Document(
                page_content=content_text,
                metadata={
                    "source": self.file_path,
                    "pre_chunked": True,
                    "chunk_type": ch.get("chunk_type", ""),
                    "section_path": ch.get("section_path", []),
                    "page": ch.get("page"),
                    "caption": ch.get("caption", ""),
                    "footnote": ch.get("footnote", ""),
                    "img_path": ch.get("img_path", ""),
                },
            )
