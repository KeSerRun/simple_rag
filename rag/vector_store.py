"""向量存储 + 文档处理管线。"""

from __future__ import annotations

import hashlib
# ---- 向量索引核心 ----
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, List, Optional

import faiss
import numpy as np

from base.config import conf
from base.logger import logger

from .pdf_parser import MinerUPDFLoader
from base.llm_client import OpenAIClient
# ---- 文档处理管线 ----


# ---- VectorStore ----
class VectorStore:
    """基于 OpenAI Embedding + FAISS 的本地向量存储"""

# ---- __init__ ----
    def __init__(
        self,
        client: OpenAIClient,
        embedding_model: str,
        embedding_dim: int,
        index_dir: Optional[str] = None,
    ):
        self.client = client
        self.embedding_model = embedding_model
        self.dimension = embedding_dim
        self.index_dir = index_dir or conf.vector_store_dir
        os.makedirs(self.index_dir, exist_ok=True)

        self._dense_file = os.path.join(self.index_dir, "dense_vectors.npy")
        self._meta_file = os.path.join(self.index_dir, "metadata.json")
        self._lock = threading.RLock()

        self.dense_vectors: List[List[float]] = []
        self.metadata: List[dict] = []
        self.dense_index: Optional[faiss.IndexFlatIP] = None

        self._load_from_disk()
        logger.debug(
            f"向量存储就绪: embedding={embedding_model}, dim={embedding_dim}, "
            f"当前文档数={len(self.metadata)}"
        )

# ---- _load_from_disk ----
    def _load_from_disk(self):
        if not (os.path.exists(self._dense_file) and os.path.exists(self._meta_file)):
            logger.debug("未发现已有向量存储,将创建新的")
            return
        try:
            arr = np.load(self._dense_file)
            if arr.size and arr.shape[1] != self.dimension:
                logger.warning(
                    f"已有索引维度 {arr.shape[1]} 与配置维度 {self.dimension} 不一致,丢弃旧索引,需要重新嵌入"
                )
                self.dense_vectors = []
                self.metadata = []
                self.dense_index = None
                return
            self.dense_vectors = arr.tolist()
            with open(self._meta_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            for m in self.metadata:
                m.pop("sparse_vector", None)
            self._rebuild_index()
            logger.debug(f"从磁盘加载向量存储: {len(self.dense_vectors)} 条记录")
        except Exception as e:
            logger.warning(f"加载向量存储失败,将重新创建: {e}")
            self.dense_vectors = []
            self.metadata = []
            self.dense_index = None

# ---- _save_to_disk ----
    def _save_to_disk(self):
        with self._lock:
            if self.dense_vectors:
                np.save(self._dense_file, np.array(self.dense_vectors, dtype=np.float32))
            elif os.path.exists(self._dense_file):
                os.remove(self._dense_file)
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)

# ---- _rebuild_index ----
    def _rebuild_index(self):
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            faiss.normalize_L2(arr)
            self.dense_vectors = arr.tolist()
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None

# ---- _embed ----
    def _embed(self, texts: List[str]) -> np.ndarray:
        try:
            vectors = self.client.embed(texts, model=self.embedding_model)
            arr = np.array(vectors, dtype=np.float32)
            if arr.size == 0:
                return arr
            faiss.normalize_L2(arr)
            return arr
        except Exception as e:
            logger.error(f"嵌入失败: {e}")
            raise  # 调用方 add_documents 会捕获并处理

# ---- add_documents ----
    def add_documents(self, documents: List[Document], partition: Optional[str] = None):
# ---- _embed_text ----
        def _embed_text(doc):
            parts = [
                doc.metadata.get("source", ""),
                doc.page_content,
                doc.metadata.get("footnote", ""),
            ]
            return "\n".join(p for p in parts if p)

        embed_texts = [_embed_text(doc) for doc in documents]
        if not embed_texts:
            return
        logger.info(f"开始嵌入 {len(embed_texts)} 条文档分块,模型={self.embedding_model}")
        try:
            embeddings = self._embed(embed_texts)
        except Exception as e:
            logger.error(f"文档嵌入失败,跳过入库: {e}")
            return
        logger.info(f"嵌入完成,开始写入本地向量库")
        with self._lock:
            for i, doc in enumerate(documents):
                text_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
                self.dense_vectors.append(embeddings[i].tolist())
                self.metadata.append({
                    "id": text_hash,
                    "text": doc.page_content,
                    "source": doc.metadata.get("source", ""),
                    "timestamp": doc.metadata.get("timestamp", datetime.now().isoformat()),
                    "partition": partition or "",
                    "chunk_type": doc.metadata.get("chunk_type", ""),
                    "page": doc.metadata.get("page"),
                    "img_path": doc.metadata.get("img_path") if doc.metadata.get("chunk_type") != "table" else "",
                    "footnote": doc.metadata.get("footnote", ""),
                    "table_body": doc.metadata.get("table_body", ""),
                })
            if self.dense_index is None:
                self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(embeddings)
            self._save_to_disk()
        logger.info(f"成功插入 {len(documents)} 条文档到本地向量存储")

# ---- get_documents_by_partition ----
    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        if partition:
            sources = {m["source"] for m in self.metadata if m["partition"] == partition}
        else:
            sources = {m["source"] for m in self.metadata}
        return list(sources)

