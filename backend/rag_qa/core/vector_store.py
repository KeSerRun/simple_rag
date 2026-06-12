# 导入 hashlib 模块，用于生成唯一 ID 的哈希值
import hashlib
# 导入日志记录器，用于记录程序运行的日志信息
from base.logger import logger
# 导人配置类，用于获取全局配置参数
from base.config import conf
# 导入 Milvus 向量数据库客户端，用于存储和查询向量数据
from pymilvus import MilvusClient, DataType, AnnSearchRequest, WeightedRanker
# 导入 Document 类，用于创建文档对象
from langchain_community.docstore.document import Document
# 导入 CrossEncoder，用于混合检索的重排序和 NLI 判断
from sentence_transformers import CrossEncoder
# 导入 BGE-M3 向量化函数，Milvus 官方推荐的模型，具有较好的性能和效果
from milvus_model.hybrid import BGEM3EmbeddingFunction
# 导入文档加载器，用于加载不同格式的文档数据
from .document_process import process_documents_from_dir

'''
使用 BGE-M3 模型进行向量化，并使用 Milvus 向量数据库进行存储和查询。
需要安装 BGE-Reranker 和 BGE-M3 模型：
modelscope download --model BAAI/bge-reranker-v2-m3 --local_dir ./model/bge-reranker-v2-m3
modelscope download --model BAAI/bge-m3 --local_dir ./model/bge-m3
'''

