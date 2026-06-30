import hashlib
import json
import os
import threading
from datetime import datetime
from typing import List, Optional

import faiss
import numpy as np

from base.config import conf
from base.logger import logger

from .document import Document
from .document_process import process_documents_from_dir
from .openai_client import OpenAIClient


class VectorStore:
    """基于 OpenAI Embedding + FAISS 的本地向量存储"""

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
        logger.info(
            f"向量存储就绪: embedding={embedding_model}, dim={embedding_dim}, "
            f"当前文档数={len(self.metadata)}"
        )

    def _load_from_disk(self):
        if not (os.path.exists(self._dense_file) and os.path.exists(self._meta_file)):
            logger.info("未发现已有向量存储,将创建新的")
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
            logger.info(f"从磁盘加载向量存储: {len(self.dense_vectors)} 条记录")
        except Exception as e:
            logger.warning(f"加载向量存储失败,将重新创建: {e}")
            self.dense_vectors = []
            self.metadata = []
            self.dense_index = None

    def _save_to_disk(self):
        with self._lock:
            if self.dense_vectors:
                np.save(self._dense_file, np.array(self.dense_vectors, dtype=np.float32))
            elif os.path.exists(self._dense_file):
                os.remove(self._dense_file)
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def _rebuild_index(self):
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            faiss.normalize_L2(arr)
            self.dense_vectors = arr.tolist()
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None

    def _embed(self, texts: List[str]) -> np.ndarray:
        vectors = self.client.embed(texts, model=self.embedding_model)
        arr = np.array(vectors, dtype=np.float32)
        if arr.size == 0:
            return arr
        faiss.normalize_L2(arr)
        return arr

    def add_documents(self, documents: List[Document], partition: Optional[str] = None):
        texts = [doc.page_content for doc in documents]
        if not texts:
            return
        logger.info(f"开始嵌入 {len(texts)} 条文档分块,模型={self.embedding_model}")
        embeddings = self._embed(texts)
        logger.info(f"嵌入完成,开始写入本地向量库")
        with self._lock:
            for i, doc in enumerate(documents):
                text_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
                self.dense_vectors.append(embeddings[i].tolist())
                self.metadata.append({
                    "id": text_hash,
                    "text": doc.page_content,
                    "parent_id": doc.metadata.get("parent_chunk_id", ""),
                    "parent_text": doc.metadata.get("parent_content", ""),
                    "source": doc.metadata.get("source", ""),
                    "timestamp": doc.metadata.get("timestamp", datetime.now().isoformat()),
                    "partition": partition or "",
                    "chunk_type": doc.metadata.get("chunk_type", ""),
                    "section_path": doc.metadata.get("section_path", []),
                    "page": doc.metadata.get("page"),
                    "caption": doc.metadata.get("caption", ""),
                    "footnote": doc.metadata.get("footnote", ""),
                    "img_path": doc.metadata.get("img_path", ""),
                })
            self._rebuild_index()
            self._save_to_disk()
        logger.info(f"成功插入 {len(documents)} 条文档到本地向量存储")

    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        if partition:
            sources = {m["source"] for m in self.metadata if m["partition"] == partition}
        else:
            sources = {m["source"] for m in self.metadata}
        return list(sources)

    def delete_documents_by_partition(self, partition: Optional[str] = None):
        with self._lock:
            before = len(self.metadata)
            if partition:
                keep_indices = [i for i, m in enumerate(self.metadata) if m["partition"] != partition]
            else:
                keep_indices = []
            self._apply_keep_indices(keep_indices)
            removed = before - len(self.metadata)
        logger.info(f"删除分区 {partition} 文档: 移除 {removed} 条向量, 剩余 {len(self.metadata)} 条")

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
        logger.info(f"删除来源 {sources} 文档: 移除 {removed} 条向量, 剩余 {len(self.metadata)} 条")

    def _apply_keep_indices(self, keep_indices):
        keep_set = set(keep_indices)
        self.dense_vectors = [v for i, v in enumerate(self.dense_vectors) if i in keep_set]
        self.metadata = [m for i, m in enumerate(self.metadata) if i in keep_set]
        self._rebuild_index()
        self._save_to_disk()

    def store_documents_from_dir(self, directory, partition: Optional[str] = None):
        if not partition:
            logger.warning("未提供 partition,将存储至默认分区")
        documents = process_documents_from_dir(directory)
        if not documents:
            logger.warning(f"在目录 {directory} 中未找到任何文档。")
            return
        self.add_documents(documents, partition=partition)

    def search(
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
                    "parent_id": m.get("parent_id", ""),
                    "parent_text": m.get("parent_text", ""),
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
        unique_parents = self._get_unique_parent_docs(child_docs)
        return unique_parents[: conf.candidate_top_k]

    def _get_unique_parent_docs(self, docs: List[Document]) -> List[Document]:
        parent_contents = set()
        unique = []
        for doc in docs:
            parent_text = doc.metadata.get("parent_text") or doc.page_content
            if parent_text and parent_text not in parent_contents:
                parent_contents.add(parent_text)
                unique.append(Document(
                    page_content=parent_text,
                    metadata={
                        "id": doc.metadata.get("parent_id", ""),
                        "source": doc.metadata.get("source", ""),
                        "timestamp": doc.metadata.get("timestamp", ""),
                        "chunk_type": doc.metadata.get("chunk_type", ""),
                        "section_path": doc.metadata.get("section_path", []),
                        "page": doc.metadata.get("page"),
                        "caption": doc.metadata.get("caption", ""),
                        "footnote": doc.metadata.get("footnote", ""),
                        "img_path": doc.metadata.get("img_path", ""),
                    },
                ))
        return unique
