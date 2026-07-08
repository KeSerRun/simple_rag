# ===== 文件头：模块文档字符串 =====
# 这个字符串是模块的说明文档，描述了本文件的主要功能：向量存储和文档处理管线
"""向量存储 + 文档处理管线。"""

# ===== 导入：让 Python 在未来版本中支持类型注解中的字符串引用 =====
# from __future__ import annotations 可以让类型注解延迟求值，避免循环引用问题
from __future__ import annotations

# ===== 导入：标准库模块 =====
# 导入 hashlib 库，用于计算 MD5 哈希值（后面用来生成文档的唯一 ID）
import hashlib
# 导入 json 库，用于把 Python 对象序列化成 JSON 字符串（保存到磁盘文件）
import json
# 导入 os 库，用于操作文件和路径（创建目录、检查文件是否存在等）
import os
# 导入 threading 库，用于多线程编程（这里用 RLock 实现线程安全的读写锁）
import threading
# 从 dataclasses 模块导入 dataclass 装饰器和 field 函数（用于定义轻量数据类）
from dataclasses import dataclass, field
# 从 datetime 模块导入 datetime 类（用于获取当前时间戳）
from datetime import datetime
# 从 typing 模块导入 Iterator、List、Optional 三个类型提示工具
# Iterator 表示迭代器类型，List 表示列表类型，Optional 表示可选类型（可以是 None）
from typing import Iterator, List, Optional

# ===== 导入：第三方库 =====
# 导入 faiss 库，这是 Meta 开源的向量相似性搜索库（用于高效检索相似向量）
import faiss
# 导入 numpy 库，这是 Python 最流行的数值计算库（用于处理向量和矩阵）
import numpy as np

# ===== 导入：项目内部模块 =====
# 从 base.config 模块导入 conf 对象（这是全局配置对象，包含各种设置项）
from base.config import conf
# 从 base.logger 模块导入 logger 对象（这是全局日志记录器）
from base.logger import logger

# 从当前包（rag）的 pdf_parser 模块导入 MinerUPDFLoader 类（用于解析 PDF 文件）
from .pdf_parser import MinerUPDFLoader
# 从当前包（rag）的 llm_client 模块导入 OpenAIClient 类（用于调用 OpenAI 的 API）
from .llm_client import OpenAIClient