class VectorStore:
    # 初始化向量存储，连接 Milvus 数据库并设置集合名称
    def __init__(self,
                 embedding_model: str,
                 reranker_model: str,
                 collection_name: str = conf.milvus_collection,
                 host: str = conf.milvus_host,
                 port: int = conf.milvus_port,
                 database: str = conf.milvus_database):
        # 设置 Milvus 集合名称
        self.collection_name = collection_name
        # 设置 Milvus 主机地址
        self.host = host
        # 设置 Milvus 端口号
        self.port = port
        # 设置 Milvus 数据库名称
        self.database = database
        # 设置日志记录器
        self.logger = logger
        # 初始化 BGE-Reranker 模型，用于生成向量表示
        self.reranker = CrossEncoder(reranker_model,device='cpu') 
        # 记录RAG重排序模型初始化完成日志
        logger.info(f"RAG 重排序模型初始化完成，使用模型：{reranker_model}，使用设备: {self.reranker.device}")
        # 初始化 BGE-M3 词嵌入模型，使用 CPU，不启用 FP16 精度
        self.embedder = BGEM3EmbeddingFunction(embedding_model, device='cpu', use_fp16=False)
        # 记录rag词嵌入模型初始化完成日志
        logger.info(f"RAG 词嵌入模型初始化完成，使用模型：{embedding_model}，使用设备: {self.embedder.device}")
        # 获取稠密向量维度，BGE-M3 模型的默认维度是1024
        self.dimension = self.embedder.dim["dense"]
        # 初始化 Milvus 客户端，连接到 Milvus 数据库
        self.client = MilvusClient(uri=f"http://{self.host}:{self.port}")
        # 如果不存在该数据库，则创建新的数据库
        if not self.database in self.client.list_databases():
            self.client.create_database(self.database)
        # 切换到指定数据库
        self.client.use_database(self.database)
        # 调用方法创建或加载 Milvus 集合
        self._create_or_load_collection()

    # 定义保护方法，用于创建或加载 Milvus 集合，如果集合不存在则创建新的集合
    def _create_or_load_collection(self):
        # 检查 Milvus 中是否存在指定名称的集合
        if not self.collection_name in self.client.list_collections():
            # 创建 schema 定义集合的字段，包括 id、question、answer、metadata 和向量字段
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
            # 添加主键 id 字段，类型为字符串
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=256)
            # 添加文本字段，类型为字符串
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            # 添加稠密向量字段，类型为 FLOAT_VECTOR，维度为 BGE-M3 模型的默认维度
            schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=self.dimension)
            # 添加稀疏向量字段，类型为 SPARSE_FLOAT_VECTOR，这里不指定维度，使用动态字段功能
            schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
            # 添加父级 ID 字段，类型为字符串，用于存储文档的父级 ID
            schema.add_field("parent_id", DataType.VARCHAR, max_length=256)
            # 添加父级文本字段，类型为字符串，用于存储文档的父级文本
            schema.add_field("parent_text", DataType.VARCHAR, max_length=65535)
            # 创建来源字段，类型为字符串，用于存储文档的来源信息
            schema.add_field("source", DataType.VARCHAR, max_length=256)
            # 添加时间戳字段，类型为字符串，用于存储文档的创建时间
            schema.add_field("timestamp", DataType.VARCHAR, max_length=64)
            # 创建索引参数对象
            index_params = self.client.prepare_index_params()
            # 为稠密向量添加索引
            index_params.add_index(
                field_name="dense_vector",
                index_name="dense_index", 
                metric_type="IP",
                index_type="IVF_FLAT", 
                params={"nlist": 128})  # 聚类中心数量，影响搜索效率和精度的平衡
            # 为稀疏向量添加索引
            index_params.add_index(
                field_name="sparse_vector",
                index_name="sparse_index", 
                metric_type="IP",
                index_type="SPARSE_INVERTED_INDEX", 
                params={"drop_ratio_build": 0.2})   # 构建稀疏索引时丢弃低权重特征的比例，减少索引大小和提高搜索效率
            # 创建集合，指定集合名称、schema 和索引参数
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params
            )
            # 记录创建集合成功日志
            self.logger.info(f"成功创建 Milvus 集合: {self.collection_name}")
        else:
            # 记录集合已存在日志
            self.logger.info(f"Milvus 集合已存在: {self.collection_name}")
        # 加载集合到内存，准备接受查询
        self.client.load_collection(self.collection_name)
        # 记录加载集合成功日志
        self.logger.info(f"成功加载 Milvus 集合: {self.collection_name}")

    # 定义方法，向向量存储添加文档
    def add_documents(self, documents, partition:str=None):
        # 提取所有文档的子块内容列表
        texts = [doc.page_content for doc in documents]
        # 使用 BGE-M3 模型生成子块文档的向量表示
        # {"dense": [[0.1, 0.2, ..., 0.1024], ...], 
        # "sparse": <Compressed Sparse Row sparse array of dtype 'float64'...}
        embeddings = self.embedder(texts)
        # 初始化空列表，用于存储插入的数据
        data = []
        # 遍历每个文档，带上索引
        for i, doc in enumerate(documents):
            # 生成文档内容的 MD5 哈希值作为唯一 ID
            text_hash = hashlib.md5(doc.page_content.encode('utf-8')).hexdigest()  # 生成文档内容的 MD5 哈希值作为唯一 ID
            # 初始化稀疏向量字典
            sparse_vector = {}
            # 获取第 i 个文档的稀疏向量数据
            row = embeddings['sparse']._getrow(i)
            # 将稀疏向量数据转换为字典格式，键为特征索引，值为特征权重
            for idx, value in zip(row.indices, row.data):
                sparse_vector[idx] = value
            # 创建数据字典，插入 data
            data.append({
                "id": text_hash,  # 使用文档内容的哈希值作为 ID
                "text": doc.page_content,  # 文档内容
                "dense_vector": embeddings['dense'][i].tolist(),  # 稠密向量转换为列表格式
                "sparse_vector": sparse_vector,  # 稀疏向量字典
                "parent_id": doc.metadata.get("parent_chunk_id", ""),  # 父级 ID，如果没有则为空字符串
                "parent_text": doc.metadata.get("parent_content", ""),  # 父级文本，如果没有则为空字符串
                "source": doc.metadata.get("source", ""),  # 来源信息，如果没有则为空字符串
                "timestamp": doc.metadata.get("timestamp", "")  # 时间戳，如果没有则为空字符串
            })
        # 如果没有该分区，则创建它
        if partition and not self.client.has_partition(self.collection_name, partition):
            self.client.create_partition(self.collection_name, partition)
        # 将数据插入 Milvus 集合
        self.client.upsert(collection_name=self.collection_name, data=data, partition_name=partition)
        # 记录插入数据成功日志
        self.logger.info(f"成功插入 {len(data)} 条文档数据到 Milvus 集合: {self.collection_name}")

    def get_documents_by_partition(self, partition:str=None) -> list:
        # 获取指定分区中的所有文档source名称
        doc_list = self.client.query(
            collection_name=self.collection_name, 
            partition_name=partition,
            output_fields=["source"], 
            filter="id like '%'")
        # 对查询结果进行去重，获取唯一的来源名称列表
        unique_sources = list(set([doc['source'] for doc in doc_list]))
        return unique_sources

    def delete_documents_by_partition(self, partition:str=None):
        try:
            # 删除指定分区中的所有文档数据
            self.client.delete(collection_name=self.collection_name, partition_name=partition, filter="id like '%'")
            # 从内存中卸载分区，释放资源
            self.client.release_partitions(collection_name=self.collection_name, partition_names=[partition])
            # 删除指定分区
            self.client.drop_partition(collection_name=self.collection_name, partition_name=partition)
            # 记录删除数据成功日志
            self.logger.info(f"成功删除分区 {partition} 中的所有文档数据")
        except Exception as e:
            self.logger.error(f"删除分区 {partition} 中的文档数据失败: {e}")
            raise e
    
    def delete_documents_by_sources(self, sources:list, partition:str=None):
        try:
            # 构建过滤表达式，删除指定来源的文档数据
            filter_expr = " or ".join([f"source == '{source}'" for source in sources])
            self.client.delete(collection_name=self.collection_name, partition_name=partition, filter=filter_expr)
            # 记录删除数据成功日志
            self.logger.info(f"成功删除来源 {sources} 中的所有文档数据")
        except Exception as e:
            self.logger.error(f"删除来源 {sources} 中的文档数据失败: {e}")
            raise e

    def hybrid_search_with_rerank(self, query:str, top_k:int=conf.retrieval_top_k, source_filter:str=None, partition:str=None) -> list:
        '''
        执行混合搜索并进行重排序
        query: 用户查询文本
        top_k: 返回的最相关文档数量
        source_filter: 可选的来源过滤器，限制搜索结果仅来自特定来源
        '''
        # 使用BGE-M3模型生成查询的向量表示
        # {"dense": [[0.1, 0.2, ..., 0.1024]], "sparse": <Compressed Sparse Row sparse array of dtype 'float64'...>}
        query_embedding = self.embedder([query])    
        # 获取查询的稠密向量并转换为列表格式
        dense_vector = query_embedding['dense'][0].tolist()  
        # 初始化稀疏向量字典
        sparse_vector = {}
        # 获取查询的稀疏向量数据
        row = query_embedding['sparse']._getrow(0)  
        # 获得查询的稀疏向量数据
        for idx, value in zip(row.indices, row.data):
            # 将稀疏向量数据转换为字典格式，键为特征索引，值为特征权重
            sparse_vector[idx] = value  
        # 初始化过滤条件列表
        filter_expr = f"source == '{source_filter}'" if source_filter else ""
        # 创建稠密向量检索请求对象
        search_request = AnnSearchRequest(
            data = [dense_vector],  # 查询的稠密向量列表
            anns_field = "dense_vector",  # 指定稠密向量字段进行检索
            param = {"metric_type": "IP", "params": {"nprobe": 10}},  # 检索参数，使用内积作为相似度度量，nprobe 控制搜索的聚类中心数量
            limit = top_k,  # 返回的最相关文档数量
            expr = filter_expr  # 可选的过滤表达式，限制搜索结果仅来自特定来源
        )
        # 创建稀疏向量检索请求对象
        sparse_search_request = AnnSearchRequest(
            data=[sparse_vector],  # 查询的稀疏向量列表
            anns_field="sparse_vector",  # 指定稀疏向量字段进行检索
            param={"metric_type": "IP", "params": {"nprobe": 10}},  # 检索参数
            limit=top_k,  # 返回的最相关文档数量
            expr=filter_expr  # 可选的过滤表达式
        )
        # 创建加权重排序器对象，指定稠密向量和稀疏向量的权重
        ranker = WeightedRanker(conf.dense_weight, conf.sparse_weight)
        # 如果提供了 partition，但该分区不存在，则记录警告日志并返回空列表
        if partition:
            if not self.client.has_partition(self.collection_name, partition):
                self.logger.warning(f"分区 {partition} 不存在，无法执行检索")
                return []
        else:
            # 如果未提供 partition, 则无法执行检索，因为无法确定搜索范围，记录警告日志并返回空列表
            self.logger.warning("未提供 partition，将在所有分区中执行检索，可能会导致性能问题")
        # 执行混合检索，获取检索结果
        child_hits = self.client.hybrid_search(
            collection_name=self.collection_name,
            partition_names=[partition] if partition else None,  # 如果提供了 partition，则仅在该分区中搜索
            reqs=[
                 search_request,  # 稠密向量检索请求
                 sparse_search_request  # 稀疏向量检索请求
            ],
            output_fields=["text", "parent_id", "parent_text", "source", "timestamp"],  # 指定返回的字段
            ranker=ranker,  # 加权重排序器
            limit=top_k  # 返回的最相关文档数量
        )[0]
        # 将检索结果转换为 Document 对象列表
        child_docs = [self._doc_from_hit(hit) for hit in child_hits]
        # 从检索结果中获取唯一的父级文档列表，去除重复的父级文档
        unique_parent_docs = self._get_unique_parent_docs(child_docs)
        # 如果只有一个文档，则直接返回该文档的内容
        if len(unique_parent_docs) == 1:
            return unique_parent_docs
        # 如果有多个文档，进行重排序，使用 BGE-Reranker 模型对每个父级文档与查询进行匹配打分
        if unique_parent_docs:
            # 创建列表，存储查询与每个父级文档的文本对
            rerank_inputs = [(query, doc.page_content) for doc in unique_parent_docs]
            # 使用 BGE-Reranker 模型对每个文本对进行打分，得到相关性分数列表
            scores = self.reranker.predict(rerank_inputs)
            # 将父级文档与对应的分数进行绑定，并根据分数进行排序，得到排序后的父级文档列表
            ranked_parent_docs = [doc for _, doc in sorted(zip(scores, unique_parent_docs), key=lambda x: x[0], reverse=True)]
            # 返回排序后的前k个文档，即最相关的文档
            return ranked_parent_docs[:conf.candidate_top_k]
        # 如果没有检索到任何文档，则返回空列表
        return []

    def _doc_from_hit(self, hit):
        '''
        将 Milvus 检索结果转换为 Document 对象
        hit: Milvus 检索结果中的单个命中项
        '''
        return Document(
            page_content=hit.entity.get("text", ""),
            metadata={
                "parent_id": hit.entity.get("parent_id", ""),
                "parent_text": hit.entity.get("parent_text", ""),
                "source": hit.entity.get("source", ""),
                "timestamp": hit.entity.get("timestamp", "")
            }
        )

    def _get_unique_parent_docs(self, docs):
        '''
        从检索结果中获取唯一的父级文档列表，去除重复的父级文档
        docs: 检索结果中的 Document 对象列表
        '''
        # 初始化集合，用于存储已处理的父块内容（去重）
        parent_contents = set()
        # 初始化列表，用于存储唯一的父级文档
        unique_parent_docs = []
        # 遍历每个子块文档
        for doc in docs:
            # 获取父级文本内容，如果没有父级文本，则使用子块文本作为父级文本
            parent_text = doc.metadata.get("parent_text", doc.page_content)  
            # 如果父级文本内容不在集合中，说明是一个新的父级文档
            if parent_text and parent_text not in parent_contents:
                # 将父级文本内容添加到集合中，标记为已处理
                parent_contents.add(parent_text)
                # 创建一个新的 Document 对象，表示父级文档
                parent_doc = Document(
                    page_content=parent_text,
                    metadata={
                        "id": doc.metadata.get("parent_id", ""),
                        "source": doc.metadata.get("source", ""),
                        "timestamp": doc.metadata.get("timestamp", "")
                    }
                )
                # 将唯一的父级文档添加到列表中
                unique_parent_docs.append(parent_doc)
        return unique_parent_docs

    def store_documents_from_dir(self, directory:str, partition:str=None):
        '''
        从指定目录加载文档并存储到向量数据库
        directory: 文档所在的目录路径
        partition: 分区名称，用于将文档存储到指定分区，如果未提供，则存储到默认分区
        '''
        # 如果未提供 partition，则无法存储文档，记录警告日志并返回
        if not partition:
            self.logger.warning("未提供 partition，将存储至默认分区")
        # 使用文档加载器从目录中加载文档，返回 Document 对象列表
        documents = process_documents_from_dir(directory)
        if not documents:
            # 记录没有找到文档的日志
            self.logger.warning(f"在目录 {directory} 中未找到任何文档。")
            return
        # 将加载的文档添加到向量存储中
        self.add_documents(documents, partition=partition)

    def __del__(self):
        try:
            # 关闭 Milvus 客户端连接
            self.client.close()
            # 记录关闭连接日志
            self.logger.info("成功关闭 Milvus 客户端连接")
        except Exception as e:
            # 记录关闭连接失败日志
            self.logger.error(f"关闭 Milvus 客户端连接时发生错误: {e}")

if __name__ == "__main__":
    v = VectorStore()
    result = v.hybrid_search_with_rerank("什么光子晶体表面发射激光器")
    print("检索结果:", result)