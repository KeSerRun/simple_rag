"""
Agent 工具模块 -- 注册表模式 + 检索结果格式化。

核心架构说明（注册表模式）：
  1. 全局唯一的 `registry = ToolRegistry()` 实例作为注册表中心。
  2. 每个工具通过 `registry.register(name, description, parameters, handler, source)`
     注册，将工具名称映射到其 schema（供 LLM function calling 用）和 handler 函数。
  3. 外部调用时通过 `registry.dispatch(name, args_json, ctx=ToolContext(...))` 派发，
     根据工具名找到 handler，传入反序列化后的 args dict 和上下文 ctx 执行。
  4. 这种模式解耦了工具的定义、schema 声明和执行逻辑，便于统一管理。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from base.config import conf          # 全局配置对象，包含 search_backend / API Key 等
from base.logger import logger        # 结构化日志

from rag.core.document_process import Document  # 文档块数据类，含 page_content 和 metadata

from .registry import ToolContext, ToolRegistry  # 工具上下文（vector_store, partition 等）和注册表

# 系统级数据分区名：系统公开文档放在此分区下，对所有用户可见
SYSTEM_PARTITION = "__system__"

# ─── 全局注册中心 ────────────────────────────────
# 单一全局注册表实例，所有内建工具都在模块加载时注册到此实例上。
registry = ToolRegistry()

# ─── 检索结果格式化 ──────────────────────────────
# 将向量检索返回的 Document 列表格式化为 LLM 易读的文本。
# 每个块附带元数据标头（来源、章节路径、页码、文档类型、分区标记），
# 如果是图片/图表块且关联了图片路径，则追加 Markdown 图片引用。


def _format_chunk(idx: int, chunk: Document) -> str:
    """
    格式化单个检索块为带元数据的文本。

    参数:
        idx:   块序号（从 1 开始）
        chunk: 检索结果 Document 对象，含 page_content（文本）和 metadata（元数据字典）

    返回:
        格式如 "【片段 1 | 来源 | 章节路径 | p.页码】\\n文本内容" 的字符串。
        如果是图片/图表块且存在图片路径，还会附加 Markdown 图片引用。
    """
    meta = chunk.metadata or {}
    # --- 构建元数据标头部分 ---
    parts = []
    source = (meta.get("source") or "").strip()
    if source:
        parts.append(f"**{source}**")                              # 来源文件名（加粗）
    section_path = meta.get("section_path") or []
    if section_path:
        parts.append(" > ".join(s for s in section_path if s))     # 文档内章节路径
    page = meta.get("page")
    if page is not None:
        parts.append(f"p.{page}")                                  # 页码
    chunk_type = (meta.get("chunk_type") or "").strip()
    if chunk_type and chunk_type != "text":
        parts.append(chunk_type)                                   # 块类型（image/chart/table 等）
    # 标注来源分区（系统文档 vs 用户文档），便于 LLM 判断权威性
    partition = (meta.get("partition") or "").strip()
    if partition == SYSTEM_PARTITION:
        parts.append("📖 系统文档")
    elif partition:
        parts.append("📄 用户文档")
    header = f"【片段 {idx} | {' | '.join(parts)}】" if parts else f"【片段 {idx}】"
    # --- 正文部分 ---
    body = chunk.page_content.strip()
    # 如果是图片/图表块且有图片路径，追加 Markdown 图片链接
    img_path = (meta.get("img_path") or "").strip()
    if img_path and chunk_type in ("image", "chart") and source:
        stem = Path(source).stem                                    # 去掉扩展名的文件名作为 URL 路径
        img_md = f"\n\n![图](/api/documents/image/{stem}/{img_path})"
        return f"{header}\n{body}{img_md}"
    return f"{header}\n{body}"


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
    if not chunks:
        return ""
    return "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))


# ─── 工具 handlers ────────────────────────────────
# 每个 handler 签名: (args: dict, ctx: ToolContext) -> str
# args 由 LLM function calling 生成的 JSON 反序列化而来，
# ctx 包含 vector_store（向量数据库引用）、partition（当前用户分区）、data_store（数据存储）等。


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
    queries = args.get("queries") or []                 # 从 LLM 参数中获取查询列表
    if isinstance(queries, str):
        queries = [queries]                              # 兼容单个字符串的情况
    queries = [str(q).strip() for q in queries if str(q).strip()]
    if not queries:
        logger.warning("tool search_knowledge_base 被调用但未提供有效 query")
        return "(未提供任何检索 query)"

    search_system = args.get("search_system", True)     # 是否同时搜索系统文档分区
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    logger.info(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system}")
    # 调用 _retrieve_and_dedup: 内部按多 query 多分区检索，并做全局去重
    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions)
    if not chunks:
        logger.info("tool search_knowledge_base 未检索到相关内容, 返回 0 块")
        return "(知识库中未检索到相关内容)"

    # ── 可选 LLM Listwise Rerank ─────────────────────────────────────
    # 如果 ToolContext 中注入了 reranker 实例且 conf.enable_llm_rerank 为 True，
    # 调用 LLM 对检索结果进行相关性重排序，取 Top-15 最相关的片段。
    # 注意：使用第一个 query（主要的用户查询）作为 rerank 依据。
    reranker = getattr(ctx, "reranker", None)
    if reranker and reranker.enable:
        primary_query = queries[0]
        chunks = reranker.rerank(primary_query, chunks, top_k=min(15, len(chunks)))
        logger.info(f"LLM Rerank 后保留 {len(chunks)} 个片段")

    # 日志记录每个检索块的元数据（用于调试和监控检索质量）
    for ci, c in enumerate(chunks):
        meta = c.metadata or {}
        logger.info(
            f"检索块 {ci+1}/{len(chunks)}] source={meta.get('source','')!r} "
            f"type={meta.get('chunk_type','')!r} section={meta.get('section_path',[])} "
            f"page={meta.get('page')} caption={meta.get('caption','')!r} "
            f"img={meta.get('img_path','')!r} len={len(c.page_content)}"
        )
        preview = c.page_content[:200].replace("\n", " ")
        logger.info(f"检索块 {ci+1} 内容] {preview}")
    formatted = format_retrieved_chunks(chunks)          # 将 Document 列表格式化为 LLM 友好的文本
    logger.info(f"tool search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted


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
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    stem = Path(filename).stem
    # 构造 full.md 路径: {向量库目录}/uploads/{用户分区}/{文件名不含扩展}/full.md
    # 该文件由 MinerU 等文档解析器在预处理阶段生成
    full_md = Path(conf.vector_store_dir) / "uploads" / (ctx.partition or "") / "chunk_out" / stem / "full.md"

    try:
        # resolve() 解析符号链接和相对路径为绝对路径
        resolved = full_md.resolve()
        # 路径穿越防护: 验证解析后的路径在允许的基目录下
        resolved.relative_to(Path(conf.vector_store_dir).resolve() / "uploads")
    except (ValueError, OSError):
        return f"(文件路径非法: {filename})"

    if not resolved.is_file():
        logger.warning(f"tool read_full_document 未找到: {resolved}")
        return f"(未找到 {filename} 的全文, 可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
        logger.info(f"tool read_full_document 成功: {filename} ({len(content)} 字符)")
        # 截断安全性: 全文超过 30000 字符时截断并附加提示
        if len(content) > 30000:
            content = content[:30000] + "\n\n...(全文过长，已截取前 30000 字符)..."
        return content
    except Exception as e:
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"



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
    query = (args.get("query") or "").strip()
    if not query:
        return "(未提供搜索 query)"
    # 限制结果数量在 1-10 之间，防止返回过多结果浪费上下文
    max_results = min(int(args.get("max_results", 5)), 10)

    logger.info(f"tool web_search query={query!r} max={max_results} backend={conf.search_backend}")

    # 自动增强时间语境: 检测 query 中是否包含 4 位年份，缺失则补当前年份
    # 使得搜索结果在跨年时仍有合理的时效性
    from datetime import datetime as _dt
    _now = _dt.now()
    if not __import__('re').search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query):
        query = f"{_now.year}年 {query}"
        logger.info(f"tool web_search 已补年份: {query!r}")

    # 根据配置选择搜索引擎后端
    backend = conf.search_backend or "duckduckgo"
    if backend == "searxng":
        results = _search_searxng(query, max_results)
    elif backend == "bocha":
        results = _search_bocha(query, max_results)
    elif backend == "bing":
        results = _search_bing(query, max_results)
    else:
        results = _search_duckduckgo(query, max_results)
    # 搜索不可用（如网络异常、API Key 未配置）时返回明确提示，避免进入重试死循环
    if results is None:
        return "(联网搜索暂时不可用，请直接回答，不要重试。)"
    if not results:
        return "(未找到相关搜索结果)"

    # 格式化为 LLM 易读的文本（编号 + 标题 + 摘要 + URL）
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()
        url = r.get("href", "").strip()
        lines.append(f"[搜索结果 {i}] {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    output = "\n".join(lines).strip()
    logger.info(f"tool web_search 返回 {len(results)} 条结果, 长度={len(output)}")
    return output


def _search_duckduckgo(query: str, max_results: int) -> list | None:
    """
    后端 1: DuckDuckGo 搜索
    特点: 无需 API Key，免费，但国内访问需要 VPN。
    优先尝试新版 ddgs 库，回退到旧版 duckduckgo_search 库。
    返回 None 表示不可用（库未安装或网络异常）。
    """
    try:
        from ddgs import DDGS
        timeout = int(conf.search_timeout or 10)
        return list(DDGS(timeout=timeout).text(query, max_results=max_results))
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return list(DDGS().text(query, max_results=max_results))
        except ImportError:
            logger.warning("[tool] duckduckgo_search 库未安装")
            return None
    except Exception as e:
        logger.warning(f"tool duckduckgo 搜索失败: {e}")
        return None


def _search_searxng(query: str, max_results: int) -> list | None:
    """
    后端 2: SearXNG 搜索
    特点: 开源的元搜索引擎，通过自建或公开实例使用，国内可直连。
    需在配置中设置 searxng_url（实例地址），否则返回 None。
    通过 REST JSON API 获取结果。
    """
    base_url = (conf.searxng_url or "").rstrip("/")
    if not base_url:
        logger.warning("[tool] searxng_url 未配置")
        return None

    import urllib.parse as _up
    try:
        import requests as _req
        params = {"q": query, "format": "json", "language": "zh-CN"}
        resp = _req.get(
            f"{base_url}/search",
            params=params,
            timeout=conf.search_timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"tool SearXNG 搜索失败: {e}")
        return None

    results = data.get("results", [])
    out = []
    for r in results[:max_results]:
        out.append({
            "title": r.get("title", ""),
            "body": r.get("content", ""),
            "href": r.get("url", ""),
        })
    return out


def _search_bocha(query: str, max_results: int) -> list | None:
    """
    后端 3: 博查 AI Search API
    特点: 国内可用，无需 VPN，但需要配置 bocha_api_key。
    调用博查 Web Search API（POST JSON 格式），
    兼容多种可能的响应路径（webPages / items / results / data 字段）。
    """
    api_key = conf.bocha_api_key
    if not api_key:
        logger.warning("[tool] bocha_api_key 未配置")
        return None

    try:
        import requests as _req

        # 博查 Web Search API — 支持 POST JSON
        resp = _req.post(
            "https://api.bochaai.com/v1/web-search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "count": max_results,
                "summary": True,
                "freshness": "noLimit",
            },
            timeout=conf.search_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"tool Bocha 搜索失败: {e}")
        return None

    # 尝试多种可能的响应路径
    raw = data.get("data") or data
    items = (
        raw.get("webPages", {}).get("value")
        or raw.get("items")
        or raw.get("results")
        or raw.get("data")
    )
    if not items or not isinstance(items, list):
        logger.warning(f"tool Bocha 返回格式异常: {str(data)[:300]}")
        return None

    out = []
    for r in items[:max_results]:
        out.append({
            "title": r.get("name") or r.get("title") or "",
            "body": r.get("snippet") or r.get("content") or r.get("summary") or "",
            "href": r.get("url") or r.get("link") or "",
        })
    return out


def _search_bing(query: str, max_results: int) -> list | None:
    """
    后端 4: Bing Web Search API v7
    特点: 微软 Azure 服务，国内可用，需配置 bing_api_key。
    通过 GET 请求调用 official Bing API，返回结构化搜索结果。
    """
    api_key = conf.bing_api_key
    if not api_key:
        logger.warning("[tool] bing_api_key 未配置")
        return None

    try:
        import requests as _req

        resp = _req.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={
                "q": query,
                "count": max_results,
                "mkt": "zh-CN",
            },
            timeout=conf.search_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"tool Bing 搜索失败: {e}")
        return None

    pages = data.get("webPages") or {}
    items = pages.get("value") or []
    out = []
    for r in items[:max_results]:
        out.append({
            "title": r.get("name", ""),
            "body": r.get("snippet", ""),
            "href": r.get("url", ""),
        })
    return out


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
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (args.get("pattern") or "").strip().lower()
    list_system = args.get("list_system", True)

    logger.info(f"tool list_documents pattern={pattern!r} list_system={list_system} partition={ctx.partition}")

    # 获取当前用户分区的文档列表
    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []

    # 合并系统分区的文档（如果 list_system=true）
    docs = []
    for d in user_docs:
        docs.append(f"📄 {d}")

    if list_system:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        for d in system_docs:
            label = f"📖 {d}"
            if label not in docs:              # 避免同名文档重复列出
                docs.append(label)

    # 可选关键词过滤
    if pattern:
        docs = [d for d in docs if pattern in d.lower()]

    if not docs:
        return "(当前没有匹配的文档)"

    lines = [f"- {d}" for d in sorted(docs)]
    return "当前知识库中的文档：\n" + "\n".join(lines)


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
    archive_id = (args.get("archive_id") or "").strip()
    if not archive_id:
        return "(未提供 archive_id 参数)"
    if not ctx.data_store:
        return "(归档存储不可用)"

    try:
        result = ctx.data_store.format_archive_turns(archive_id)
        if result is None:
            return f"(归档 {archive_id} 不存在)"
        logger.info(f"tool read_archive 成功: {archive_id} ({len(result)} 字符)")
        return result
    except Exception as e:
        logger.warning(f"tool read_archive 失败 ({archive_id}): {e}")
        return f"(读取归档失败: {e})"


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
    question = args.get("question", "需要您提供更多信息。")
    logger.info(f"tool ask_user_for_clarification: LLM 请求澄清: {question}")
    return question


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
    url = (args.get("url") or "").strip()
    if not url:
        return "(未提供 URL 参数)"

    logger.info(f"tool read_url: 开始抓取 {url}")
    try:
        import requests as _req
        resp = _req.get(
            url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        resp.raise_for_status()

        # 用 stdlib 的 HTMLParser 提取纯文本
        from html.parser import HTMLParser as _HTMLParser

        class _TextExtractor(_HTMLParser):
            def __init__(self):
                super().__init__()
                self._text = []
                self._skip = False  # 跳过 script/style 块

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False
                if tag in ("p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div"):
                    self._text.append("\n")

            def handle_data(self, data):
                if not self._skip:
                    self._text.append(data.strip())

            def get_text(self):
                return "".join(self._text)

        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()

        # 压缩多余空行
        import re as _re
        text = _re.sub(r"\n{3,}", "\n\n", text).strip()

        # 截断防止上下文溢出
        if len(text) > 20000:
            text = text[:20000] + "\n\n...(网页内容过长，已截取前 20000 字符)..."

        logger.info(f"tool read_url 成功: {url} ({len(text)} 字符)")
        return text

    except Exception as e:
        logger.warning(f"tool read_url 失败 ({url}): {e}")
        return f"(读取网页失败: {e})"


# ─── 注册内建工具 ───────────────────────────────────
# 以下通过 registry.register() 注册所有内建工具。
# 每个注册包含:
#   - name:        工具名（LLM function calling 中使用的标识符）
#   - description: 工具描述（作为 system prompt 的一部分，引导 LLM 何时调用）
#   - parameters:  JSON Schema 格式的参数声明（LLM 据此生成合法参数）
#   - handler:     实际执行函数 (args, ctx) -> str
#   - source:      注册来源（模块名，用于调试）
# 注册完成后，外部通过 registry.dispatch(name, args_json, ctx) 调用。

# --- 工具 1: ask_user_for_clarification ---
# 虚拟工具，用于请求用户澄清。
# 外部 agent 循环会截获此工具调用，不执行 handler，直接向用户展示 question。
registry.register(
    name="ask_user_for_clarification",
    description=(
        "当用户的请求非常模糊（如未指定具体文档、指代不清）且你无法通过已有的检索结果自行推理出正确答案时调用此工具。"
        "调用此工具后，对话会立即中断并将你设置的 question 抛给用户等待补充。"
        "除非别无他法，否则请尽量利用知识库和其他工具完成任务。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "你需要向用户询问的具体问题，比如'请问您指的是本季度的哪一份财报？'",
            },
        },
        "required": ["question"],
    },
    handler=_exec_ask_clarification,
    source=__name__,
)

# --- 工具 2: search_knowledge_base ---
# 知识库检索工具，支持多 query 并行检索 + 多分区 + 去重合并。
# LLM 通过 queries 参数传入检索语句列表，search_system 控制是否同时搜索系统文档。
registry.register(
    name="search_knowledge_base",
    description=(
        "在用户的知识库中检索与问题相关的文档片段。当问题涉及具体文档内容"
        "(报告、表格、专业数据、上传过的文件中提到的事实) 时调用; 闲聊 / 问候 / "
        "通用常识问题不要调用。可一次性传入多个 query 做并行检索。"
        "知识库包含用户私有文档和系统公开文档。"
        "如需只搜索用户自己的文档、排除系统数据，请设置 search_system=false。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
                "description": (
                    "用于向量检索的查询列表。简单问题 1 个; "
                    "对比类 / 多焦点 / 多条件问题拆成 2-5 个独立子查询。"
                    "查询用名词短语或简洁的检索语句, 而不是完整问句; "
                    "用户说'那份报告'之类时应用文档清单里的实际文件名替换。"
                ),
            },
            "search_system": {
                "type": "boolean",
                "description": "是否同时搜索系统公开文档。默认为 true（搜索全部）。设为 false 则只搜索用户自己的文档。",
                "default": True,
            },
        },
        "required": ["queries"],
    },
    handler=_exec_search_kb,
    source=__name__,
)

# --- 工具 3: read_full_document ---
# 读取完整文档全文，支持 MinerU 解析后的 Markdown 格式。
# 含路径穿越防护（resolve + relative_to 双重校验）和 30000 字符截断保护。
registry.register(
    name="read_full_document",
    description=(
        "读取用户上传的某一篇文档的完整全文内容（Markdown 格式）。"
        "当需要仔细阅读整篇文档（而非检索片段）、文档被用户明确点名要求阅读、"
        "或检索片段不足以回答问题时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": (
                    "要读取的文档文件名（含扩展名）。"
                    "必须是文档清单中出现的完整文件名，如 KD指标.pdf"
                ),
            }
        },
        "required": ["filename"],
    },
    handler=_exec_read_full_document,
    source=__name__,
)

# --- 工具 4: read_url ---
# URL 全文阅读工具，配合 web_search 使用。
# web_search 只返回摘要，LLM 可用此工具深入阅读整篇文章。
# 使用 requests 抓取 + stdlib HTMLParser 提取纯文本，无需额外依赖。
registry.register(
    name="read_url",
    description=(
        "读取指定网页的完整文字内容（纯文本格式）。"
        "当 web_search 找到了一篇看起来信息量很大的文章、"
        "或者用户给出了一个具体的网页链接时调用此工具阅读全文。"
        "注意：只能读取公开可访问的网页，不能读取登录后才能查看的页面。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要读取的网页完整 URL（必须以 http:// 或 https:// 开头）",
            },
        },
        "required": ["url"],
    },
    handler=_exec_read_url,
    source=__name__,
)

# --- 工具 5: web_search ---
# 互联网搜索工具，支持 duckduckgo / searxng / bocha / bing 四个后端。
# 自动为查询补充年份以增强时效性，max_results 上限为 10 条。
registry.register(
    name="web_search",
    description=(
        "在互联网上搜索最新的实时信息。当用户问到需要实时数据、最新新闻、"
        "当前事件、或知识库中不包含的时效性内容时调用。"
        "如果知识库中已经有相关内容，优先使用 search_knowledge_base。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，用名词短语或简洁问句。",
            },
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "返回结果数量（1-10）。",
            },
        },
        "required": ["query"],
    },
    handler=_exec_web_search,
    source=__name__,
)

# --- 工具 6: list_documents ---
# 列出知识库中文档，支持按关键词 pattern 过滤、按分区（用户/系统）区分。
# 用于 LLM 确认用户所指文档的完整文件名。
registry.register(
    name="list_documents",
    description=(
        "列出当前知识库中的文档（支持按文件名过滤）。"
        "知识库包含用户私有文档和系统公开文档，会分别标注 📄 和 📖。"
        "如需只列用户文档，请设置 list_system=false。"
        "当用户说「那份报告」「那个文档」需要确定具体文件名时调用，"
        "或者在搜索前确认知识库中有什么文档时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "可选的文件名关键词（如「KD」「财报」），不传则列出全部。",
            },
            "list_system": {
                "type": "boolean",
                "description": "是否同时列出系统公开文档。默认为 true（列出全部）。设为 false 则只列用户自己的文档。",
                "default": True,
            },
        },
        "required": [],
    },
    handler=_exec_list_documents,
    source=__name__,
)

# --- 工具 7: read_archive ---
# 读取归档对话历史的工具。当 system message 中包含 #[archive_id] 标记时，
# LLM 可调用此工具恢复被压缩的旧对话上下文。
registry.register(
    name="read_archive",
    description=(
        "读取被归档的历史对话记录。当 system message 中出现「历史摘要 #[archive_id]」标记时，"
        "可调用此工具获取该段历史的完整对话内容。每次调用读取一个归档。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "archive_id": {
                "type": "string",
                "description": "归档 ID，格式如 arch_xxx。从历史摘要标记 #[archive_id] 中提取。",
            },
        },
        "required": ["archive_id"],
    },
    handler=_exec_read_archive,
    source=__name__,
)


# ─── 向后兼容导出 ────────────────────────────────
# 为旧版 import (from agent.tools import TOOL_SCHEMAS, execute_tool) 提供兼容层。
# 新代码推荐: from agent.tools import registry
#   - registry.schemas       → 所有工具的 OpenAPI schema 列表
#   - registry.dispatch(...) → 根据工具名派发到对应 handler

TOOL_SCHEMAS = registry.schemas  # list[dict]，供旧版 function calling schema 构建用


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """
    向后兼容的 dispatch 函数。

    旧用法:
      execute_tool(name, args, vector_store=..., partition=...)
    新用法:
      registry.dispatch(name, args, ctx=ToolContext(vector_store=..., partition=...))

    这个包装函数自动从 kwargs 中提取所需字段构造 ToolContext。
    """
    from .registry import ToolContext
    ctx = ToolContext(
        vector_store=kwargs.get("vector_store"),
        partition=kwargs.get("partition"),
    )
    return registry.dispatch(name, args_json, ctx=ctx)


# ─── 内部辅助 ───────────────────────────────────


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
    if not queries:
        return []

    # 收集要搜索的所有分区（用户分区 + 系统分区）
    search_partitions = [partition] if partition else []
    if system_partitions:
        search_partitions.extend(sp for sp in system_partitions if sp and sp not in search_partitions)

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
                return vector_store.search(
                    query=queries[0], top_k=conf.retrieval_top_k,
                    partition=p,
                )
            except Exception as e:
                logger.error(f"检索失败 (query={queries[0]!r}, partition={p}): {e}")
                return []

        # 多 query: 公平分配，每 query 取 per_q 个，合并去重
        per_q = max(1, conf.candidate_top_k // len(queries))
        seen = set()
        merged: List[Document] = []
        for q in queries:
            try:
                results = vector_store.search(
                    query=q, top_k=conf.retrieval_top_k,
                    partition=p,
                )
            except Exception as e:
                logger.error(f"检索失败 (query={q!r}, partition={p}): {e}")
                continue
            # 每个 query 只取前 per_q 个，然后按 id 去重
            for c in results[:per_q]:
                key = c.metadata.get("id") or c.page_content
                if key in seen:
                    continue
                seen.add(key)
                merged.append(c)
        return merged

    # 跨分区合并: 对所有分区（用户分区 + 系统分区）分别检索，
    # 然后用全局 seen set 做二次去重，避免不同分区返回同一文档块。
    seen = set()
    merged: List[Document] = []
    for p in search_partitions:
        results = _search_partition(p)
        for c in results:
            key = c.metadata.get("id") or c.page_content
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)

    logger.info(f"多分区检索完成: partitions={search_partitions}, 合并后 {len(merged)} 块")
    return merged
