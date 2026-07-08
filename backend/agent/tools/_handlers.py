# ===== 文件顶部: 模块文档字符串 =====
"""工具 handler 函数与注册。"""  # 模块的文档说明，描述这个文件的作用——定义所有工具的 handler 函数并注册到注册表中

# ===== 导入标准库模块 =====
from __future__ import annotations  # 让类型注解变成字符串（延迟求值），避免循环导入问题，Python 3.7+ 支持

# ===== 导入路径操作模块 =====
from pathlib import Path  # 导入 Path 类，用于跨平台的文件路径操作（拼接、解析、判断是否存在等）

# ===== 导入类型注解工具 =====
from typing import List, Optional  # 导入类型注解：List 表示列表类型，Optional 表示可选类型（可以是 None）

# ===== 导入项目配置模块 =====
from base.config import conf  # 导入项目的全局配置对象 conf，里面包含各种配置项（如检索数量、搜索后端等）

# ===== 导入日志模块 =====
from base.logger import logger  # 导入项目的日志记录器，用于输出调试信息和错误日志

# ===== 导入领域模型 =====
from rag.vector_store import Document  # 导入 Document 类，表示知识库中的一个文档块（包含文本内容和元数据）

# ===== 导入工具链中的依赖模块 =====
from ..registry import ToolContext, ToolRegistry  # 从上一级目录的 registry.py 导入 ToolContext（工具上下文）和 ToolRegistry（工具注册表）
from ._format import SYSTEM_PARTITION, format_retrieved_chunks  # 从同目录的 _format.py 导入系统分区常量 和 格式化检索结果块的函数
from ._search_backends import (  # 从同目录的 _search_backends.py 导入各个搜索引擎后端的搜索函数
    _search_duckduckgo, _search_searxng, _search_bocha, _search_bing,  # 分别对应 DuckDuckGo、SearXNG、博查、Bing 四个搜索引擎
)

# ===== 导入全局注册表实例 =====
from . import registry  # 全局注册表实例（在 __init__.py 中定义），所有工具都要通过它来注册

# ===== 工具 handlers 说明 =====
# ─── 工具 handlers ────────────────────────────────
# 每个 handler 签名: (args: dict, ctx: ToolContext) -> str
# 接受两个参数：args（字典类型，LLM 传过来的参数）和 ctx（工具上下文对象），返回字符串（最终给 LLM 看的结果文本）
# args 由 LLM function calling 生成的 JSON 反序列化而来，
# 也就是大模型决定调用哪个工具时，按照工具的参数声明生成的 JSON 数据，Python 解析后就是 args 这个字典
# ctx 包含 vector_store（向量数据库引用）、partition（当前用户分区）、data_store（数据存储）等。
# 这些上下文信息在调用工具时由框架自动注入，handler 函数不需要关心怎么获取

