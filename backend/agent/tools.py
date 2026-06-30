"""Agent tools: LLM function-calling 工具 + 检索结果格式化器。

- TOOL_SCHEMAS: 注册给 LLM 的工具列表
- execute_tool: 按 name dispatch, 返回字符串结果
- format_retrieved_chunks: 把检索结果序列化为 LLM 上下文字符串 (每块带元数据头)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from base.config import conf
from base.logger import logger

from rag.core.document import Document
from rag.core.local_vector_store import VectorStore


# ─── 工具 schema ──────────────────────────────────────────────────

SEARCH_KNOWLEDGE_BASE = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "在用户的知识库中检索与问题相关的文档片段。当问题涉及具体文档内容"
            "(报告、表格、专业数据、上传过的文件中提到的事实) 时调用; 闲聊 / 问候 / "
            "通用常识问题不要调用。可一次性传入多个 query 做并行检索。"
        ),
        "parameters": {
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
                }
            },
            "required": ["queries"],
        },
    },
}

READ_FULL_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "read_full_document",
        "description": (
            "读取用户上传的某一篇文档的完整全文内容（Markdown 格式）。"
            "当需要仔细阅读整篇文档（而非检索片段）、文档被用户明确点名要求阅读、"
            "或检索片段不足以回答问题时调用。"
        ),
        "parameters": {
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
    },
}

TOOL_SCHEMAS: List[dict] = [SEARCH_KNOWLEDGE_BASE, READ_FULL_DOCUMENT]


# ─── 检索结果格式化 (原 rag_system._format_chunk + format_retrieved_chunks) ──


def _format_chunk(idx: int, chunk: Document) -> str:
    """把检索块格式化为带元数据的 LLM 上下文片段。"""
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

    header = f"【片段 {idx} | {' | '.join(parts)}】" if parts else f"【片段 {idx}】"
    body = chunk.page_content.strip()

    # 图片 / 图表块附加内嵌图片
    img_path = (meta.get("img_path") or "").strip()
    if img_path and chunk_type in ("image", "chart") and source:
        stem = Path(source).stem
        img_md = f"\n\n![图](/api/documents/image/{stem}/{img_path})"
        return f"{header}\n{body}{img_md}"

    return f"{header}\n{body}"


def format_retrieved_chunks(chunks: List[Document]) -> str:
    """把召回结果序列化为单个上下文字符串, 每块带元数据头, 块间空行分隔。"""
    if not chunks:
        return ""
    return "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))


# ─── Executors ──────────────────────────────────────────────────────


def _retrieve_and_dedup(
    vector_store: VectorStore,
    queries: List[str],
    partition: Optional[str],
    source_filter: Optional[str],
) -> List[Document]:
    if not queries:
        return []
    if len(queries) == 1:
        try:
            return vector_store.search(
                query=queries[0], top_k=conf.retrieval_top_k,
                source_filter=source_filter, partition=partition,
            )
        except Exception as e:
            logger.error(f"检索失败 (query={queries[0]!r}): {e}")
            return []

    per_q = max(1, conf.candidate_top_k // len(queries))
    seen = set()
    merged: List[Document] = []
    for q in queries:
        try:
            results = vector_store.search(
                query=q, top_k=conf.retrieval_top_k,
                source_filter=source_filter, partition=partition,
            )
        except Exception as e:
            logger.error(f"检索失败 (query={q!r}): {e}")
            continue
        for c in results[:per_q]:
            key = c.metadata.get("id") or c.page_content
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def execute_tool(
    name: str,
    args_json: str,
    *,
    vector_store: VectorStore,
    partition: Optional[str] = None,
    source_filter: Optional[str] = None,
) -> str:
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        logger.warning(f"tool {name} 参数 JSON 解析失败 ({e}), raw={args_json!r}")
        return f"(工具调用失败: 参数 JSON 解析错误 {e})"

    if name == "search_knowledge_base":
        return _exec_search_kb(args, vector_store, partition, source_filter)
    elif name == "read_full_document":
        return _exec_read_full_document(args, partition)

    logger.warning(f"未知工具名: {name}")
    return f"(未知工具: {name})"


def _exec_search_kb(
    args: dict,
    vector_store: VectorStore,
    partition: Optional[str],
    source_filter: Optional[str],
) -> str:
    queries = args.get("queries") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(q).strip() for q in queries if str(q).strip()]
    if not queries:
        return "(未提供任何检索 query)"

    logger.info(f"[tool] search_knowledge_base queries={queries} partition={partition}")
    chunks = _retrieve_and_dedup(vector_store, queries, partition, source_filter)
    if not chunks:
        return "(知识库中未检索到相关内容)"

    # 逐块打印元数据 + 内容预览，方便排查检索质量
    for ci, c in enumerate(chunks):
        meta = c.metadata or {}
        logger.info(
            f"[检索块 {ci+1}/{len(chunks)}] "
            f"source={meta.get('source','')!r} "
            f"type={meta.get('chunk_type','')!r} "
            f"section={meta.get('section_path',[])} "
            f"page={meta.get('page')} "
            f"caption={meta.get('caption','')!r} "
            f"img={meta.get('img_path','')!r} "
            f"len={len(c.page_content)}"
        )
        # 内容预览前 200 字符
        preview = c.page_content[:200].replace("\n", " ")
        logger.info(f"[检索块 {ci+1} 内容] {preview}")
    formatted = format_retrieved_chunks(chunks)
    logger.info(f"[tool] search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted


def _exec_read_full_document(args: dict, partition: Optional[str]) -> str:
    """通过文件名找到 MinerU 产出的 full.md，返回全文内容。"""
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    stem = Path(filename).stem
    # 构造路径: {vector_store_dir}/tmp/{partition}/mineru_out/{stem}/full.md
    full_md = (
        Path(conf.vector_store_dir)
        / "tmp" / (partition or "")
        / "mineru_out" / stem
        / "full.md"
    )

    try:
        resolved = full_md.resolve()
        # 安全校验：必须在 tmp/ 目录下
        resolved.relative_to(Path(conf.vector_store_dir).resolve() / "tmp")
    except (ValueError, OSError):
        return f"(文件路径非法: {filename})"

    if not resolved.is_file():
        logger.warning(f"[tool] read_full_document 未找到: {resolved}")
        return f"(未找到 {filename} 的全文, 可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
        logger.info(f"[tool] read_full_document 成功: {filename} ({len(content)} 字符)")
        # 避免超出 token 上限，截取前 30000 字符
        if len(content) > 30000:
            content = content[:30000] + "\n\n...(全文过长，已截取前 30000 字符)..."
        return content
    except Exception as e:
        logger.warning(f"[tool] read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"