# ---- delete_documents_by_partition ----
    def delete_documents_by_partition(self, partition: Optional[str] = None):
        with self._lock:
            before = len(self.metadata)
            if partition:
                keep_indices = [i for i, m in enumerate(self.metadata) if m["partition"] != partition]
            else:
                keep_indices = []
            self._apply_keep_indices(keep_indices)
            removed = before - len(self.metadata)
        logger.info(f"清理分区 {partition}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

# ---- delete_documents_by_sources ----
    def delete_documents_by_sources(self, sources, partition: Optional[str] = None):
        with self._lock:
            before = len(self.metadata)
            keep_indices = []
            for i, m in enumerate(self.metadata):
                if m["source"] in sources:
                    if partition and m["partition"] != partition:
                        keep_indices.append(i)
                else:
                    keep_indices.append(i)
            self._apply_keep_indices(keep_indices)
            removed = before - len(self.metadata)
        logger.info(f"按来源删除文档 {sources}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

# ---- _apply_keep_indices ----
    def _apply_keep_indices(self, keep_indices):
        keep_set = set(keep_indices)
        self.dense_vectors = [v for i, v in enumerate(self.dense_vectors) if i in keep_set]
        self.metadata = [m for i, m in enumerate(self.metadata) if i in keep_set]
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None
        self._save_to_disk()

# ---- store_documents_from_dir ----
    def store_documents_from_dir(self, directory, partition: Optional[str] = None):
        if not partition:
            logger.warning("未提供 partition,将存储至默认分区")
        documents = process_documents_from_dir(directory)
        if not documents:
            raise RuntimeError(f"未从 {directory} 解析到任何文档（请检查 MinerU 是否可用）")
        self.add_documents(documents, partition=partition)

# ---- search ----
    def search(
        self,
        query: str,
        top_k: int = None,
        source_filter: Optional[str] = None,
        partition: Optional[str] = None,
    ) -> List[Document]:
        with self._lock:
            return self._search_impl(query, top_k, source_filter, partition)

# ---- _search_impl ----
    def _search_impl(
        self,
        query: str,
        top_k: int = None,
        source_filter: Optional[str] = None,
        partition: Optional[str] = None,
    ) -> List[Document]:
        if not self.dense_index or not self.metadata:
            logger.warning("向量存储为空,无法执行检索")
            return []
        top_k = top_k or conf.retrieval_top_k
        q_vec = self._embed([query])
        if q_vec.size == 0:
            return []
        search_n = min(top_k * 4, len(self.metadata))
        scores, ids = self.dense_index.search(q_vec, search_n)

        candidates = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

# ---- keep ----
        def keep(meta):
            if partition and meta.get("partition", "") != partition:
                return False
            if source_filter and meta.get("source", "") != source_filter:
                return False
            return True

        filtered = [(i, s) for i, s in candidates if keep(self.metadata[i])]
        filtered = filtered[: top_k * 2]
        if not filtered:
            return []
        child_docs: List[Document] = []
        for idx, _ in filtered[:top_k]:
            m = self.metadata[idx]
            child_docs.append(Document(
                page_content=m.get("text", ""),
                metadata={
                    "id": m.get("id", ""),
                    "source": m.get("source", ""),
                    "timestamp": m.get("timestamp", ""),
                    "chunk_type": m.get("chunk_type", ""),
                    "section_path": m.get("section_path", []),
                    "page": m.get("page"),
                    "caption": m.get("caption", ""),
                    "footnote": m.get("footnote", ""),
                    "img_path": m.get("img_path", ""),
                },
            ))

        seen = set()
        unique = []
        for doc in child_docs:
            key = doc.page_content
            if key and key not in seen:
                unique.append(doc)
        return unique[: top_k]

"""文档加载与分块入口(MinerU 已预切块则跳过二次切分)"""

@dataclass
# ---- Document ----
class Document:
    """轻量文档容器,替代 langchain_core.documents.Document"""
    page_content: str
    metadata: dict = field(default_factory=dict)


# ---- _BaseLoader ----
class _BaseLoader:
    """轻量 BaseLoader。"""
# ---- lazy_load ----
    def lazy_load(self) -> Iterator[Document]:
        raise NotImplementedError
# ---- load ----
    def load(self) -> List[Document]:
        return list(self.lazy_load())


document_loaders = {
    "pdf": MinerUPDFLoader,
}


# ---- load_sigle_document ----
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


# ---- load_documents_from_dir ----
def load_documents_from_dir(directory):
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            doc = load_sigle_document(root, file)
            if doc:
                documents.extend(doc)
    return documents


# ---- load_documents_from_file ----
def load_documents_from_file(file_path):
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    return doc if doc else []


# ---- process_documents_from_dir ----
def process_documents_from_dir(directory) -> List[Document]:
    """加载文档，每个 MinerU 原始块直接入库。"""
    if os.path.isdir(directory):
        documents = load_documents_from_dir(directory)
    elif os.path.isfile(directory):
        documents = load_documents_from_file(directory)
    else:
        logger.error(f"无效的路径: {directory}")
        return []
    logger.info(f"加载的文档数量: {len(documents)}")

    min_len = conf.min_chunk_length
    before = len(documents)
    documents = [
        d for d in documents
        if d.metadata.get("chunk_type") != "text" or len(d.page_content) >= min_len
    ]
    if before != len(documents):
        logger.debug(f"过滤短文本块: {before} → {len(documents)} (最短 {min_len} 字符)")

    stop_words = conf.stop_words
    before = len(documents)
    documents = [
        d for d in documents
        if d.metadata.get("chunk_type") != "text"
        or not any(w in d.page_content for w in stop_words)
    ]
    if before != len(documents):
        logger.debug(f"过滤停用词块: {before} → {len(documents)}")

    logger.info(f"文档处理完成, 共 {len(documents)} 个块")
    return documents

# ===== 向量存储核心：索引/检索/持久化 =====

# ===== 文档处理管线：切分/嵌入/存储 =====

# ===== 分区管理：用户分区 + 系统分区 =====