# ===== 工具1: 知识库搜索 handler =====
def _exec_search_kb(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: search_knowledge_base
    触发条件: LLM 认为需要从知识库中检索文档片段来回答问题。

    核心流程（多 query + 多分区 + 去重）:
      1. 从 args 中提取 queries 列表（支持单个字符串自动包装为列表）。
      2. 根据 search_system 标记决定是否同时搜索系统公开文档分区。
      3. 调用 _retrieve_and_dedup 执行多 query 并行检索 + 跨分区去重合并。
      4. 如果命中了结果，调用 format_retrieved_chunks 格式化为文本返回。
      5. 无命中则返回提示信息，让 LLM 决定后续策略。
    """
    # 从 LLM 传过来的参数中获取 queries 字段，如果没有则用空列表
    queries = args.get("queries") or []                 # 从 LLM 参数中获取查询列表
    # 如果 queries 是一个字符串（而不是列表），把它包装成只有一个元素的列表
    if isinstance(queries, str):
        queries = [queries]                              # 兼容单个字符串的情况
    # 清洗每个 query：转成字符串、去掉首尾空格、过滤掉空字符串
    queries = [str(q).strip() for q in queries if str(q).strip()]
    # 如果清洗后没有有效的 query，说明 LLM 没传对参数
    if not queries:
        logger.warning("tool search_knowledge_base 被调用但未提供有效 query")  # 记录警告日志，便于排查问题
        return "(未提供任何检索 query)"  # 返回提示信息，LLM 看到后会重新思考怎么问

    # 从参数中获取 search_system 标记，默认 True（表示同时搜索系统公开文档）
    search_system = args.get("search_system", True)     # 是否同时搜索系统文档分区
    # 如果 search_system 为 True，系统分区列表 = [SYSTEM_PARTITION]，否则为 None（不搜索系统文档）
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    # 记录日志：打印当前查询列表、用户分区、是否搜索系统文档，方便调试
    logger.info(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system}")
    # 调用 _retrieve_and_dedup: 内部按多 query 多分区检索，并做全局去重
    # 传入了向量数据库、查询列表、用户分区、系统分区
    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions)
    # 如果没有检索到任何文档块
    if not chunks:
        logger.info("tool search_knowledge_base 未检索到相关内容, 返回 0 块")  # 记录信息日志
        return "(知识库中未检索到相关内容)"  # 返回提示，告诉 LLM 知识库里没找到

    # ── 可选 LLM Listwise Rerank ─────────────────────────────────────
    # 如果 ToolContext 中注入了 reranker 实例且 conf.enable_llm_rerank 为 True，
    # 调用 LLM 对检索结果进行相关性重排序，再截断到 candidate_top_k 个。
    # 注意：使用第一个 query（主要的用户查询）作为 rerank 依据。
    # 从上下文中获取 reranker 对象（可能没有，所以用 getattr 避免报错）
    reranker = getattr(ctx, "reranker", None)
    # 如果 reranker 存在且已启用（enable 为 True）
    if reranker and reranker.enable:
        # 用第一个 query 作为重排序的基准（最核心的查询意图）
        primary_query = queries[0]
        # 调用 rerank 方法对检索结果重新排序，只保留前 candidate_top_k 个
        chunks = reranker.rerank(primary_query, chunks, top_k=conf.candidate_top_k)
        # 记录日志，打印重排序后留下了多少块
        logger.info(f"LLM Rerank 后保留 {len(chunks)} 个片段")
    else:
        # 不启用 rerank 时直接截断到 candidate_top_k
        # 直接取前 candidate_top_k 个（默认顺序就是向量检索的相关性排序）
        chunks = chunks[: conf.candidate_top_k]

    # 日志记录每个检索块的元数据（用于调试和监控检索质量）
    # 遍历每个检索结果块，记录详细信息方便排查问题
    for ci, c in enumerate(chunks):
        # 获取块的元数据，如果没有元数据就用空字典
        meta = c.metadata or {}
        # 记录日志：块序号、来源文件名、块类型、章节路径、页码、标题、图片路径、内容长度
        logger.info(
            f"检索块 {ci+1}/{len(chunks)}] source={meta.get('source','')!r} "
            f"type={meta.get('chunk_type','')!r} section={meta.get('section_path',[])} "
            f"page={meta.get('page')} caption={meta.get('caption','')!r} "
            f"img={meta.get('img_path','')!r} len={len(c.page_content)}"
        )
        # 取内容前 200 个字符作为预览（去掉换行符让日志更紧凑）
        preview = c.page_content[:200].replace("\n", " ")
        # 记录预览内容日志
        logger.info(f"检索块 {ci+1} 内容] {preview}")
    # 将 Document 列表格式化为 LLM 友好的文本（添加标题、序号、来源等标记）
    formatted = format_retrieved_chunks(chunks)          # 将 Document 列表格式化为 LLM 友好的文本
    # 记录最终返回的文本长度，用于监控上下文使用量
    logger.info(f"tool search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted  # 返回格式化后的检索结果文本

# ===== 工具2: 读取完整文档 handler =====
def _exec_read_full_document(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_full_document
    触发条件: LLM 需要读取完整的文档全文（而非检索片段）。

    安全性设计（路径穿越防护）:
      1. 将拼接后的路径 resolve() 解析为绝对路径。
      2. 检查解析后的路径是否在允许的基目录（conf.vector_store_dir/uploads）之下。
      3. 如果不在（如含 ../ 试图逃逸），直接返回路径非法。

    截断安全性:
      全文内容超过 30000 字符时截断并提示，防止上下文窗口溢出。

    参数:
        args: {"filename": "文档名.pdf"}
        ctx:  工具上下文（含 partition，用于定位用户文档目录）
    """
    # 从参数中获取 filename（要读取的文档文件名），去掉首尾空格，如果没有则用空字符串
    filename = (args.get("filename") or "").strip()
    # 如果文件名为空，说明 LLM 没传 filename 参数
    if not filename:
        return "(未提供 filename 参数)"  # 返回错误提示

    # 提取文件名的主干部分（不带扩展名），例如 "KD指标.pdf" 的 stem 是 "KD指标"
    stem = Path(filename).stem

    # 1. 优先在用户分区查找
    # 拼接基础路径: 配置中的向量存储目录 + "uploads" 子目录
    base = Path(conf.vector_store_dir) / "uploads"
    # 构造候选文件路径列表: 用户分区下 chunk_out/文件主干名/full.md
    candidates = [
        base / (ctx.partition or "") / "chunk_out" / stem / "full.md",
    ]
    # 2. 如果在系统分区，也查 __system__ 分区
    # 如果用户分区存在且不等于 "__system__"（说明当前不是系统分区），加一个系统分区的候选路径
    if ctx.partition and ctx.partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")

    # 初始化 resolved 为 None，表示还没找到有效的文件路径
    resolved = None
    # 遍历所有候选路径，查找第一个真正存在的文件
    for full_md in candidates:
        try:
            # 将路径解析为绝对路径（会处理 ../ 等相对路径符号）
            r = full_md.resolve()
            # 检查解析后的路径是否在 base 目录下，防止路径穿越攻击
            r.relative_to(base.resolve())
            # 如果该路径是一个真实存在的文件
            if r.is_file():
                resolved = r  # 记录找到的文件路径
                break  # 找到就停止循环
        except (ValueError, OSError):
            # ValueError: relative_to 检查失败（路径不在 base 下，说明可能有 ../ 逃逸）
            # OSError: 文件系统错误
            continue  # 跳过这个候选路径，继续检查下一个

    # 如果所有候选路径都没找到有效文件
    if resolved is None:
        logger.warning(f"tool read_full_document 未找到: {resolved}")  # 记录警告日志
        return f"(未找到 {filename} 的全文, 可能该文档不是由 MinerU 解析的)"  # 返回提示

    # 找到了文件，开始读取内容
    try:
        # 以 UTF-8 编码读取文件的全部文本内容
        content = resolved.read_text(encoding="utf-8")
        # 记录成功日志，包含文件名和字符数
        logger.info(f"tool read_full_document 成功: {filename} ({len(content)} 字符)")
        # 截断安全性: 全文超过 30000 字符时截断并附加提示
        # 防止返回过长的内容撑爆 LLM 的上下文窗口
        if len(content) > 30000:
            content = content[:30000] + "\n\n...(全文过长，已截取前 30000 字符)..."
        return content  # 返回全文内容（可能被截断）
    except Exception as e:
        # 读取过程中发生任何异常（如文件编码错误、权限不足等）
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")  # 记录警告日志
        return f"(读取 {filename} 失败: {e})"  # 返回错误信息



# ===== 工具3: 网页搜索 handler =====
def _exec_web_search(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: web_search
    触发条件: LLM 需要互联网上的实时信息（最新新闻、实时数据、知识库未覆盖的内容）。

    多后端策略（由配置 conf.search_backend 控制）:
      - "duckduckgo" (默认): 无需 API Key，但国内需要 VPN
      - "searxng":       自建或公开的 SearXNG 实例，国内可直连
      - "bocha":        博查 AI Search API，国内可用无需 VPN（需 API Key）
      - "bing":          Bing Web Search API v7，国内可用（需 Azure Key）

    自动时间语境增强:
      如果 query 中不含 4 位年份（如 2025），自动拼接当前年份前缀，
      确保搜索结果的时效性。

    安全保护:
      max_results 限制在 1-10 之间（超过 10 的自动截断）。

    参数:
        args: {"query": "搜索关键词", "max_results": 5}
        ctx:  工具上下文
    """
    # 从参数中获取搜索关键词 query，去掉首尾空格
    query = (args.get("query") or "").strip()
    # 如果 query 为空，说明 LLM 没传搜索词
    if not query:
        return "(未提供搜索 query)"  # 返回错误提示
    # 限制结果数量在 1-10 之间，防止返回过多结果浪费上下文
    # 先从参数中取 max_results，默认为 5，然后和 10 取最小值，最多 10 条
    max_results = min(int(args.get("max_results", 5)), 10)

    # 记录日志：搜索关键词、最大结果数、使用的搜索引擎后端
    logger.info(f"tool web_search query={query!r} max={max_results} backend={conf.search_backend}")

    # 自动增强时间语境: 检测 query 中是否包含 4 位年份，缺失则补当前年份
    # 使得搜索结果在跨年时仍有合理的时效性
    from datetime import datetime as _dt  # 导入 datetime 模块，用于获取当前时间
    _now = _dt.now()  # 获取当前日期时间
    # 用正则表达式检查 query 中是否已经包含 4 位数字年份（19xx 或 20xx）
    if not __import__('re').search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query):
        # 如果没有年份，在 query 前面加上当前年份，例如 "2026年"
        query = f"{_now.year}年 {query}"
        # 记录日志，说明自动补充了年份
        logger.info(f"tool web_search 已补年份: {query!r}")

    # 根据配置选择搜索引擎后端
    backend = conf.search_backend or "duckduckgo"  # 从配置读取后端名称，默认为 duckduckgo
    # 根据不同的后端调用对应的搜索函数
    if backend == "searxng":
        results = _search_searxng(query, max_results)  # 调用 SearXNG 搜索
    elif backend == "bocha":
        results = _search_bocha(query, max_results)  # 调用博查搜索
    elif backend == "bing":
        results = _search_bing(query, max_results)  # 调用 Bing 搜索
    else:
        results = _search_duckduckgo(query, max_results)  # 默认使用 DuckDuckGo 搜索
    # 搜索不可用（如网络异常、API Key 未配置）时返回明确提示，避免进入重试死循环
    if results is None:
        return "(联网搜索暂时不可用，请直接回答，不要重试。)"  # 明确告诉 LLM 不要重试
    # 搜索成功但没有结果
    if not results:
        return "(未找到相关搜索结果)"  # 返回空结果提示

    # 格式化为 LLM 易读的文本（编号 + 标题 + 摘要 + URL）
    lines = []  # 创建一个空列表，用来存放格式化后的文本行
    # 遍历搜索结果，enumerate 从 1 开始编号
    for i, r in enumerate(results, 1):
        # 获取标题，去掉首尾空格
        title = r.get("title", "").strip()
        # 获取摘要/正文，去掉首尾空格
        snippet = r.get("body", "").strip()
        # 获取 URL 链接，去掉首尾空格
        url = r.get("href", "").strip()
        # 添加搜索结果编号和标题
        lines.append(f"[搜索结果 {i}] {title}")
        # 如果有摘要内容，添加摘要（缩进显示）
        if snippet:
            lines.append(f"   {snippet}")
        # 如果有 URL，添加 URL（缩进显示）
        if url:
            lines.append(f"   {url}")
        # 每条结果之间加一个空行，方便阅读
        lines.append("")

    # 将所有行用换行符连接起来，再去掉首尾空白
    output = "\n".join(lines).strip()
    # 记录日志：返回了多少条结果，总文本长度
    logger.info(f"tool web_search 返回 {len(results)} 条结果, 长度={len(output)}")
    return output  # 返回格式化后的搜索结果文本

# ===== 工具4: 列出文档 handler =====
def _exec_list_documents(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: list_documents
    触发条件: LLM 需要查看知识库中有哪些文档（如用户提到"那份报告"需确定具体文件名）。

    功能:
      - 列出当前用户分区的所有文档（标记 📄）
      - 可选同时列出系统分区的公开文档（标记 📖）
      - 支持按关键词过滤（pattern 参数不区分大小写）

    参数:
        args: {"pattern": "可选关键词", "list_system": true}
        ctx:  工具上下文
    """
    # 如果向量数据库不可用（没有初始化成功）
    if not ctx.vector_store:
        return "(知识库不可用)"  # 返回提示
    # 从参数中获取过滤关键词 pattern，转小写、去空格
    pattern = (args.get("pattern") or "").strip().lower()
    # 从参数中获取是否列出系统文档，默认为 True
    list_system = args.get("list_system", True)

    # 记录日志：过滤关键词、是否列系统文档、当前用户分区
    logger.info(f"tool list_documents pattern={pattern!r} list_system={list_system} partition={ctx.partition}")

    # 获取当前用户分区的文档列表
    # 调用向量数据库的 get_documents_by_partition 方法，传入当前用户分区
    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []

    # 合并系统分区的文档（如果 list_system=true）
    docs = []  # 初始化一个空列表，用来存放所有要显示的文档
    # 遍历用户文档，每条前面加 📄 标记（表示用户私有文档）
    for d in user_docs:
        docs.append(f"📄 {d}")

    # 如果需要列出系统文档
    if list_system:
        # 获取系统分区的文档列表
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        # 遍历系统文档，每条前面加 📖 标记（表示系统公开文档）
        for d in system_docs:
            label = f"📖 {d}"
            # 如果这条文档已经出现在列表中（同名），就跳过，避免重复
            if label not in docs:              # 避免同名文档重复列出
                docs.append(label)

    # 可选关键词过滤
    # 如果传了 pattern 过滤关键词
    if pattern:
        # 只保留文档名中包含 pattern（不区分大小写）的条目
        docs = [d for d in docs if pattern in d.lower()]

    # 如果没有匹配的文档
    if not docs:
        return "(当前没有匹配的文档)"  # 返回提示

    # 按字母排序，每行前面加 "- " 形成列表样式
    lines = [f"- {d}" for d in sorted(docs)]
    # 返回格式化的文档列表文本
    return "当前知识库中的文档：\n" + "\n".join(lines)

# ===== 工具5: 读取归档记录 handler =====
def _exec_read_archive(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_archive
    触发条件: system prompt 中出现了 "#[archive_id]" 标记，
             需要读取被归档的历史对话记录以恢复上下文。

    功能:
      通过 data_store.format_archive_turns 从归档存储中读取指定 ID 的对话历史，
      格式化为 LLM 易读的文本。

    参数:
        args: {"archive_id": "arch_xxx"}
        ctx:  工具上下文（含 data_store 引用）
    """
    # 从参数中获取 archive_id（归档记录的唯一标识），去掉首尾空格
    archive_id = (args.get("archive_id") or "").strip()
    # 如果 archive_id 为空，说明 LLM 没传参数
    if not archive_id:
        return "(未提供 archive_id 参数)"  # 返回错误提示
    # 如果数据存储不可用（没有初始化）
    if not ctx.data_store:
        return "(归档存储不可用)"  # 返回提示

    # 尝试读取归档
    try:
        # 调用 data_store 的 format_archive_turns 方法，根据 archive_id 读取归档对话历史
        result = ctx.data_store.format_archive_turns(archive_id)
        # 如果返回 None，说明该归档 ID 不存在
        if result is None:
            return f"(归档 {archive_id} 不存在)"  # 返回提示
        # 记录成功日志
        logger.info(f"tool read_archive 成功: {archive_id} ({len(result)} 字符)")
        return result  # 返回归档对话历史文本
    except Exception as e:
        # 读取过程中发生异常
        logger.warning(f"tool read_archive 失败 ({archive_id}): {e}")  # 记录警告日志
        return f"(读取归档失败: {e})"  # 返回错误信息

# ===== 工具6: 请求用户澄清 handler（虚拟工具） =====
def _exec_ask_clarification(args: dict, ctx: ToolContext) -> str:
    """
    虚拟工具 handler: ask_user_for_clarification

    虚拟工具模式说明:
      这是唯一一个不在后端真正执行逻辑的工具。它的作用是在 LLM 侧的 function calling
      中作为一个"信号"——当 LLM 认为用户请求过于模糊时调用它。
      外部 agent 循环检测到该工具被调用时，不会执行 handler，而是直接将 question
      文本返回给用户作为回复，并中止后续的自动生成流程。
      等待用户补充信息后再继续。

    参数:
        args: {"question": "请问您指的是哪份文档？"}
        ctx:  工具上下文（忽略）

    返回:
        question 文本（外部循环捕获后直接展示给用户）
    """
    # 从参数中获取 question（要向用户提的问题），如果没有则用默认提示语
    question = args.get("question", "需要您提供更多信息。")
    # 记录日志：LLM 请求澄清的内容
    logger.info(f"tool ask_user_for_clarification: LLM 请求澄清: {question}")
    return question  # 返回问题文本（外部循环会截获它，直接展示给用户）

# ===== 工具7: 读取网页 URL handler =====
def _exec_read_url(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_url
    触发条件: web_search 找到了一篇看起来信息丰富的文章 URL，
             需要阅读完整内容（而非仅摘要）时调用。

    流程:
      1. 用 requests 抓取 URL 的 HTML。
      2. 用 Python 标准库 html.parser 提取正文文本。
      3. 截断到 20000 字符防止上下文溢出。

    参数:
        args: {"url": "https://example.com/article"}
        ctx:  工具上下文
    """
    # 从参数中获取 URL，去掉首尾空格
    url = (args.get("url") or "").strip()
    # 如果 URL 为空，说明 LLM 没传参数
    if not url:
        return "(未提供 URL 参数)"  # 返回错误提示

    # 记录日志：开始抓取该 URL
    logger.info(f"tool read_url: 开始抓取 {url}")
    # 尝试抓取网页
    try:
        import requests as _req  # 导入 requests 库（用于发送 HTTP 请求）
        resp = _req.get(  # 发送 GET 请求获取网页内容
            url,  # 要访问的 URL
            timeout=15,  # 超时时间 15 秒，防止网络卡住
            headers={  # 设置请求头，伪装成正常浏览器访问，避免被网站屏蔽
                "User-Agent": (  # User-Agent 字符串，模仿 Chrome 120 浏览器
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        resp.raise_for_status()  # 检查 HTTP 响应状态码，如果不是 200 会抛出异常

        # 用 stdlib 的 HTMLParser 提取纯文本
        # 使用 Python 标准库中的 HTMLParser，不需要额外安装第三方库
        from html.parser import HTMLParser as _HTMLParser  # 导入 HTML 解析器

        # 定义一个继承 HTMLParser 的子类，用来从 HTML 中提取纯文本
        class _TextExtractor(_HTMLParser):
            # 初始化方法
            def __init__(self):
                super().__init__()  # 调用父类的初始化方法
                self._text = []  # 创建一个列表，用来存放提取出来的文本片段
                self._skip = False  # 标记是否跳过当前标签内的内容（如 script、style）

            # 遇到开始标签时调用
            def handle_starttag(self, tag, attrs):
                # 如果标签是 script 或 style（里面的内容不是正文），设置跳过标记为 True
                if tag in ("script", "style"):
                    self._skip = True

            # 遇到结束标签时调用
            def handle_endtag(self, tag):
                # 如果结束标签是 script 或 style，取消跳过标记
                if tag in ("script", "style"):
                    self._skip = False
                # 如果是段落、换行、标题、列表项、表格行、div 等块级标签，添加换行符
                if tag in ("p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div"):
                    self._text.append("\n")

            # 遇到文本数据时调用
            def handle_data(self, data):
                # 如果当前不在跳过状态（不在 script 或 style 里面）
                if not self._skip:
                    self._text.append(data.strip())  # 添加去掉首尾空格的文本

            # 获取最终提取的纯文本
            def get_text(self):
                return "".join(self._text)  # 把所有文本片段拼接成一个完整的字符串

        # 创建文本提取器的实例
        extractor = _TextExtractor()
        # 向解析器喂入 HTML 内容，触发一系列的 handle_starttag/handle_data/handle_endtag 调用
        extractor.feed(resp.text)
        # 获取提取出来的纯文本
        text = extractor.get_text()

        # 压缩多余空行
        import re as _re  # 导入正则表达式模块
        # 将连续 3 个及以上的换行符替换为 2 个换行符，去掉多余空行
        text = _re.sub(r"\n{3,}", "\n\n", text).strip()

        # 截断防止上下文溢出
        # 如果提取的文本超过 20000 字符
        if len(text) > 20000:
            # 截取前 20000 字符，并附加截断提示
            text = text[:20000] + "\n\n...(网页内容过长，已截取前 20000 字符)..."

        # 记录成功日志
        logger.info(f"tool read_url 成功: {url} ({len(text)} 字符)")
        return text  # 返回网页文本内容

    except Exception as e:
        # 抓取或解析过程中发生异常（网络错误、解析错误等）
        logger.warning(f"tool read_url 失败 ({url}): {e}")  # 记录警告日志
        return f"(读取网页失败: {e})"  # 返回错误信息


# ===== 注册内建工具 =====
# ─── 注册内建工具 ───────────────────────────────────
# 以下通过 registry.register() 注册所有内建工具。
# 每个注册包含:
#   - name:        工具名（LLM function calling 中使用的标识符）
#                  大模型就是通过这个名字来识别和调用哪个工具
#   - description: 工具描述（作为 system prompt 的一部分，引导 LLM 何时调用）
#                  大模型通过阅读这段描述来决定什么情况下该调用这个工具
#   - parameters:  JSON Schema 格式的参数声明（LLM 据此生成合法参数）
#                  告诉大模型这个工具有哪些参数、每个参数的类型和含义
#   - handler:     实际执行函数 (args, ctx) -> str
#                  当大模型决定调用工具时，实际运行的 Python 函数
#   - source:      注册来源（模块名，用于调试）
#                  方便定位这个工具是在哪个文件中注册的
# 注册完成后，外部通过 registry.dispatch(name, args_json, ctx) 调用。

# --- 工具 1: ask_user_for_clarification ---
# 虚拟工具，用于请求用户澄清。
# 外部 agent 循环会截获此工具调用，不执行 handler，直接向用户展示 question。
# 调用 registry.register 方法，将工具的信息注册到全局注册表中
registry.register(
    name="ask_user_for_clarification",  # 工具名称：LLM 通过这个名字来调用
    description=(  # 工具描述：引导 LLM 在什么情况下使用
        "当用户的请求非常模糊（如未指定具体文档、指代不清）且你无法通过已有的检索结果自行推理出正确答案时调用此工具。"
        "调用此工具后，对话会立即中断并将你设置的 question 抛给用户等待补充。"
        "除非别无他法，否则请尽量利用知识库和其他工具完成任务。"
    ),
    parameters={  # 参数声明：告诉 LLM 这个工具需要哪些参数
        "type": "object",  # 参数类型是对象（JSON 对象）
        "properties": {  # 对象的属性列表
            "question": {  # question 参数
                "type": "string",  # 参数类型是字符串
                "description": "你需要向用户询问的具体问题，比如'请问您指的是本季度的哪一份财报？'",  # 参数描述
            },
        },
        "required": ["question"],  # 必填参数：question 必须提供
    },
    handler=_exec_ask_clarification,  # 绑定的处理函数
    source=__name__,  # 注册来源：当前模块的名称
)

# --- 工具 2: search_knowledge_base ---
# 知识库检索工具，支持多 query 并行检索 + 多分区 + 去重合并。
# LLM 通过 queries 参数传入检索语句列表，search_system 控制是否同时搜索系统文档。
# 这是最核心的工具，负责从向量数据库中检索相关文档片段
registry.register(
    name="search_knowledge_base",  # 工具名称
    description=(  # 工具描述：告诉 LLM 何时检索知识库
        "在用户的知识库中检索与问题相关的文档片段。当问题涉及具体文档内容"
        "(报告、表格、专业数据、上传过的文件中提到的事实) 时调用; 闲聊 / 问候 / "
        "通用常识问题不要调用。可一次性传入多个 query 做并行检索。"
        "知识库包含用户私有文档和系统公开文档。"
        "如需只搜索用户自己的文档、排除系统数据，请设置 search_system=false。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "queries": {  # queries 参数：查询词列表
                "type": "array",  # 类型是数组
                "items": {"type": "string"},  # 数组中的每个元素是字符串
                "minItems": 1,  # 最少 1 个查询词
                "maxItems": 5,  # 最多 5 个查询词（防止一次检索太多）
                "description": (  # 参数描述：指导 LLM 如何构造好的查询
                    "用于向量检索的查询列表。简单问题 1 个; "
                    "对比类 / 多焦点 / 多条件问题拆成 2-5 个独立子查询。"
                    "查询用名词短语或简洁的检索语句, 而不是完整问句; "
                    "用户说'那份报告'之类时应用文档清单里的实际文件名替换。"
                ),
            },
            "search_system": {  # search_system 参数：是否搜索系统文档
                "type": "boolean",  # 布尔类型
                "description": "是否同时搜索系统公开文档。默认为 true（搜索全部）。设为 false 则只搜索用户自己的文档。",  # 参数描述
                "default": True,  # 默认值为 True（搜索全部）
            },
        },
        "required": ["queries"],  # queries 是必填参数，search_system 有默认值所以可选
    },
    handler=_exec_search_kb,  # 绑定的处理函数
    source=__name__,  # 注册来源
)

# --- 工具 3: read_full_document ---
# 读取完整文档全文，支持 MinerU 解析后的 Markdown 格式。
# 含路径穿越防护（resolve + relative_to 双重校验）和 30000 字符截断保护。
# 当检索片段不够用时，LLM 可以调用这个工具来阅读整篇文档
registry.register(
    name="read_full_document",  # 工具名称
    description=(  # 工具描述
        "读取用户上传的某一篇文档的完整全文内容（Markdown 格式）。"
        "当需要仔细阅读整篇文档（而非检索片段）、文档被用户明确点名要求阅读、"
        "或检索片段不足以回答问题时调用。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "filename": {  # filename 参数：要读取的文档文件名
                "type": "string",  # 字符串类型
                "description": (  # 参数描述
                    "要读取的文档文件名（含扩展名）。"
                    "必须是文档清单中出现的完整文件名，如 KD指标.pdf"
                ),
            }
        },
        "required": ["filename"],  # filename 是必填参数
    },
    handler=_exec_read_full_document,  # 绑定的处理函数
    source=__name__,  # 注册来源
)

# --- 工具 4: read_url ---
# URL 全文阅读工具，配合 web_search 使用。
# web_search 只返回摘要，LLM 可用此工具深入阅读整篇文章。
# 使用 requests 抓取 + stdlib HTMLParser 提取纯文本，无需额外依赖。
# 这个工具只使用 Python 标准库，不需要安装额外的 HTML 解析库
registry.register(
    name="read_url",  # 工具名称
    description=(  # 工具描述
        "读取指定网页的完整文字内容（纯文本格式）。"
        "当 web_search 找到了一篇看起来信息量很大的文章、"
        "或者用户给出了一个具体的网页链接时调用此工具阅读全文。"
        "注意：只能读取公开可访问的网页，不能读取登录后才能查看的页面。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "url": {  # url 参数：要读取的网页地址
                "type": "string",  # 字符串类型
                "description": "要读取的网页完整 URL（必须以 http:// 或 https:// 开头）",  # 参数描述
            },
        },
        "required": ["url"],  # url 是必填参数
    },
    handler=_exec_read_url,  # 绑定的处理函数
    source=__name__,  # 注册来源
)

