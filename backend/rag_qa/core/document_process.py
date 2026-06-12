from base.config import conf
from base.logger import logger,batch_configure_loggers
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders.markdown import UnstructuredMarkdownLoader
from langchain_text_splitters import MarkdownTextSplitter
import os
from datetime import datetime
'''自定义文档处理模块，包含文本切分器和文档加载器'''
from ..text_spliter import ChineseRecursiveTextSplitter, AliTextSplitter
from ..document_loaders import OCRPDFLoader, OCRDOCLoader, OCRIMGLoader, OCRPPTLoader

# 将 第三方包 的日志级别设置为 WARNING，减少日志输出
batch_configure_loggers()

document_loaders = {
    # PDF文件
    'pdf': OCRPDFLoader,
    # Word文档
    'doc': OCRDOCLoader,
    'docx': OCRDOCLoader,
    # PowerPoint文档
    'ppt': OCRPPTLoader,
    'pptx': OCRPPTLoader,
    # 文本文件
    'txt': TextLoader,
    # Markdown文件
    'md': UnstructuredMarkdownLoader,
    # 图像文件
    'png': OCRIMGLoader,
    'jpg': OCRIMGLoader,
    'jpeg': OCRIMGLoader,
}

# 定义函数，从单个文件加载文档
def load_sigle_document(root,file_name):
    # 支持的扩展名
    supported_extensions = document_loaders.keys()
    # 获取文件扩展名
    ext = file_name.split('.')[-1].lower()
    # 如果扩展名受支持，则加载文档
    if ext in supported_extensions:
        file_path = os.path.join(root, file_name)
        try:
            # 获取对应的加载器类
            loader_class = document_loaders[ext]
            # 创建加载器实例
            loader = loader_class(file_path)
            # 加载文档内容
            doc = loader.load()
            # 为文档添加元数据（文件名）
            for d in doc:
                d.metadata['file_path'] = file_path
                d.metadata['source'] = file_name
                d.metadata['extension'] = ext
                d.metadata['timestamp'] = datetime.now().isoformat()
            # 记录成功加载文档的日志
            logger.info(f"成功加载文档: {file_path}")
            # 将加载的文档添加到文档列表中
            return doc
        except Exception as e:
            logger.error(f"加载文档失败: {file_path}, 错误: {e}")
    else:
        logger.warning(f"不支持的文件类型: {file_name}")

# 定义函数，从指定文件夹加载多类型文档
def load_documents_from_dir(directory):
    # 初始化文档列表
    documents = []
    # 递归遍历目录中的所有文件
    for root,_,files in os.walk(directory):
        '''
        root: 当前目录路径
        _: 当前目录下的子目录列表（不使用）
        files: 当前目录下的文件列表
        '''
        # 遍历文件列表
        for file in files:
            # 加载单个文档
            doc = load_sigle_document(root,file)
            if doc:
                documents.extend(doc)
    return documents

# 定义函数，从单个文件路径加载文档
def load_documents_from_file(file_path):
    # 如果扩展名受支持，则加载文档
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    return doc if doc else []

def process_documents_from_dir(
        directory,  # 文档目录或文件路径
        parent_chunk_size=conf.parent_chunk_size,  # 父级切分块大小
        child_chunk_size=conf.child_chunk_size,  # 子级切分块大小
        chunk_overlap=conf.chunk_overlap    # 切分块重叠大小
    ):
    if os.path.isdir(directory):
        # 从目录加载文档
        documents = load_documents_from_dir(directory)
    elif os.path.isfile(directory):
        # 从单个文件加载文档
        documents = load_documents_from_file(directory)
    else:
        logger.error(f"无效的路径: {directory}")
        return []
    # 记录加载文档数量的日志
    logger.info(f"加载的文档数量: {len(documents)}")
    # 初始化文本切分器
    parent_splitter = ChineseRecursiveTextSplitter(chunk_size=parent_chunk_size, chunk_overlap=chunk_overlap)
    child_splitter = ChineseRecursiveTextSplitter(chunk_size=child_chunk_size, chunk_overlap=chunk_overlap)
    # 初始化Markdown文本切分器
    parent_markdown_splitter = MarkdownTextSplitter(chunk_size=parent_chunk_size, chunk_overlap=chunk_overlap)
    child_markdown_splitter = MarkdownTextSplitter(chunk_size=child_chunk_size, chunk_overlap=chunk_overlap)
    # 初始化空列表，用于存储切分后的子块
    child_chunk_list = []
    # 遍历每个原始文档，带上文档索引
    for i, doc in enumerate(documents):
        # 获取文档名称
        doc_name = doc.metadata.get('source', f'文档_{i}')
        # 获取文档扩展名
        doc_extension = doc.metadata.get('extension', f'扩展名_{i}')
        # 根据扩展名选择切分器
        if doc_extension in ['md']:
            parent_splitter_use = parent_markdown_splitter
            child_splitter_use = child_markdown_splitter
        else:
            parent_splitter_use = parent_splitter
            child_splitter_use = child_splitter
        # 记录使用的切分器的日志
        logger.info(f"使用切分器: {parent_splitter_use.__class__.__name__} 和 {child_splitter_use.__class__.__name__} 处理文档: {doc_name}")
        # 使用父级切分器对文档进行初步切分
        parent_chunks = parent_splitter_use.split_documents([doc])
        # 记录父级切分块数量的日志
        logger.info(f"文档: {doc_name} 的父级切分块数量: {len(parent_chunks)}")
        # 定义子级切分块数量的计数器
        child_chunk_count = 0
        # 遍历每个父级切分块，带上父级切分块索引
        for j, parent_chunk in enumerate(parent_chunks):
            # 为父块生成唯一ID
            parent_chunk_id = f'doc_{i}_parent_{j}'
            # 使用子级切分器对父级切分块进行进一步切分
            child_chunks = child_splitter_use.split_documents([parent_chunk])
            # 遍历每个子级切分块，带上子级切分块索引
            for k, child_chunk in enumerate(child_chunks):
                # 为子块生成唯一ID
                child_chunk_id = f'{parent_chunk_id}_child_{k}'
                # 将子块的元数据更新为包含父块ID和子块ID
                child_chunk.metadata['parent_chunk_id'] = parent_chunk_id
                child_chunk.metadata['parent_content'] = parent_chunk.page_content
                child_chunk.metadata['child_chunk_id'] = child_chunk_id
                # 将切分后的子块添加到列表中
                child_chunk_list.append(child_chunk)
                child_chunk_count += 1
        # 记录子级切分块数量的日志
        logger.info(f"文档: {doc_name} 的子级切分块数量: {child_chunk_count}")
    # 记录切分完成的日志
    logger.info(f"文档切分完成，生成的子级切分块总数量: {len(child_chunk_list)}")
    return child_chunk_list

if __name__ == "__main__":
    # 测试文档加载和切分功能
    test_directory = "data"  # 替换为你的测试文档目录
    docs = load_documents_from_dir(test_directory)
    print(f"加载的文档数量: {len(docs)}")
    for i, doc in enumerate(docs):  # 打印前3条文档内容
        print(f"文档 {i+1} 内容: {doc.page_content[:100]}")  # 打印前100个字符
    child_chunks = process_documents_from_dir(test_directory)
    print(f"生成的子级切分块数量: {len(child_chunks)}")