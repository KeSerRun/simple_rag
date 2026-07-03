"""Agent tools: 内建工具通过 registry 注册 + 检索结果格式化。

每个 handler 接收 (args: dict, ctx: ToolContext) -> str。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from base.config import conf
from base.logger import logger

from rag.core.document_process import Document

from .registry import ToolContext, ToolRegistry

# 系统级数据分区名（对所有用户可见）
SYSTEM_PARTITION = "__system__"

# ─── 全局注册中心 ────────────────────────────────

registry = ToolRegistry()

# ─── 检索结果格式化 ──────────────────────────────


def _format_chunk(idx: int, chunk: Document) -> str:
    meta = chunk.metadata or {}
    parts = []
    source = (meta.get("source") or "").strip()
    if source:
        parts.append(f"**{source}**")
    section_path = meta.get("section_path") or []
    if section_path:
        parts.append(" > ".join(s for s in section_path if s))
    page = meta.get("page")
    if page is not None:
        parts.append(f"p.{page}")
    chunk_type = (meta.get("chunk_type") or "").strip()
    if chunk_type and chunk_type != "text":
        parts.append(chunk_type)
    # 标注来源分区
    partition = (meta.get("partition") or "").strip()
    if partition == SYSTEM_PARTITION:
        parts.append("📖 系统文档")
    elif partition:
        parts.append("📄 用户文档")
    header = f"【片段 {idx} | {' | '.join(parts)}】" if parts else f"【片段 {idx}】"
    body = chunk.page_content.strip()
    img_path = (meta.get("img_path") or "").strip()
    if img_path and chunk_type in ("image", "chart") and source:
        stem = Path(source).stem
        img_md = f"\n\n![图](/api/documents/image/{stem}/{img_path})"
        return f"{header}\n{body}{img_md}"
    return f"{header}\n{body}"


def format_retrieved_chunks(chunks: List[Document]) -> str:
    if not chunks:
        return ""
    return "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))


# ─── 工具 handers ────────────────────────────────


def _exec_search_kb(args: dict, ctx: ToolContext) -> str:
    queries = args.get("queries") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(q).strip() for q in queries if str(q).strip()]
    if not queries:
        logger.warning("tool search_knowledge_base 被调用但未提供有效 query")
        return "(未提供任何检索 query)"

    search_system = args.get("search_system", True)
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    logger.info(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system}")
    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions)
    if not chunks:
        logger.info("tool search_knowledge_base 未检索到相关内容, 返回 0 块")
        return "(知识库中未检索到相关内容)"

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
    formatted = format_retrieved_chunks(chunks)
    logger.info(f"tool search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted


def _exec_read_full_document(args: dict, ctx: ToolContext) -> str:
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    stem = Path(filename).stem
    full_md = Path(conf.vector_store_dir) / "uploads" / (ctx.partition or "") / "chunk_out" / stem / "full.md"

    try:
        resolved = full_md.resolve()
        resolved.relative_to(Path(conf.vector_store_dir).resolve() / "uploads")
    except (ValueError, OSError):
        return f"(文件路径非法: {filename})"

    if not resolved.is_file():
        logger.warning(f"tool read_full_document 未找到: {resolved}")
        return f"(未找到 {filename} 的全文, 可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
        logger.info(f"tool read_full_document 成功: {filename} ({len(content)} 字符)")
        if len(content) > 30000:
            content = content[:30000] + "\n\n...(全文过长，已截取前 30000 字符)..."
        return content
    except Exception as e:
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"



def _exec_web_search(args: dict, ctx: ToolContext) -> str:
    """搜索互联网，支持多后端 (duckduckgo / searxng)。"""
    query = (args.get("query") or "").strip()
    if not query:
        return "(未提供搜索 query)"
    max_results = min(int(args.get("max_results", 5)), 10)

    logger.info(f"tool web_search query={query!r} max={max_results} backend={conf.search_backend}")

    # 自动增强时间语境
    from datetime import datetime as _dt
    _now = _dt.now()
    if not __import__('re').search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query):
        query = f"{_now.year}年 {query}"
        logger.info(f"tool web_search 已补年份: {query!r}")

    backend = conf.search_backend or "duckduckgo"
    if backend == "searxng":
        results = _search_searxng(query, max_results)
    else:
        results = _search_duckduckgo(query, max_results)
    if results is None:
        return "(联网搜索暂时不可用，请直接回答，不要重试。)"
    if not results:
        return "(未找到相关搜索结果)"

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
    """通过 DuckDuckGo 搜索。"""
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
    """通过 SearXNG 实例搜索（国内可用，需自建或找公开实例）。"""
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


def _exec_list_documents(args: dict, ctx: ToolContext) -> str:
    """列出当前知识库中的文档，支持按文件名过滤。"""
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (args.get("pattern") or "").strip().lower()
    list_system = args.get("list_system", True)

    # 获取用户分区的文档
    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []

    # 合并系统分区的文档
    docs = []
    for d in user_docs:
        docs.append(f"📄 {d}")

    if list_system:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        for d in system_docs:
            label = f"📖 {d}"
            if label not in docs:
                docs.append(label)

    if pattern:
        docs = [d for d in docs if pattern in d.lower()]

    if not docs:
        return "(当前没有匹配的文档)"

    lines = [f"- {d}" for d in sorted(docs)]
    return "当前知识库中的文档：\n" + "\n".join(lines)


def _exec_read_archive(args: dict, ctx: ToolContext) -> str:
    """读取归档的历史对话记录。"""
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


# ─── 注册内建工具 ───────────────────────────────────

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
# 老代码：from agent.tools import TOOL_SCHEMAS, execute_tool
# 新代码：from agent.tools import registry

TOOL_SCHEMAS = registry.schemas  # list[dict]


def execute_tool(name: str, args_json: str, **kwargs) -> str:
    """向后兼容的 dispatch 函数。

    旧: execute_tool(name, args, vector_store=..., partition=...)
    新: registry.dispatch(name, args, ctx=ToolContext(...))

    这个包装自动从 kwargs 构造 ToolContext。
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
    if not queries:
        return []

    # 收集要搜索的所有分区（用户分区 + 系统分区）
    search_partitions = [partition] if partition else []
    if system_partitions:
        search_partitions.extend(sp for sp in system_partitions if sp and sp not in search_partitions)

    def _search_partition(p):
        """在单个分区中检索并返回去重后的父块列表。"""
        if len(queries) == 1:
            try:
                return vector_store.search(
                    query=queries[0], top_k=conf.retrieval_top_k,
                    partition=p,
                )
            except Exception as e:
                logger.error(f"检索失败 (query={queries[0]!r}, partition={p}): {e}")
                return []

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
            for c in results[:per_q]:
                key = c.metadata.get("id") or c.page_content
                if key in seen:
                    continue
                seen.add(key)
                merged.append(c)
        return merged

    # 对所有分区分别检索，合并结果
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