# --- 工具 5: web_search ---
# 互联网搜索工具，支持 duckduckgo / searxng / bocha / bing 四个后端。
# 自动为查询补充年份以增强时效性，max_results 上限为 10 条。
# 当知识库无法回答实时问题时，LLM 可以调用这个工具搜索互联网
registry.register(
    name="web_search",  # 工具名称
    description=(  # 工具描述
        "在互联网上搜索最新的实时信息。当用户问到需要实时数据、最新新闻、"
        "当前事件、或知识库中不包含的时效性内容时调用。"
        "如果知识库中已经有相关内容，优先使用 search_knowledge_base。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "query": {  # query 参数：搜索关键词
                "type": "string",  # 字符串类型
                "description": "搜索关键词，用名词短语或简洁问句。",  # 参数描述
            },
            "max_results": {  # max_results 参数：返回结果数量
                "type": "integer",  # 整数类型
                "default": 5,  # 默认返回 5 条
                "description": "返回结果数量（1-10）。",  # 参数描述
            },
        },
        "required": ["query"],  # query 是必填参数，max_results 有默认值所以可选
    },
    handler=_exec_web_search,  # 绑定的处理函数
    source=__name__,  # 注册来源
)

# --- 工具 6: list_documents ---
# 列出知识库中文档，支持按关键词 pattern 过滤、按分区（用户/系统）区分。
# 用于 LLM 确认用户所指文档的完整文件名。
# 当用户含糊地提到"那个文档""那份报告"时，LLM 可以通过这个工具先看看有什么文档
registry.register(
    name="list_documents",  # 工具名称
    description=(  # 工具描述
        "列出当前知识库中的文档（支持按文件名过滤）。"
        "知识库包含用户私有文档和系统公开文档，会分别标注 📄 和 📖。"
        "如需只列用户文档，请设置 list_system=false。"
        "当用户说「那份报告」「那个文档」需要确定具体文件名时调用，"
        "或者在搜索前确认知识库中有什么文档时调用。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "pattern": {  # pattern 参数：文件名过滤关键词
                "type": "string",  # 字符串类型
                "description": "可选的文件名关键词（如「KD」「财报」），不传则列出全部。",  # 参数描述
            },
            "list_system": {  # list_system 参数：是否同时列出系统文档
                "type": "boolean",  # 布尔类型
                "description": "是否同时列出系统公开文档。默认为 true（列出全部）。设为 false 则只列用户自己的文档。",  # 参数描述
                "default": True,  # 默认列出全部
            },
        },
        "required": [],  # 没有必填参数（两个参数都有默认值）
    },
    handler=_exec_list_documents,  # 绑定的处理函数
    source=__name__,  # 注册来源
)

