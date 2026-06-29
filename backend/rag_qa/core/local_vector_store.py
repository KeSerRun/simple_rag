import hashlib
import json
import os
import re
import threading
from datetime import datetime
from typing import List, Optional

import faiss
import numpy as np

from base.config import conf
from base.logger import logger

from .context_builder import ContextBuilder
from .document import Document
from .document_process import process_documents_from_dir
from .openai_client import OpenAIClient


class VectorStore:
    """基于 OpenAI Embedding + FAISS 的本地向量存储

    存储布局 (index_dir / conf.vector_store_dir):
        dense_vectors.npy     - N×dim float32 稠密向量矩阵
        metadata.json         - 与矩阵行对应的文档元数据列表
    """

    def __init__(
        self,
        client: OpenAIClient,
        embedding_model: str,
        embedding_dim: int,
        enable_llm_rerank: bool = False,
        chat_model: Optional[str] = None,
        chat_client: Optional[OpenAIClient] = None,
        context_builder: Optional[ContextBuilder] = None,
        index_dir: Optional[str] = None,
    ):
        # client 专用于 embedding;chat_client 专用于 LLM rerank,默认复用 client
        self.client = client
        self.chat_client = chat_client or client
        # rerank 用 ContextBuilder 加载 prompt,仅当 enable_llm_rerank=True 时必需
        self.context_builder = context_builder
        if enable_llm_rerank and context_builder is None:
            raise ValueError("enable_llm_rerank=True 但未提供 context_builder")
        self.embedding_model = embedding_model
        self.dimension = embedding_dim
        self.enable_llm_rerank = enable_llm_rerank
        # rerank 用的 chat 模型,默认复用主 chat_model
        self.chat_model = chat_model or conf.chat_model
        self.index_dir = index_dir or conf.vector_store_dir
        os.makedirs(self.index_dir, exist_ok=True)

        self._dense_file = os.path.join(self.index_dir, "dense_vectors.npy")
        self._meta_file = os.path.join(self.index_dir, "metadata.json")
        # 用可重入锁:add_documents/_apply_keep_indices 持锁后还会调用 _save_to_disk,
        # 而 _save_to_disk 内部也要持锁,普通 Lock 会自死锁
        self._lock = threading.RLock()

        self.dense_vectors: List[List[float]] = []
        self.metadata: List[dict] = []
        self.dense_index: Optional[faiss.IndexFlatIP] = None

        self._load_from_disk()
        logger.info(
            f"向量存储就绪: embedding={embedding_model}, dim={embedding_dim}, "
            f"llm_rerank={'开' if enable_llm_rerank else '关'}, 当前文档数={len(self.metadata)}"
        )

    # ─── 持久化 ─────────────────────────────────

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
            # 老数据可能带有 sparse_vector 字段,直接忽略不再使用
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
            # 用余弦相似度等价于先归一化再点积
            faiss.normalize_L2(arr)
            self.dense_vectors = arr.tolist()
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None

    # ─── 文档管理 ───────────────────────────────

    def _embed(self, texts: List[str]) -> np.ndarray:
        # 不主动传 dimensions:BGE-M3/智谱/百炼 等不支持该参数,会被拒绝;
        # OpenAI text-embedding-3 系列即便不传也会输出该模型的原生维度。
        vectors = self.client.embed(
            texts,
            model=self.embedding_model,
        )
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

    # ─── 检索 ───────────────────────────────────

    def hybrid_search_with_rerank(
        self,
        query: str,
        top_k: int = None,
        source_filter: Optional[str] = None,
        partition: Optional[str] = None,
    ) -> List[Document]:
        """对外保留旧名以避免上层改动。内部为纯稠密检索 + 可选 LLM rerank。"""
        return self.search(query, top_k=top_k, source_filter=source_filter, partition=partition)

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

        # 1) FAISS 粗筛
        search_n = min(top_k * 4, len(self.metadata))
        scores, ids = self.dense_index.search(q_vec, search_n)
        candidates = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

        # 2) 应用过滤
        def keep(meta):
            if partition and meta.get("partition", "") != partition:
                return False
            if source_filter and meta.get("source", "") != source_filter:
                return False
            return True

        filtered = [(i, s) for i, s in candidates if keep(self.metadata[i])]
        filtered = filtered[: top_k * 2] or candidates[: top_k]
        if not filtered:
            return []

        # 3) 构造 child docs
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
                },
            ))

        # 4) 取唯一 parent
        unique_parents = self._get_unique_parent_docs(child_docs)
        if len(unique_parents) <= 1:
            return unique_parents

        # 5) 可选的 LLM rerank
        if self.enable_llm_rerank:
            ranked = self._llm_rerank(query, unique_parents)
            return ranked[: conf.candidate_top_k]
        return unique_parents[: conf.candidate_top_k]

    def _llm_rerank(self, query: str, docs: List[Document]) -> List[Document]:
        n = len(docs)
        snippets = "\n\n".join(f"[{i+1}] {d.page_content[:500]}" for i, d in enumerate(docs))
        messages = self.context_builder.build_messages(
            "rerank", query=query, n=n, docs=snippets
        )
        try:
            resp = self.chat_client.chat(
                messages=messages,
                model=self.chat_model,
                stream=False,
                temperature=0.0,
                max_tokens=max(64, n * 4),
            )
        except Exception as e:
            logger.warning(f"LLM rerank 调用失败,回退原顺序: {e}")
            return docs

        nums = [int(x) for x in re.findall(r"\d+", resp or "")]
        if len(nums) < n:
            logger.warning(f"LLM rerank 评分数量不足,回退原顺序。原始输出: {resp!r}")
            return docs
        scored = list(zip(nums[:n], docs))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored]

    # ─── 内部辅助 ───────────────────────────────

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
                    },
                ))
        return unique


if __name__ == "__main__":
    embed_client = OpenAIClient(
        api_key=conf.embedding_api_key,
        base_url=conf.embedding_base_url,
        timeout=conf.openai_timeout,
        max_retries=conf.openai_max_retries,
    )
    vs = VectorStore(
        client=embed_client,
        embedding_model=conf.openai_embedding_model,
        embedding_dim=conf.openai_embedding_dim,
        enable_llm_rerank=conf.enable_llm_rerank,
    )
    print("向量存储初始化完成,当前文档数:", len(vs.metadata))
