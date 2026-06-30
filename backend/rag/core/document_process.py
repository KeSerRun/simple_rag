"""文档加载与分块入口(MinerU 已预切块则跳过二次切分)"""
import os
from datetime import datetime
from typing import Iterator, List

from base.config import conf
from base.logger import logger, batch_configure_loggers

from ..document_loaders import MinerUPDFLoader, OCRPDFLoader
from ..document_loaders.base import BaseLoader
from ..text_spliter import ChineseRecursiveTextSplitter
from .document import Document

batch_configure_loggers()


class PlainTextLoader(BaseLoader):
    def __init__(self, file_path: str, encoding: str = "utf-8"):
        self.file_path = file_path
        self.encoding = encoding

    def lazy_load(self) -> Iterator[Document]:
        text = self._read()
        yield Document(page_content=text, metadata={"source": self.file_path})

    def _read(self) -> str:
        for enc in (self.encoding, "utf-8", "gbk", "latin-1"):
            try:
                with open(self.file_path, "r", encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        with open(self.file_path, "rb") as f:
            return f.read().decode("utf-8", errors="ignore")


document_loaders = {
    "pdf": MinerUPDFLoader,
    "txt": PlainTextLoader,
    "md": PlainTextLoader,
}


def load_sigle_document(root, file_name):
    supported_extensions = document_loaders.keys()
    ext = file_name.split(".")[-1].lower()
    if ext in supported_extensions:
        file_path = os.path.join(root, file_name)
        try:
            loader_class = document_loaders[ext]
            loader = loader_class(file_path)
            doc = loader.load()
            for d in doc:
                d.metadata["file_path"] = file_path
                d.metadata["source"] = file_name
                d.metadata["extension"] = ext
                d.metadata["timestamp"] = datetime.now().isoformat()
            logger.info(f"成功加载文档: {file_path}")
            return doc
        except Exception as e:
            logger.error(f"加载文档失败: {file_path}, 错误: {e}")
    else:
        logger.warning(f"不支持的文件类型: {file_name}")
    return None


def load_documents_from_dir(directory):
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            doc = load_sigle_document(root, file)
            if doc:
                documents.extend(doc)
    return documents


def load_documents_from_file(file_path):
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    return doc if doc else []


def process_documents_from_dir(
    directory,
    parent_chunk_size: int = conf.parent_chunk_size,
    child_chunk_size: int = conf.child_chunk_size,
    chunk_overlap: int = conf.chunk_overlap,
) -> List[Document]:
    if os.path.isdir(directory):
        documents = load_documents_from_dir(directory)
    elif os.path.isfile(directory):
        documents = load_documents_from_file(directory)
    else:
        logger.error(f"无效的路径: {directory}")
        return []
    logger.info(f"加载的文档数量: {len(documents)}")
    parent_splitter = ChineseRecursiveTextSplitter(chunk_size=parent_chunk_size, chunk_overlap=chunk_overlap)
    child_splitter = ChineseRecursiveTextSplitter(chunk_size=child_chunk_size, chunk_overlap=chunk_overlap)
    child_chunk_list: List[Document] = []
    for i, doc in enumerate(documents):
        doc_name = doc.metadata.get("source", f"文档_{i}")
        if doc.metadata.get("pre_chunked"):
            chunk_id = f"doc_{i}_chunk_0"
            doc.metadata["parent_chunk_id"] = chunk_id
            doc.metadata["parent_content"] = doc.page_content
            doc.metadata["child_chunk_id"] = chunk_id
            child_chunk_list.append(doc)
            logger.info(f"文档: {doc_name} 已预切块, 直接入库 (1 块)")
            continue
        logger.info(f"使用切分器: {parent_splitter.__class__.__name__} 处理文档: {doc_name}")
        parent_chunks = parent_splitter.split_documents([doc])
        logger.info(f"文档: {doc_name} 的父级切分块数量: {len(parent_chunks)}")
        child_count = 0
        for j, parent_chunk in enumerate(parent_chunks):
            parent_chunk_id = f"doc_{i}_parent_{j}"
            child_chunks = child_splitter.split_documents([parent_chunk])
            for k, child_chunk in enumerate(child_chunks):
                child_chunk_id = f"{parent_chunk_id}_child_{k}"
                child_chunk.metadata["parent_chunk_id"] = parent_chunk_id
                child_chunk.metadata["parent_content"] = parent_chunk.page_content
                child_chunk.metadata["child_chunk_id"] = child_chunk_id
                child_chunk_list.append(child_chunk)
                child_count += 1
        logger.info(f"文档: {doc_name} 的子级切分块数量: {child_count}")
    logger.info(f"文档切分完成,生成的子级切分块总数量: {len(child_chunk_list)}")
    return child_chunk_list
