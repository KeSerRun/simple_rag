# ── 向量存储 + 文档处理管线 ──────────────────────────────────────
"""向量存储 + 文档处理管线。

基于 OpenAI Embedding + FAISS 的本地向量存储，
以及文档加载、分块、过滤的完整预处理流程。
"""

from __future__ import annotations

import hashlib
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


# ── 文档容器 ──────────────────────────────────────────────────────


@dataclass
class Document:
    """轻量文档容器，替代 langchain_core.documents.Document。

    Attributes:
        page_content: 文档正文内容。
        metadata: 文档元数据字典。
    """
    page_content: str
    metadata: dict = field(default_factory=dict)


# ── 向量存储 ──────────────────────────────────────────────────────


class VectorStore:
    """基于 OpenAI Embedding + FAISS 的本地向量存储。

    支持文档添加、检索、分区管理、持久化与热加载。
    使用内积相似度（IndexFlatIP），向量在入库前经过 L2 归一化。

    Attributes:
        client: OpenAI 客户端实例。
        embedding_model: 嵌入模型名称。
        dimension: 嵌入向量维度。
        index_dir: 索引文件存储目录。
        dense_vectors: 稠密向量列表。
        metadata: 元数据列表，与向量一一对应。
        dense_index: FAISS 内积索引。
    """

    def __init__(
        self,
        client: OpenAIClient,
        embedding_model: str,
        embedding_dim: int,
        index_dir: Optional[str] = None,
    ):
        """初始化向量存储。

        Args:
            client: OpenAI 客户端实例。
            embedding_model: 嵌入模型名称。
            embedding_dim: 嵌入向量维度。
            index_dir: 索引文件存储目录；默认使用 conf.vector_store_dir。
        """
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
            f"当前分块数={len(self.metadata)}"
        )

    # ── 磁盘持久化 ────────────────────────────────────────────────

    def _load_from_disk(self):
        """从磁盘加载向量和元数据。

        维度不匹配时自动丢弃旧索引，需要重新嵌入。
        """
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

    def _save_to_disk(self):
        """将向量和元数据持久化到磁盘。"""
        with self._lock:
            if self.dense_vectors:
                np.save(self._dense_file, np.array(self.dense_vectors, dtype=np.float32))
            elif os.path.exists(self._dense_file):
                os.remove(self._dense_file)
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def _rebuild_index(self):
        """从当前向量重建 FAISS 索引。"""
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            faiss.normalize_L2(arr)
            self.dense_vectors = arr.tolist()
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None

    def _embed(self, texts: List[str]) -> np.ndarray:
        """对文本列表进行批量嵌入。

        Args:
            texts: 文本列表。

        Returns:
            归一化后的嵌入向量数组。

        Raises:
            嵌入失败时向上抛出原始异常。
        """
        try:
            vectors = self.client.embed(texts, model=self.embedding_model)
            arr = np.array(vectors, dtype=np.float32)
            if arr.size == 0:
                return arr
            faiss.normalize_L2(arr)
            return arr
        except Exception as e:
            logger.error(f"嵌入失败: {e}")
            raise

    # ── 文档写入 ──────────────────────────────────────────────────

    def add_documents(self, documents: List[Document], partition: Optional[str] = None):
        """添加文档到向量存储：嵌入 + 写入索引 + 持久化。

        Args:
            documents: Document 实例列表。
            partition: 分区标识（可选），用于按分区管理。
        """
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
        logger.debug(f"开始嵌入 {len(embed_texts)} 条文档分块,模型={self.embedding_model}")
        try:
            embeddings = self._embed(embed_texts)
        except Exception as e:
            logger.error(f"文档嵌入失败,跳过入库: {e}")
            return
        logger.debug(f"嵌入完成,开始写入本地向量库")
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
        logger.debug(f"成功插入 {len(documents)} 条文档到本地向量存储")

    # ── 文档查询与管理 ────────────────────────────────────────────

    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        """按分区查询文档来源列表。

        Args:
            partition: 分区标识；为 None 则返回所有来源。

        Returns:
            去重后的文档来源列表。
        """
        if partition:
            sources = {m["source"] for m in self.metadata if m["partition"] == partition}
        else:
            sources = {m["source"] for m in self.metadata}
        return list(sources)

    def delete_documents_by_partition(self, partition: Optional[str] = None):
        """按分区删除文档。

        Args:
            partition: 分区标识；为 None 则清空所有文档。
        """
        with self._lock:
            before = len(self.metadata)
            if partition:
                keep_indices = [i for i, m in enumerate(self.metadata) if m["partition"] != partition]
            else:
                keep_indices = []
            self._apply_keep_indices(keep_indices)
            removed = before - len(self.metadata)
        logger.debug(f"清理分区 {partition}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

    def delete_documents_by_sources(self, sources, partition: Optional[str] = None):
        """按文档来源删除。

        Args:
            sources: 来源文件名集合。
            partition: 可选的分区过滤。
        """
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
        logger.debug(f"按来源删除文档 {sources}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

    def _apply_keep_indices(self, keep_indices):
        """应用保留索引列表，删除其余向量和元数据。

        Args:
            keep_indices: 需要保留的索引列表。
        """
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

    def store_documents_from_dir(self, directory, partition: Optional[str] = None):
        """从目录加载并存储文档到向量库。

        Args:
            directory: 文档目录或文件路径。
            partition: 分区标识。
        """
        if not partition:
            logger.warning("未提供 partition,将存储至默认分区")
        documents = process_documents_from_dir(directory)
        if not documents:
            raise RuntimeError(f"未从 {directory} 解析到任何文档（请检查 MinerU 是否可用）")
        self.add_documents(documents, partition=partition)

    # ── 检索 ──────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = None,
        source_filter: Optional[str] = None,
        partition: Optional[str] = None,
    ) -> List[Document]:
        """检索与查询最相关的文档片段。

        Args:
            query: 查询文本。
            top_k: 返回结果数；默认 conf.retrieval_top_k。
            source_filter: 来源过滤。
            partition: 分区过滤。

        Returns:
            检索到的 Document 列表，已去重。
        """
        with self._lock:
            return self._search_impl(query, top_k, source_filter, partition)

    def _search_impl(
        self,
        query: str,
        top_k: int = None,
        source_filter: Optional[str] = None,
        partition: Optional[str] = None,
    ) -> List[Document]:
        """检索实现（需在持有锁的情况下调用）。

        Args:
            query: 查询文本。
            top_k: 返回结果数。
            source_filter: 来源过滤。
            partition: 分区过滤。

        Returns:
            检索到的 Document 列表，已去重。
        """
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


# ── 文档加载与处理管线 ────────────────────────────────────────────


document_loaders = {
    "pdf": MinerUPDFLoader,
}


def load_sigle_document(root, file_name):
    """加载单个文档文件。

    根据文件扩展名选择对应的加载器。

    Args:
        root: 文件所在目录。
        file_name: 文件名。

    Returns:
        Document 列表，失败返回 None。
    """
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
            logger.debug(f"成功加载文档: {file_path}")
            return doc
        except Exception as e:
            logger.error(f"加载文档失败: {file_path}, 错误: {e}")
    else:
        logger.warning(f"不支持的文件类型: {file_name}")
    return None


def load_documents_from_dir(directory):
    """递归加载目录下所有支持的文档。

    Args:
        directory: 文档目录路径。

    Returns:
        拼接后的 Document 列表。
    """
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            doc = load_sigle_document(root, file)
            if doc:
                documents.extend(doc)
    return documents


def load_documents_from_file(file_path):
    """加载单个文档文件。

    Args:
        file_path: 文件路径。

    Returns:
        Document 列表，失败返回空列表。
    """
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    return doc if doc else []


def process_documents_from_dir(directory) -> List[Document]:
    """加载文档，每个 MinerU 原始块直接入库。

    对 text 类型块执行最短长度过滤和停用词过滤。

    Args:
        directory: 文档目录或文件路径。

    Returns:
        处理后的 Document 列表。
    """
    if os.path.isdir(directory):
        documents = load_documents_from_dir(directory)
    elif os.path.isfile(directory):
        documents = load_documents_from_file(directory)
    else:
        logger.error(f"无效的路径: {directory}")
        return []
    logger.debug(f"加载的文档数量: {len(documents)}")

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
