# ===== 文件头部文档字符串 =====
# 这是一个多行字符串（docstring），用来描述这个文件是干什么用的
"""检索结果格式化工具函数。

将向量检索返回的 Document 列表格式化为 LLM 易读的文本。
每个块附带元数据标头（来源、章节路径、页码、文档类型、分区标记），
如果是图片/图表块且关联了图片路径，则追加 Markdown 图片引用。
"""

# ===== 导入标准库模块 =====
# 从 Python 标准库的 pathlib 模块导入 Path 类，用于处理文件路径
from pathlib import Path
# 从 typing 模块导入 List 类型注解，用来声明函数参数和返回值是列表类型
from typing import List

# ===== 导入项目内部模块 =====
# 从 base.logger 包中导入 logger 对象，用于在代码中打印日志
from base.logger import logger
# 从 rag.vector_store 模块中导入 Document 类，这是向量检索返回的数据结构
from rag.vector_store import Document

# ===== 全局常量定义 =====
# 系统级数据分区名：系统公开文档放在此分区下，对所有用户可见
# 这是一个字符串常量，用来标记文档属于"系统分区"
SYSTEM_PARTITION = "__system__"


# ===== 核心函数：格式化单个检索块 =====
def _format_chunk(idx: int, chunk: Document) -> str:
    """
    格式化单个检索块为带元数据的文本。

    参数:
        idx:   块序号（从 1 开始）
        chunk: 检索结果 Document 对象，含 page_content（文本）和 metadata（元数据字典）

    返回:
        格式如 "【片段 1 | 来源 | 章节路径 | p.页码】\n文本内容" 的字符串。
        如果是图片/图表块且存在图片路径，还会附加 Markdown 图片引用。
    """
    # 从 chunk 对象中取出 metadata 字典，如果 metadata 为空则设为空字典
    # 这样做是为了避免后面调用 meta.get() 时因为 None 而报错
    meta = chunk.metadata or {}
    # --- 构建元数据标头部分 ---
    # 创建一个空列表，用来存放元数据标头的各个组成部分
    parts = []
    # 从 metadata 中获取 "source" 字段（文档来源/文件名），去掉首尾空格
    # 如果 source 不存在或为空，就得到一个空字符串
    source = (meta.get("source") or "").strip()
    if source:
        # 如果 source 有内容，就把它加粗后添加到 parts 列表中
        # **xxx** 是 Markdown 加粗语法
        parts.append(f"**{source}**")                              # 来源文件名（加粗）
    # 从 metadata 中获取 "section_path" 字段，这是一个列表，表示文档内的章节层级路径
    section_path = meta.get("section_path") or []
    if section_path:
        # 如果章节路径不为空，就把路径中的每一级用 " > " 连接起来，形成一个路径字符串
        # 比如 ["第一章", "第一节"] 就变成 "第一章 > 第一节"
        # 同时过滤掉空的章节名（s if s）
        parts.append(" > ".join(s for s in section_path if s))     # 文档内章节路径
    # 从 metadata 中获取 "page" 字段，表示该块所在的页码
    page = meta.get("page")
    if page is not None:
        # 如果 page 存在（注意：page 可能是数字 0，所以不能用 if page 来判断）
        # 就把页码添加到 parts 中，格式为 "p.3"
        parts.append(f"p.{page}")                                  # 页码
    # 从 metadata 中获取 "chunk_type" 字段，表示块的类型（如 text、image、chart、table 等）
    chunk_type = (meta.get("chunk_type") or "").strip()
    if chunk_type and chunk_type != "text":
        # 如果块类型存在且不是普通的 "text" 类型，就把类型名称添加到 parts 中
        # 这样 LLM 就能知道这个块是图片还是图表
        parts.append(chunk_type)                                   # 块类型（image/chart/table 等）
    # 标注来源分区（系统文档 vs 用户文档），便于 LLM 判断权威性
    # 从 metadata 中获取 "partition" 字段，表示文档所属的分区
    partition = (meta.get("partition") or "").strip()
    if partition == SYSTEM_PARTITION:
        # 如果分区等于系统分区常量，就在标头中添加一个书本图标和"系统文档"字样
        parts.append("📖 系统文档")
    elif partition:
        # 如果分区存在但不是系统分区（说明是用户上传的文档），就添加文档图标和"用户文档"
        parts.append("📄 用户文档")
    # 组装最终的标头字符串
    # 如果 parts 列表不为空，就生成 "【片段 1 | xxx | yyy】" 这种格式
    # 如果 parts 为空，就只生成 "【片段 1】"
    header = f"【片段 {idx} | {' | '.join(parts)}】" if parts else f"【片段 {idx}】"
    # --- 正文部分 ---
    # 获取 chunk 的文本内容，并去掉首尾空白字符
    body = chunk.page_content.strip()
    # 如果是图片/图表块且有图片路径，追加 Markdown 图片链接
    # 从 metadata 中获取 "img_path" 字段，表示图片文件的路径
    img_path = (meta.get("img_path") or "").strip()
    if img_path and chunk_type in ("image", "chart") and source:
        # 如果同时满足三个条件：有图片路径、块类型是 image 或 chart、有来源文件名
        # 就用 Path(source).stem 获取文件名去掉扩展名的部分，作为 URL 中的路径
        stem = Path(source).stem                                    # 去掉扩展名的文件名作为 URL 路径
        # 拼接 Markdown 图片引用，格式为 ![图](/api/documents/image/文件名/图片路径)
        img_md = f"\n\n![图](/api/documents/image/{stem}/{img_path})"
        # 返回标头 + 正文 + 图片引用的完整字符串
        return f"{header}\n{body}{img_md}"
    # 如果没有图片或不是图片类型，就只返回标头 + 正文
    return f"{header}\n{body}"


# ===== 公开函数：格式化所有检索结果为完整上下文 =====
def format_retrieved_chunks(chunks: List[Document]) -> str:
    """
    将一组检索块拼接为完整上下文文本。

    遍历 chunks 列表，为每个块调用 _format_chunk 生成带元数据标头的文本块，
    块之间以两个换行符分隔。空列表返回空字符串。

    参数:
        chunks: 检索结果 Document 列表

    返回:
        拼接后的文本字符串（多个块之间用空行分隔）
    """
    # 判断 chunks 列表是否为空（None 或空列表都会走这里）
    if not chunks:
        # 如果列表为空，直接返回空字符串，不做任何处理
        return ""
    # 使用 enumerate 遍历 chunks，i 从 0 开始，c 是每个 Document 对象
    # i + 1 让序号从 1 开始，看起来更自然
    # 对每个块调用 _format_chunk 生成格式化文本
    # 最后用 "\n\n"（两个换行符）将所有块的文本连接起来
    # 这样 LLM 就能看到用空行分隔的多个检索片段
    return "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))