# ===== 类定义：VectorStore（向量存储） =====
# 这是整个文件最核心的类，负责管理文档的向量化存储和相似性检索
class VectorStore:
    # 类的文档字符串，说明这个类是基于 OpenAI Embedding + FAISS 的本地向量存储
    """基于 OpenAI Embedding + FAISS 的本地向量存储"""

    # ===== 方法：__init__（构造函数） =====
    # 当创建 VectorStore 实例时自动调用，负责初始化所有属性和状态
    def __init__(
        self,
        # client 参数：OpenAIClient 类型的实例，用来调用 OpenAI 的 API（包括 Embedding）
        client: OpenAIClient,
        # embedding_model 参数：字符串类型，指定使用的嵌入模型名称（如 text-embedding-ada-002）
        embedding_model: str,
        # embedding_dim 参数：整数类型，指定嵌入向量的维度（如 1536）
        embedding_dim: int,
        # index_dir 参数：可选的字符串类型，指定向量索引在磁盘上的存储目录路径
        index_dir: Optional[str] = None,
    ):
        # 将传入的 client 参数保存到实例属性 self.client 中（供后续方法使用）
        self.client = client
        # 将传入的 embedding_model 参数保存到实例属性中（记录当前使用的嵌入模型名称）
        self.embedding_model = embedding_model
        # 将传入的 embedding_dim 参数保存到 self.dimension 属性中（记录向量维度）
        self.dimension = embedding_dim
        # 将 index_dir 赋值给 self.index_dir，如果调用者没传则使用配置文件中设置的向量存储目录
        self.index_dir = index_dir or conf.vector_store_dir
        # 调用 os.makedirs 创建索引目录，exist_ok=True 表示如果目录已存在也不会报错
        os.makedirs(self.index_dir, exist_ok=True)

        # 构建稠密向量文件的完整路径：在索引目录下命名为 "dense_vectors.npy"
        self._dense_file = os.path.join(self.index_dir, "dense_vectors.npy")
        # 构建元数据文件的完整路径：在索引目录下命名为 "metadata.json"
        self._meta_file = os.path.join(self.index_dir, "metadata.json")
        # 创建一个可重入锁（RLock），用于多线程环境下保护共享资源的并发访问
        self._lock = threading.RLock()

        # 初始化稠密向量列表，类型是 List[List[float]]，用于在内存中保存所有文档的向量
        self.dense_vectors: List[List[float]] = []
        # 初始化元数据列表，类型是 List[dict]，用于在内存中保存所有文档的元信息
        self.metadata: List[dict] = []
        # 初始化 FAISS 索引对象，类型是 Optional[faiss.IndexFlatIP]，IP 表示内积（余弦相似度）
        self.dense_index: Optional[faiss.IndexFlatIP] = None

        # 调用 _load_from_disk 方法，尝试从磁盘加载之前保存的向量和元数据
        self._load_from_disk()
        # 使用 logger.info 输出一条日志，告知用户向量存储已经初始化完成
        logger.debug(
            f"向量存储就绪: embedding={embedding_model}, dim={embedding_dim}, "
            f"当前文档数={len(self.metadata)}"
        )

    # ===== 方法：_load_from_disk（从磁盘加载向量数据） =====
    # 私有方法（以单下划线开头），从磁盘文件中读取之前保存的向量和元数据
    def _load_from_disk(self):
        # 检查稠密向量文件和元数据文件是否同时存在，如果有一个不存在就说明没有历史数据
        if not (os.path.exists(self._dense_file) and os.path.exists(self._meta_file)):
            # 输出日志：没有发现已有的向量存储文件，将创建新的空存储
            logger.debug("未发现已有向量存储,将创建新的")
            # 直接返回，不执行后续的加载逻辑
            return
        # 使用 try 块捕获可能出现的异常（如文件损坏、格式不对等）
        try:
            # 使用 numpy 的 load 函数从磁盘加载 .npy 文件，返回一个 NumPy 数组
            arr = np.load(self._dense_file)
            # 如果数组不为空且数组的列数（向量维度）与配置的维度不一致
            if arr.size and arr.shape[1] != self.dimension:
                # 输出警告日志：已有索引的维度和配置的维度不匹配
                logger.warning(
                    f"已有索引维度 {arr.shape[1]} 与配置维度 {self.dimension} 不一致,丢弃旧索引,需要重新嵌入"
                )
                # 清空内存中的稠密向量列表（准备重新构建）
                self.dense_vectors = []
                # 清空内存中的元数据列表
                self.metadata = []
                # 将 FAISS 索引设为 None（旧索引已失效）
                self.dense_index = None
                # 返回，不继续执行后续代码
                return
            # 将 NumPy 数组转换为 Python 的普通列表，保存到 self.dense_vectors
            self.dense_vectors = arr.tolist()
            # 以只读模式打开元数据 JSON 文件，指定编码为 utf-8
            with open(self._meta_file, "r", encoding="utf-8") as f:
                # 使用 json.load 将文件内容解析为 Python 列表（每个元素是一个 dict）
                self.metadata = json.load(f)
            # 遍历每一条元数据记录
            for m in self.metadata:
                # 移除元数据中的 "sparse_vector" 键（稀疏向量字段，本版本不再使用）
                m.pop("sparse_vector", None)
            # 调用 _rebuild_index 方法，用加载的向量重新构建 FAISS 索引
            self._rebuild_index()
            # 输出日志：成功从磁盘加载了向量存储，并显示记录条数
            logger.debug(f"从磁盘加载向量存储: {len(self.dense_vectors)} 条记录")
        # 如果在 try 块中发生了任何异常，使用 except 捕获
        except Exception as e:
            # 输出警告日志：加载失败并显示错误信息，后续将重新创建空存储
            logger.warning(f"加载向量存储失败,将重新创建: {e}")
            # 清空稠密向量列表
            self.dense_vectors = []
            # 清空元数据列表
            self.metadata = []
            # 将 FAISS 索引设为 None
            self.dense_index = None

    # ===== 方法：_save_to_disk（将向量数据保存到磁盘） =====
    # 私有方法，将当前内存中的向量和元数据持久化到磁盘文件中
    def _save_to_disk(self):
        # 使用 with 语句获取可重入锁，确保多线程环境下写入操作的原子性
        with self._lock:
            # 如果稠密向量列表不为空（有数据需要保存）
            if self.dense_vectors:
                # 使用 numpy 的 save 函数将向量列表转为 float32 类型的数组并保存到 .npy 文件
                np.save(self._dense_file, np.array(self.dense_vectors, dtype=np.float32))
            # 如果稠密向量列表为空，但磁盘上的 .npy 文件还存在
            elif os.path.exists(self._dense_file):
                # 删除磁盘上的 .npy 文件（因为已经没有向量数据了）
                os.remove(self._dense_file)
            # 以写入模式打开元数据 JSON 文件，指定编码为 utf-8
            with open(self._meta_file, "w", encoding="utf-8") as f:
                # 将元数据列表序列化为 JSON 字符串写入文件，ensure_ascii=False 支持中文，indent=2 美化格式
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    # ===== 方法：_rebuild_index（重建 FAISS 索引） =====
    # 私有方法，根据当前内存中的稠密向量重新构建 FAISS 索引
    def _rebuild_index(self):
        # 如果稠密向量列表不为空（有向量数据）
        if self.dense_vectors:
            # 将 Python 列表转为 numpy 的 float32 类型数组（FAISS 需要这种格式）
            arr = np.array(self.dense_vectors, dtype=np.float32)
            # 对数组进行 L2 归一化（使每个向量的 L2 范数为 1，这样内积就等价于余弦相似度）
            faiss.normalize_L2(arr)
            # 将归一化后的数组转回 Python 列表，更新 self.dense_vectors
            self.dense_vectors = arr.tolist()
            # 创建一个新的 FAISS 内积索引（IndexFlatIP），传入向量的维度
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            # 将归一化后的向量数组添加到 FAISS 索引中（建立索引供后续检索使用）
            self.dense_index.add(arr)
        # 如果稠密向量列表为空（没有任何向量数据）
        else:
            # 将 FAISS 索引设置为 None（表示当前没有可用的索引）
            self.dense_index = None

    # ===== 方法：_embed（批量生成文本嵌入向量） =====
    # 私有方法，调用 OpenAI 的 Embedding API 将文本列表转换为向量矩阵
    def _embed(self, texts: List[str]) -> np.ndarray:
        # 使用 try 块捕获调用 API 过程中可能出现的异常
        try:
            # 调用 self.client.embed 方法，传入文本列表和模型名称，获取嵌入向量
            vectors = self.client.embed(texts, model=self.embedding_model)
            # 将返回的向量列表转为 numpy 的 float32 类型数组
            arr = np.array(vectors, dtype=np.float32)
            # 如果数组的大小为 0（没有生成任何向量），直接返回空数组
            if arr.size == 0:
                return arr
            # 对向量数组进行 L2 归一化，使每个向量长度为 1（方便用内积算余弦相似度）
            faiss.normalize_L2(arr)
            # 返回归一化后的向量数组
            return arr
        # 捕获任何类型的异常
        except Exception as e:
            # 记录错误日志：嵌入失败以及具体的错误信息
            logger.error(f"嵌入失败: {e}")
            # 重新抛出异常，由调用方（add_documents 方法）负责处理
            raise  # 调用方 add_documents 会捕获并处理

    # ===== 方法：add_documents（添加文档到向量存储） =====
    # 接收 Document 列表，为每个文档生成嵌入向量并存储到向量库中
    def add_documents(self, documents: List[Document], partition: Optional[str] = None):
        # ===== 内部函数：_embed_text（构造用于嵌入的文本字符串） =====
        # 这个嵌套函数负责将 Document 对象拼成一个完整的文本串，供 Embedding API 使用
        def _embed_text(doc):
            # 构建一个列表，包含三部分内容：来源、正文文本、脚注
            parts = [
                # 从文档的 metadata 中获取 "source" 字段（来源文件名），如果没有则为空字符串
                doc.metadata.get("source", ""),
                # 文档的正文内容（page_content 是 Document 的核心字段，保存了文本块内容）
                doc.page_content,
                # 从文档的 metadata 中获取 "footnote" 字段（脚注），如果没有则为空字符串
                doc.metadata.get("footnote", ""),
            ]
            # 用换行符 \n 连接 parts 列表中的非空字符串，返回拼接结果
            return "\n".join(p for p in parts if p)

        # 对 documents 列表中的每个文档调用 _embed_text，生成待嵌入的文本列表
        embed_texts = [_embed_text(doc) for doc in documents]
        # 如果 embed_texts 为空列表（没有任何文档需要处理），直接返回
        if not embed_texts:
            return
        # 输出日志：开始嵌入操作，显示文档数量和使用的嵌入模型
        logger.info(f"开始嵌入 {len(embed_texts)} 条文档分块,模型={self.embedding_model}")
        # 使用 try 块捕获嵌入过程中可能出现的异常
        try:
            # 调用 self._embed 方法，传入文本列表，获取嵌入向量数组
            embeddings = self._embed(embed_texts)
        # 如果嵌入过程中抛出了异常
        except Exception as e:
            # 记录错误日志：嵌入失败，跳过入库，并显示错误信息
            logger.error(f"文档嵌入失败,跳过入库: {e}")
            # 直接返回，不执行后续的存储逻辑
            return
        # 输出日志：嵌入完成，开始将结果写入本地向量库
        logger.info(f"嵌入完成,开始写入本地向量库")
        # 使用 with 获取可重入锁，保证写入过程的线程安全
        with self._lock:
            # 使用 enumerate 同时遍历文档列表的索引 i 和文档对象 doc
            for i, doc in enumerate(documents):
                # 使用 MD5 算法对文档正文内容计算哈希值，作为文档的唯一标识 ID
                text_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
                # 将第 i 个嵌入向量添加到 self.dense_vectors 列表中（转为普通列表格式）
                self.dense_vectors.append(embeddings[i].tolist())
                # 向 self.metadata 列表中添加一条新的元数据字典
                self.metadata.append({
                    # "id": 使用上面计算的 MD5 哈希值作为文档的唯一标识
                    "id": text_hash,
                    # "text": 文档的正文内容
                    "text": doc.page_content,
                    # "source": 文档来源（文件名），从 metadata 中获取，默认空字符串
                    "source": doc.metadata.get("source", ""),
                    # "timestamp": 时间戳，从 metadata 中获取，如果没有则使用当前时间
                    "timestamp": doc.metadata.get("timestamp", datetime.now().isoformat()),
                    # "partition": 分区标识，如果调用者传了就用传入的值，否则为空字符串
                    "partition": partition or "",
                    # "chunk_type": 分块类型（如 text、table、chart 等），从 metadata 获取
                    "chunk_type": doc.metadata.get("chunk_type", ""),
                    # "page": 页码，从 metadata 获取（可能为 None）
                    "page": doc.metadata.get("page"),
                    # "img_path": 图片路径，如果块类型不是 "table" 才保留（表格块不存图片路径）
                    "img_path": doc.metadata.get("img_path") if doc.metadata.get("chunk_type") != "table" else "",
                    # "footnote": 脚注内容，从 metadata 获取，默认空字符串
                    "footnote": doc.metadata.get("footnote", ""),
                    # "table_body": 表格正文（如果是表格块），从 metadata 获取，默认空字符串
                    "table_body": doc.metadata.get("table_body", ""),
                })
            # 所有文档添加完毕后，调用 _rebuild_index 重新构建 FAISS 索引
            self._rebuild_index()
            # 调用 _save_to_disk 将更新后的向量和元数据保存到磁盘
            self._save_to_disk()
        # 输出日志：成功插入文档到本地向量存储，显示插入的文档数量
        logger.info(f"成功插入 {len(documents)} 条文档到本地向量存储")

    # ===== 方法：get_documents_by_partition（按分区获取文档来源列表） =====
    # 根据分区标识查询该分区下有哪些文档来源（去重后的文件名列表）
    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        # 如果传入了分区标识（不为 None）
        if partition:
            # 使用集合推导式，遍历 metadata，找出 partition 字段匹配的记录的 source 值，去重后存入集合
            sources = {m["source"] for m in self.metadata if m["partition"] == partition}
        # 如果没有传入分区标识（partition 为 None）
        else:
            # 使用集合推导式，遍历所有 metadata，提取所有 source 值，去重后存入集合
            sources = {m["source"] for m in self.metadata}
        # 将集合转为列表返回（去重后的文档来源列表）
        return list(sources)

    # ===== 方法：delete_documents_by_partition（按分区删除文档） =====
    # 根据分区标识，删除该分区下的所有向量和元数据记录
    def delete_documents_by_partition(self, partition: Optional[str] = None):
        # 使用 with 获取可重入锁，保证线程安全
        with self._lock:
            # 记录删除前的元数据数量，用于后面计算删除了多少条
            before = len(self.metadata)
            # 如果传入了分区标识
            if partition:
                # 使用列表推导式，找出所有不需要删除的记录的索引（partition 不等于指定值的记录）
                keep_indices = [i for i, m in enumerate(self.metadata) if m["partition"] != partition]
            # 如果没有传入分区标识（partition 为 None，表示删除所有）
            else:
                # keep_indices 设为空列表，表示不保留任何记录（全部删除）
                keep_indices = []
            # 调用 _apply_keep_indices 方法，根据 keep_indices 保留指定索引的记录，其余的删除
            self._apply_keep_indices(keep_indices)
            # 计算被删除的记录数 = 之前的数量 - 删除后的数量
            removed = before - len(self.metadata)
        # 输出日志：显示清理了哪个分区、删除了多少条向量片段、库中还剩多少条
        logger.info(f"清理分区 {partition}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

    # ===== 方法：delete_documents_by_sources（按文档来源删除） =====
    # 根据来源文件名列表删除对应的文档，可指定分区范围
    def delete_documents_by_sources(self, sources, partition: Optional[str] = None):
        # 使用 with 获取可重入锁，保证线程安全
        with self._lock:
            # 记录删除前的元数据数量
            before = len(self.metadata)
            # 初始化要保留的索引列表（空列表）
            keep_indices = []
            # 使用 enumerate 遍历 metadata，i 是索引，m 是元数据字典
            for i, m in enumerate(self.metadata):
                # 如果当前记录的 source（来源文件名）在待删除的 sources 列表中
                if m["source"] in sources:
                    # 如果指定了分区且当前记录的分区与指定分区不一致（不在这个分区范围内）
                    if partition and m["partition"] != partition:
                        # 保留这条记录（因为虽然来源匹配，但分区不匹配）
                        keep_indices.append(i)
                # 如果当前记录的 source 不在待删除列表中
                else:
                    # 保留这条记录（不需要删除）
                    keep_indices.append(i)
            # 调用 _apply_keep_indices，根据 keep_indices 执行删除操作
            self._apply_keep_indices(keep_indices)
            # 计算被删除的记录数
            removed = before - len(self.metadata)
        # 输出日志：显示按来源删除了哪些文档、删除了多少条、剩余多少条
        logger.info(f"按来源删除文档 {sources}: 删除了 {removed} 个向量片段, 库中剩余 {len(self.metadata)} 条")

    # ===== 方法：_apply_keep_indices（根据保留索引执行删除） =====
    # 私有方法，接收一个需要保留的索引列表，删除不在列表中的向量和元数据
    def _apply_keep_indices(self, keep_indices):
        # 将 keep_indices 列表转为集合（set），提高成员检查的效率（in 操作更快）
        keep_set = set(keep_indices)
        # 使用列表推导式：遍历 self.dense_vectors，只保留索引在 keep_set 中的向量
        self.dense_vectors = [v for i, v in enumerate(self.dense_vectors) if i in keep_set]
        # 使用列表推导式：遍历 self.metadata，只保留索引在 keep_set 中的元数据
        self.metadata = [m for i, m in enumerate(self.metadata) if i in keep_set]
        # 调用 _rebuild_index 方法，用保留的向量重新构建 FAISS 索引
        self._rebuild_index()
        # 调用 _save_to_disk 方法，将更新后的数据保存到磁盘
        self._save_to_disk()

    # ===== 方法：store_documents_from_dir（从目录加载并存储文档） =====
    # 接收一个目录路径，加载该目录下的所有文档，处理后存入向量存储
    def store_documents_from_dir(self, directory, partition: Optional[str] = None):
        # 如果没有传入分区标识
        if not partition:
            # 输出警告日志：未提供分区，文档将存储到默认分区
            logger.warning("未提供 partition,将存储至默认分区")
        # 调用 process_documents_from_dir 函数，从指定目录加载并处理文档
        documents = process_documents_from_dir(directory)
        # 如果处理后的文档列表为空（没有解析到任何文档）
        if not documents:
            # 抛出运行时异常，提示用户指定目录下没有解析到文档，并建议检查 MinerU 是否可用
            raise RuntimeError(f"未从 {directory} 解析到任何文档（请检查 MinerU 是否可用）")
        # 调用 self.add_documents 方法，将文档列表添加到向量存储中，可指定分区
        self.add_documents(documents, partition=partition)

    # ===== 方法：search（执行向量相似性搜索） =====
    # 接收查询字符串，在向量库中检索最相似的文档，返回 Document 列表
    def search(
        self,
        # query 参数：用户的查询文本（字符串类型）
        query: str,
        # top_k 参数：可选，指定返回的最相似文档数量，如果是 None 则使用配置的默认值
        top_k: int = None,
        # source_filter 参数：可选字符串，按来源文件过滤检索结果
        source_filter: Optional[str] = None,
        # partition 参数：可选字符串，按分区过滤检索结果
        partition: Optional[str] = None,
    ) -> List[Document]:
        # 如果 self.dense_index 为空（没有建立索引）或 self.metadata 为空（没有数据）
        if not self.dense_index or not self.metadata:
            # 输出警告日志：向量存储为空，无法执行检索
            logger.warning("向量存储为空,无法执行检索")
            # 返回空列表
            return []
        # 如果 top_k 为 None，则使用配置文件中的 retrieval_top_k 默认值
        top_k = top_k or conf.retrieval_top_k
        # 调用 self._embed 方法对查询文本生成嵌入向量，传入列表包装的 query，返回 numpy 数组
        q_vec = self._embed([query])
        # 如果生成的查询向量数组为空（嵌入失败或无结果）
        if q_vec.size == 0:
            # 返回空列表
            return []
        # 计算召回候选数量：top_k 的 4 倍，但不能超过总元数据条数
        search_n = min(top_k * 4, len(self.metadata))
        # 使用 FAISS 索引进行搜索，返回相似度分数 scores 和对应索引 ids
        scores, ids = self.dense_index.search(q_vec, search_n)

        # ===== 构建候选列表 =====
        # 使用列表推导式构建 (索引, 分数) 元组列表：只保留索引不为 -1 的有效结果
        candidates = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

        # ===== 内部函数：keep（判断是否保留某条记录） =====
        # 根据分区和来源过滤条件，判断一条元数据记录是否符合要求
        def keep(meta):
            # 如果指定了分区，且当前记录的 partition 与指定分区不一致
            if partition and meta.get("partition", "") != partition:
                # 返回 False（不保留）
                return False
            # 如果指定了来源过滤，且当前记录的 source 与指定来源不一致
            if source_filter and meta.get("source", "") != source_filter:
                # 返回 False（不保留）
                return False
            # 所有过滤条件都通过了，返回 True（保留）
            return True

        # ===== 过滤候选结果 =====
        # 使用列表推导式，只保留经过 keep 函数过滤后的候选结果
        filtered = [(i, s) for i, s in candidates if keep(self.metadata[i])]
        # 只保留前 top_k * 2 个过滤后的结果（给后续去重留出余量）
        filtered = filtered[: top_k * 2]
        # 如果过滤后没有结果了
        if not filtered:
            # 返回空列表
            return []
        # 初始化一个空列表，用于存放最终要返回的 Document 对象
        child_docs: List[Document] = []
        # 遍历 filtered 中前 top_k 个结果，idx 是 metadata 中的索引，_ 是分数（这里用不到）
        for idx, _ in filtered[:top_k]:
            # 从 self.metadata 中获取对应索引的元数据字典
            m = self.metadata[idx]
            # 创建一个新的 Document 对象，填充正文和元数据，加入 child_docs 列表
            child_docs.append(Document(
                # page_content：从元数据中获取 "text" 字段，默认空字符串
                page_content=m.get("text", ""),
                # metadata：构建一个新的元数据字典
                metadata={
                    # "id": 文档唯一标识
                    "id": m.get("id", ""),
                    # "source": 来源文件名
                    "source": m.get("source", ""),
                    # "timestamp": 时间戳
                    "timestamp": m.get("timestamp", ""),
                    # "chunk_type": 分块类型
                    "chunk_type": m.get("chunk_type", ""),
                    # "section_path": 章节路径（列表类型），用于定位文档在原文中的位置
                    "section_path": m.get("section_path", []),
                    # "page": 页码
                    "page": m.get("page"),
                    # "caption": 标题/说明文字
                    "caption": m.get("caption", ""),
                    # "footnote": 脚注
                    "footnote": m.get("footnote", ""),
                    # "img_path": 图片路径
                    "img_path": m.get("img_path", ""),
                },
            ))

        # ===== 按文本内容去重 =====
        # 创建一个空集合 seen，用于记录已经出现过的文本
        seen = set()
        # 创建一个空列表 unique，用于存放去重后的 Document 对象
        unique = []
        # 遍历 child_docs 中的每个 Document
        for doc in child_docs:
            # 用文档的 page_content（正文）作为去重的键 key
            key = doc.page_content
            # 如果 key 不为空且不在 seen 集合中（还没有出现过）
            if key and key not in seen:
                # 将这个文档加入 unique 列表
                unique.append(doc)
        # 返回前 top_k 个去重后的 Document 对象
        return unique[: top_k]

# ========================================================================
# Document 数据类与处理管线
# ========================================================================
# 下面的文档字符串说明了文档加载和分块的入口逻辑：MinerU 已经预切块的文档不再进行二次切分
"""文档加载与分块入口(MinerU 已预切块则跳过二次切分)"""

# ===== 数据类定义：Document =====
# 使用 @dataclass 装饰器定义一个轻量级的文档数据类（自动生成 __init__、__repr__ 等方法）
@dataclass
class Document:
    # 类的文档字符串：说明这是一个轻量文档容器，替代 langchain_core.documents.Document
    """轻量文档容器,替代 langchain_core.documents.Document"""
    # page_content 字段：字符串类型，存储文档的正文文本内容
    page_content: str
    # metadata 字段：字典类型，存储文档的元数据（来源、时间戳等），默认是空字典
    # field(default_factory=dict) 表示每次创建实例时都会生成一个新的空字典，避免共享引用
    metadata: dict = field(default_factory=dict)


# ===== 类定义：_BaseLoader（基础文档加载器） =====
# 这是一个抽象的基类，定义了文档加载器的基本接口
class _BaseLoader:
    # 类的文档字符串：说明这是一个轻量级的 BaseLoader
    """轻量 BaseLoader。"""
    # ===== 方法：lazy_load（惰性加载） =====
    # 这是一个抽象方法，子类需要重写实现。使用 Iterator 逐文档加载，节省内存
    def lazy_load(self) -> Iterator[Document]:
        # 抛出未实现异常，强制子类重写这个方法
        raise NotImplementedError
    # ===== 方法：load（一次性加载所有） =====
    # 调用 lazy_load 方法并将返回的迭代器转为列表，一次性返回所有 Document
    def load(self) -> List[Document]:
        # 将 self.lazy_load() 返回的迭代器中的所有元素转为列表
        return list(self.lazy_load())


# ===== 全局字典：document_loaders（文件类型到加载器类的映射） =====
# 这个字典将文件扩展名映射到对应的加载器类，方便按文件类型选择加载器
document_loaders = {
    # "pdf" 类型的文件使用 MinerUPDFLoader 类来加载
    "pdf": MinerUPDFLoader,
}


# ===== 函数：load_sigle_document（加载单个文档文件） =====
# 注意：函数名中的 "sigle" 是拼写错误，应为 "single"，但为了保持原始代码不变，此处保留原拼写
# 这个函数接收目录路径和文件名，根据文件扩展名选择合适的加载器并加载文档
def load_sigle_document(root, file_name):
    # 获取 document_loaders 字典的所有键（即所有支持的文件扩展名）
    supported_extensions = document_loaders.keys()
    # 从文件名中提取扩展名：用 "." 分割取最后一部分，转为小写
    ext = file_name.split(".")[-1].lower()
    # 如果该扩展名在支持列表中
    if ext in supported_extensions:
        # 使用 os.path.join 将目录路径和文件名拼接成完整的文件路径
        file_path = os.path.join(root, file_name)
        # 使用 try 块捕获加载过程中可能出现的异常
        try:
            # 从 document_loaders 字典中获取该扩展名对应的加载器类
            loader_class = document_loaders[ext]
            # 创建加载器实例，传入文件路径
            loader = loader_class(file_path)
            # 调用加载器的 load 方法，加载文档，返回 Document 列表
            doc = loader.load()
            # 遍历加载出来的每个 Document 对象
            for d in doc:
                # 在 metadata 中添加 "file_path" 字段：完整的文件路径
                d.metadata["file_path"] = file_path
                # 在 metadata 中添加 "source" 字段：文件名（不含路径）
                d.metadata["source"] = file_name
                # 在 metadata 中添加 "extension" 字段：文件扩展名
                d.metadata["extension"] = ext
                # 在 metadata 中添加 "timestamp" 字段：当前时间的 ISO 格式字符串
                d.metadata["timestamp"] = datetime.now().isoformat()
            # 输出日志：成功加载文档，显示文件路径
            logger.info(f"成功加载文档: {file_path}")
            # 返回加载得到的 Document 列表
            return doc
        # 如果加载过程中出现异常
        except Exception as e:
            # 输出错误日志：显示加载失败的文件路径和错误信息
            logger.error(f"加载文档失败: {file_path}, 错误: {e}")
    # 如果文件扩展名不受支持
    else:
        # 输出警告日志：提示不支持该文件类型
        logger.warning(f"不支持的文件类型: {file_name}")
    # 如果扩展名不支持或加载失败，返回 None
    return None


# ===== 函数：load_documents_from_dir（从目录加载所有文档） =====
# 遍历指定目录及其子目录下的所有文件，逐个加载为 Document 对象
def load_documents_from_dir(directory):
    # 初始化一个空列表，用于存放所有加载的文档
    documents = []
    # 使用 os.walk 遍历目录树：root 是当前目录路径，dirs 是子目录列表，files 是文件列表
    for root, _, files in os.walk(directory):
        # 遍历当前目录下的每个文件
        for file in files:
            # 调用 load_sigle_document 加载单个文件
            doc = load_sigle_document(root, file)
            # 如果成功加载了文档（返回的列表不为 None）
            if doc:
                # 使用 extend 将加载的文档列表扩展到总的 documents 列表中
                documents.extend(doc)
    # 返回所有加载的 Document 列表
    return documents


# ===== 函数：load_documents_from_file（从单个文件加载文档） =====
# 接收一个文件路径，调用 load_sigle_document 加载该文件
def load_documents_from_file(file_path):
    # 调用 load_sigle_document，传入文件所在目录路径和文件名
    # os.path.dirname 获取目录路径，os.path.basename 获取文件名
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    # 如果返回的 doc 不为 None，直接返回 doc，否则返回空列表
    return doc if doc else []


# ===== 函数：process_documents_from_dir（处理目录或文件中的文档） =====
# 核心函数：加载文档并对文档进行过滤处理（去除过短文本和停用词）
def process_documents_from_dir(directory) -> List[Document]:
    # 函数的文档字符串：加载文档，每个 MinerU 原始块直接入库（不做二次切分）
    """加载文档，每个 MinerU 原始块直接入库。"""
    # 如果 directory 是一个目录路径
    if os.path.isdir(directory):
        # 调用 load_documents_from_dir 从目录加载所有文档
        documents = load_documents_from_dir(directory)
    # 如果 directory 是一个文件路径
    elif os.path.isfile(directory):
        # 调用 load_documents_from_file 从单个文件加载文档
        documents = load_documents_from_file(directory)
    # 如果既不是目录也不是文件（无效路径）
    else:
        # 输出错误日志：路径无效
        logger.error(f"无效的路径: {directory}")
        # 返回空列表
        return []
    # 输出日志：显示共加载了多少个文档（块）
    logger.info(f"加载的文档数量: {len(documents)}")

    # ===== 过滤规则第一步：过滤过短的文本块 =====
    # 从配置中获取最小文本块长度（min_chunk_length），太短的文本没有意义
    min_len = conf.min_chunk_length
    # 记录过滤前的文档数量
    before = len(documents)
    # 使用列表推导式过滤文档：保留非 text 类型（如 table、chart）的块，或长度 >= 最小值的 text 块
    documents = [
        d for d in documents
        # 如果 chunk_type 不是 "text"（如表格、图表等）则保留，否则检查文本长度是否达标
        if d.metadata.get("chunk_type") != "text" or len(d.page_content) >= min_len
    ]
    # 如果过滤前后数量发生了变化（有文档被过滤掉了）
    if before != len(documents):
        # 输出日志：显示过滤前后的数量以及最短字符数限制
        logger.debug(f"过滤短文本块: {before} → {len(documents)} (最短 {min_len} 字符)")

    # ===== 过滤规则第二步：过滤包含停用词的文本块 =====
    # 从配置中获取停用词列表（如邮编、电话号码等非内容行的关键词）
    stop_words = conf.stop_words
    # 记录过滤前的文档数量
    before = len(documents)
    # 使用列表推导式过滤文档：
    documents = [
        d for d in documents
        # 如果 chunk_type 不是 "text"（如图表等）则保留
        if d.metadata.get("chunk_type") != "text"
        # 如果是 text 类型，则检查文本中是否不包含任何停用词（不包含才保留）
        or not any(w in d.page_content for w in stop_words)
    ]
    # 如果过滤前后数量发生了变化
    if before != len(documents):
        # 输出日志：显示过滤前后的数量
        logger.debug(f"过滤停用词块: {before} → {len(documents)}")

    # 输出日志：文档处理完成，显示最终剩余的文档块数量
    logger.info(f"文档处理完成, 共 {len(documents)} 个块")
    # 返回处理后的 Document 列表
    return documents