# --- 工具 7: read_archive ---
# 读取归档对话历史的工具。当 system message 中包含 #[archive_id] 标记时，
# LLM 可调用此工具恢复被压缩的旧对话上下文。
# 用于长对话的场景：当对话太长了，系统会把早期对话归档压缩，LLM 可以按需读取
registry.register(
    name="read_archive",  # 工具名称
    description=(  # 工具描述
        "读取被归档的历史对话记录。当 system message 中出现「历史摘要 #[archive_id]」标记时，"
        "可调用此工具获取该段历史的完整对话内容。每次调用读取一个归档。"
    ),
    parameters={  # 参数声明
        "type": "object",  # JSON 对象类型
        "properties": {  # 属性定义
            "archive_id": {  # archive_id 参数：归档记录的唯一 ID
                "type": "string",  # 字符串类型
                "description": "归档 ID，格式如 arch_xxx。从历史摘要标记 #[archive_id] 中提取。",  # 参数描述
            },
        },
        "required": ["archive_id"],  # archive_id 是必填参数
    },
    handler=_exec_read_archive,  # 绑定的处理函数
    source=__name__,  # 注册来源
)


# ===== 向后兼容导出 =====
# ─── 向后兼容导出 ────────────────────────────────
# 为旧版 import (from agent.tools import TOOL_SCHEMAS, execute_tool) 提供兼容层。
# 新代码推荐: from agent.tools import registry
#   - registry.schemas       → 所有工具的 OpenAPI schema 列表
#   - registry.dispatch(...) → 根据工具名派发到对应 handler
# 保持向后兼容，这样旧代码不用改也能继续工作

# 从 registry 中获取所有工具的 schemas（OpenAPI 格式的参数声明列表）
TOOL_SCHEMAS = registry.schemas  # list[dict]，供旧版 function calling schema 构建用

# ===== 向后兼容的 dispatch 函数 =====
def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """
    向后兼容的 dispatch 函数。

    旧用法:
      execute_tool(name, args, vector_store=..., partition=...)
    新用法:
      registry.dispatch(name, args, ctx=ToolContext(vector_store=..., partition=...))

    这个包装函数自动从 kwargs 中提取所需字段构造 ToolContext。
    """
    from ..registry import ToolContext  # 导入 ToolContext 类（用于构造工具上下文对象）
    # 从关键字参数中提取 vector_store 和 partition 来构造 ToolContext 对象
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),  # 从 kwargs 中提取向量数据库引用
        partition=kwargs.get("partition"),  # 从 kwargs 中提取用户分区
    )
    # 调用 registry.dispatch 将请求派发给对应的 handler 处理
    return registry.dispatch(name, args_json, ctx=ctx)


# ===== 内部辅助函数 =====
# ─── 内部辅助 ───────────────────────────────────

# ===== 核心检索去重函数 =====
def _retrieve_and_dedup(
    vector_store, queries, partition, system_partitions: Optional[list] = None,
) -> List[Document]:
    """
    核心内部函数: 多 query + 多分区 + 全局去重检索。

    算法流程:
      1. 收集需要搜索的所有分区: 用户分区 + 系统分区（可选）。
      2. 对每个分区单独调用 _search_partition:
         - 单 query 时直接检索 top_k 个结果。
         - 多 query 时公平分配每个 query 检索 per_q 个结果，
           按 chunk id/page_content 去重后合并（避免重复块）。
      3. 跨分区再做一次全局去重（按 id 或 page_content），合并所有结果。
      4. 返回合并后的 Document 列表。

    参数:
        vector_store:     向量数据库引用
        queries:          查询字符串列表（至少一个）
        partition:        当前用户分区名
        system_partitions: 系统分区列表（如 ["__system__"]），为 None 时不搜索

    返回:
        去重后的 Document 列表
    """
    # 如果查询列表为空，直接返回空列表
    if not queries:
        return []

    # 收集要搜索的所有分区（用户分区 + 系统分区）
    # 如果 partition 不为空，初始分区列表包含用户分区
    search_partitions = [partition] if partition else []
    # 如果传了系统分区列表，把不重复的系统分区加进去（避免重复添加同一分区）
    if system_partitions:
        search_partitions.extend(sp for sp in system_partitions if sp and sp not in search_partitions)

    # 定义内部函数：在单个分区中执行多 query 检索并去重
    def _search_partition(p):
        """
        在单个分区中执行多 query 检索并去重。

        单 query 情况:
          直接调用 vector_store.search(query, top_k=conf.retrieval_top_k, partition=p)，
          返回最相关的 top_k 个块。

        多 query 情况（核心去重逻辑）:
          1. 总候选数上限 = conf.candidate_top_k（如 30），平分给每个 query。
          2. 每个 query 独立检索 conf.retrieval_top_k（如 20）个结果。
          3. 每个 query 只取前 per_q 个（如 30/N）进入合并池。
          4. 用 seen set 按 chunk id（首选）或 page_content（回退）进行内存去重。
          5. 目的: 避免多个相似 query 拉回相同的文档块，
             同时确保覆盖多个不同 focus 的检索需求。
        """
        # 单 query: 快速路径，直接检索并返回
        if len(queries) == 1:
            try:
                # 调用向量数据库的 search 方法，用唯一的一个 query 去检索
                return vector_store.search(
                    query=queries[0], top_k=conf.retrieval_top_k,  # 检索前 retrieval_top_k 个结果
                    partition=p,  # 指定分区
                )
            except Exception as e:
                # 检索失败时记录错误日志
                logger.error(f"检索失败 (query={queries[0]!r}, partition={p}): {e}")
                return []  # 返回空列表，不影响其他 query 的检索

        # 多 query: 公平分配，每 query 取 per_q 个，合并去重
        per_q = max(1, conf.retrieval_top_k // len(queries))  # 每个 query 平均分配的结果数，至少 1 个
        seen = set()  # 创建一个 set 集合，用来记录已经见过的文档块 ID，用于去重
        merged: List[Document] = []  # 初始化一个空列表，用来存放合并后的结果
        # 遍历每一个 query
        for q in queries:
            try:
                # 用当前 query 去向量数据库中检索
                results = vector_store.search(
                    query=q, top_k=conf.retrieval_top_k,  # 检索 top_k 个
                    partition=p,  # 指定分区
                )
            except Exception as e:
                # 检索失败时记录错误日志，跳过这个 query 继续下一个
                logger.error(f"检索失败 (query={q!r}, partition={p}): {e}")
                continue
            # 每个 query 只取前 per_q 个，然后按 id 去重
            for c in results[:per_q]:  # 只取前 per_q 个结果
                # 用块的 metadata.id 作为去重键，如果没有 id 就用 page_content 文本本身
                key = c.metadata.get("id") or c.page_content
                # 如果这个键已经在 seen 集合中，说明之前已经加过了，跳过
                if key in seen:
                    continue
                # 否则加入 seen 集合，表示已经见过
                seen.add(key)
                # 把这个块添加到合并列表中
                merged.append(c)
        return merged  # 返回当前分区去重后的结果列表

    # 跨分区合并: 对所有分区（用户分区 + 系统分区）分别检索，
    # 然后用全局 seen set 做二次去重，避免不同分区返回同一文档块。
    seen = set()  # 全局去重集合，用于跨分区去重
    merged: List[Document] = []  # 存放所有分区合并后的结果
    # 遍历所有需要搜索的分区
    for p in search_partitions:
        # 调用 _search_partition 对当前分区进行检索
        results = _search_partition(p)
        # 遍历检索结果
        for c in results:
            # 用块的 id 或内容作为去重键
            key = c.metadata.get("id") or c.page_content
            # 如果已经在 seen 中，跳过（说明已经在其他分区见过这个块）
            if key in seen:
                continue
            # 首次见到，加入 seen 集合
            seen.add(key)
            # 添加到合并结果列表
            merged.append(c)

    # 记录日志：打印所有搜索的分区和最终合并后的块数
    logger.info(f"多分区检索完成: partitions={search_partitions}, 合并后 {len(merged)} 块")
    return merged  # 返回最终去重合并后的文档块列表
