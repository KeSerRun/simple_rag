"""KB 工具 handlers: 知识库检索 / 读全文 / 列文档 / 读归档。
注册统一在 registry.py 的 register_all_builtins() 中。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from base.config import conf
from base.logger import logger
from rag.vector_store import Document

from .registry import ToolContext
def _resolve_document_path(filename: str, partition: str | None = None, search_system: bool = True) -> str | None:
    """统一的文档路径解析（路径穿越防护）。"""
    stem = Path(filename).stem
    base = Path(conf.data_dir) / "uploads"
    candidates = [base / (partition or "") / "chunk_out" / stem]
    if search_system and partition and partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem)
    for path in candidates:
        try:
            r = path.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                return str(r)
        except (ValueError, OSError):
            continue
    return None

from ._format import SYSTEM_PARTITION, format_retrieved_chunks


# ===== search_knowledge_base =====
def _exec_search_kb(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: search_knowledge_base
    多 query + 多分区 + 去重。
    """
    queries = args.get("queries") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(q).strip() for q in queries if str(q).strip()]
    if not queries:
        logger.warning("tool search_knowledge_base 被调用但未提供有效 query")
        return "(未提供任何检索 query)"

    search_system = args.get("search_system", True)
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    logger.debug(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system}")

    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions)
    if not chunks:
        logger.debug("tool search_knowledge_base 未检索到相关内容, 返回 0 块")
        return "(知识库中未检索到相关内容)"

    # 直接截断到 candidate_top_k 个
    chunks = chunks[: conf.candidate_top_k]

    # 日志记录
    for ci, c in enumerate(chunks):
        meta = c.metadata or {}
        logger.debug(
            f"检索块 {ci+1}/{len(chunks)}] source={meta.get('source','')!r} "
            f"type={meta.get('chunk_type','')!r} section={meta.get('section_path',[])} "
            f"page={meta.get('page')} caption={meta.get('caption','')!r} "
            f"img={meta.get('img_path','')!r} len={len(c.page_content)}"
        )
        preview = c.page_content[:200].replace("\n", " ")
        logger.debug(f"检索块 {ci+1} 内容] {preview}")

    formatted = format_retrieved_chunks(chunks)
    logger.debug(f"tool search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted


# ===== read_full_document =====
def _exec_read_full_document(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_full_document
    读取 MinerU 解析后的完整文档全文（路径穿越防护 + 30000 字符截断）。
    """
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    stem = Path(filename).stem
    base = Path(conf.data_dir) / "uploads"
    candidates = [
        base / (ctx.partition or "") / "chunk_out" / stem / "full.md",
    ]
    if ctx.partition and ctx.partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")

    resolved = None
    for full_md in candidates:
        try:
            r = full_md.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                resolved = r
                break
        except (ValueError, OSError):
            continue

    if resolved is None:
        logger.warning(f"tool read_full_document 未找到: {filename}")
        return f"(未找到 {filename} 的全文, 可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
        logger.debug(f"tool read_full_document 成功: {filename} ({len(content)} 字符)")
        if len(content) > 30000:
            content = content[:30000] + "\n\n...(全文过长，已截取前 30000 字符)..."
        return content
    except Exception as e:
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"


# ===== list_documents =====
def _exec_list_documents(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: list_documents
    列出用户/系统分区的文档，支持关键词过滤。
    """
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (args.get("pattern") or "").strip().lower()
    list_system = args.get("list_system", True)
    logger.debug(f"tool list_documents pattern={pattern!r} list_system={list_system} partition={ctx.partition}")

    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []
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


# ===== read_archive =====
def _exec_read_archive(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_archive
    读取被归档的历史对话记录。
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
        logger.debug(f"tool read_archive 成功: {archive_id} ({len(result)} 字符)")
        return result
    except Exception as e:
        logger.warning(f"tool read_archive 失败 ({archive_id}): {e}")
        return f"(读取归档失败: {e})"


# ===== 核心检索去重函数 =====
def _retrieve_and_dedup(
    vector_store, queries, partition, system_partitions: Optional[list] = None,
) -> List[Document]:
    """
    多 query + 多分区 + 全局去重检索。

    单 query 快速路径 / 多 query 公平分配 + chunk id/page_content 去重
    + 跨分区二次去重。
    """
    if not queries:
        return []

    search_partitions = [partition] if partition else []
    if system_partitions:
        search_partitions.extend(sp for sp in system_partitions if sp and sp not in search_partitions)

    def _search_partition(p):
        if len(queries) == 1:
            try:
                return vector_store.search(
                    query=queries[0], top_k=conf.retrieval_top_k, partition=p,
                )
            except Exception as e:
                logger.error(f"检索失败 (query={queries[0]!r}, partition={p}): {e}")
                return []

        per_q = max(1, conf.retrieval_top_k // len(queries))
        seen = set()
        merged: List[Document] = []
        for q in queries:
            try:
                results = vector_store.search(query=q, top_k=conf.retrieval_top_k, partition=p)
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

    logger.debug(f"多分区检索完成: partitions={search_partitions}, 合并后 {len(merged)} 块")
    return merged


# ===== read_chunk_context =====
def _exec_read_chunk_context(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_chunk_context
    根据 chunk ID 读取其前后相邻的文档块（按页面顺序），提供上下文。
    当 search_knowledge_base 返回的某个片段需要更多上下文时使用此工具，
    避免多次调用 search_knowledge_base。
    """
    chunk_id = (args.get("chunk_id") or "").strip()
    before = args.get("before", 3)
    after = args.get("after", 3)
    # 限制范围
    before = min(max(int(before), 0), 10)
    after = min(max(int(after), 0), 10)

    if not chunk_id:
        return "(未提供 chunk_id 参数)"

    if not ctx.vector_store:
        return "(知识库不可用)"

    meta_list = getattr(ctx.vector_store, "metadata", None)
    if not meta_list:
        return "(元数据不可用)"

    # 1. 查找目标 chunk（[id=] 只显示前 8 位，用前缀匹配）
    target_meta = None
    for m in meta_list:
        if str(m.get("id", "")).startswith(chunk_id):
            target_meta = m
            break
    if target_meta is None:
        return f"(未找到 chunk_id={chunk_id})"

    # 2. 获取同源文档的所有块，按 page 排序
    source = target_meta.get("source", "")
    partition = target_meta.get("partition", "")
    siblings = [
        m for m in meta_list
        if m.get("source") == source and m.get("partition") == partition
    ]
    # 按 page → 元数据列表原始顺序 稳定排序
    siblings.sort(key=lambda m: (m.get("page") or 0))

    # 3. 在排序列表中定位目标（前缀匹配，因为 [id=] 只显示前 8 位）
    target_idx = None
    for i, m in enumerate(siblings):
        if str(m.get("id", "")).startswith(chunk_id):
            target_idx = i
            break
    if target_idx is None:
        # 同源同分区找不到（理论上不会发生）
        return f"(chunk_id={chunk_id} 定位失败)"

    # 4. 截取范围
    start = max(0, target_idx - before)
    end = min(len(siblings), target_idx + after + 1)
    selected = siblings[start:end]

    # 5. 格式化输出
    lines = []
    for m in selected:
        tag = "【目标】" if str(m.get("id", "")).startswith(chunk_id) else ""
        page_info = f" [第{m['page']}页]" if m.get("page") else ""
        lines.append(f"--- {tag}源:{m['source']}{page_info} ---")
        text = m.get("text", "")
        if len(text) > 500:
            text = text[:500] + "...(已截断)"
        lines.append(text)
        lines.append("")

    if not lines:
        return "(未获取到上下文)"

    output = "\n".join(lines)
    logger.debug(
        f"tool read_chunk_context 成功: "
        f"id={chunk_id[:12]} source={source} "
        f"range={start}-{end-1}/{len(siblings)} "
        f"({len(selected)}块)"
    )
    return output


# ===== read_document_titles =====
def _exec_read_document_titles(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_document_titles
    读取某篇文档的完整 Markdown 源文件，提取所有 Markdown 标题（# 开头）。
    返回文档的标题目录结构。配合 read_section 使用。
    """
    source = (args.get("source") or "").strip()
    if not source:
        return "(未提供 source 参数)"

    stem = Path(source).stem
    base = Path(conf.data_dir) / "uploads"
    candidates = [
        base / (ctx.partition or "") / "chunk_out" / stem / "full.md",
    ]
    if ctx.partition and ctx.partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")

    resolved = None
    for full_md in candidates:
        try:
            r = full_md.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                resolved = r
                break
        except (ValueError, OSError):
            continue

    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"(读取 {source} 失败: {e})"

    # 提取所有 Markdown 标题行
    lines = content.splitlines()
    headings = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # 计算标题级别（# 的个数）
            level = 0
            for ch in stripped:
                if ch == "#":
                    level += 1
                else:
                    break
            text = stripped[level:].strip()
            if text:
                headings.append((level, text))

    if not headings:
        return f"(文档 {source} 中未找到 Markdown 标题)"

    # 格式化为缩进树
    output_lines = [f"📖 {source} 的文档结构："]
    for level, text in headings:
        indent = "  " * (level - 1)
        output_lines.append(f"{indent}- {text}")

    output = "\n".join(output_lines)
    logger.debug(f"tool read_document_titles 成功: {source} ({len(headings)} 个标题)")
    return output


# ===== read_section =====
def _exec_read_section(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_section
    根据文档名和标题关键词，从 Markdown 源文件中定位该标题下的正文内容。
    与 read_document_titles 使用同一数据源，匹配更准确。
    """
    source = (args.get("source") or "").strip()
    heading = (args.get("heading") or "").strip()
    if not source:
        return "(未提供 source 参数)"
    if not heading:
        return "(未提供 heading 参数)"

    # 1. 定位 full.md 源文件（与 read_document_titles / read_full_document 逻辑一致）
    stem = Path(source).stem
    base = Path(conf.data_dir) / "uploads"
    candidates = [
        base / (ctx.partition or "") / "chunk_out" / stem / "full.md",
    ]
    if ctx.partition and ctx.partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")

    resolved = None
    for full_md in candidates:
        try:
            r = full_md.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                resolved = r
                break
        except (ValueError, OSError):
            continue

    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"(读取 {source} 失败: {e})"

    # 2. 按 Markdown 标题分割内容
    lines = content.splitlines()
    # 找到所有标题行及其位置
    heading_positions = []  # [(line_index, level, text), ...]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = 0
            for ch in stripped:
                if ch == "#":
                    level += 1
                else:
                    break
            text = stripped[level:].strip()
            if text:
                heading_positions.append((i, level, text))

    if not heading_positions:
        return f"(文档 {source} 中未找到 Markdown 标题)"

    # 3. 模糊匹配标题
    heading_lower = heading.lower()
    best_match = None
    best_score = 0
    for idx, (line_idx, level, text) in enumerate(heading_positions):
        text_lower = text.lower()
        # 计算匹配得分：完全包含得分最高，部分包含次之
        if heading_lower in text_lower:
            score = len(heading) / len(text) if text else 0
            if score > best_score:
                best_score = score
                best_match = idx

    if best_match is None:
        # 尝试反向：标题文本是否包含关键词（更宽松）
        for idx, (line_idx, level, text) in enumerate(heading_positions):
            text_lower = text.lower()
            for kw in heading_lower.split():
                if len(kw) > 1 and kw in text_lower:
                    if best_match is None:
                        best_match = idx
                    break

    if best_match is None:
        return f"(未找到匹配标题「{heading}」的内容)"

    # 4. 提取该标题到下一个同级/上级标题之间的内容
    match_line, match_level, match_text = heading_positions[best_match]
    next_start = None
    for j in range(best_match + 1, len(heading_positions)):
        if heading_positions[j][1] <= match_level:
            next_start = heading_positions[j][0]
            break

    section_lines = lines[match_line:next_start]
    # 去掉首尾空行
    while section_lines and not section_lines[0].strip():
        section_lines = section_lines[1:]
    while section_lines and not section_lines[-1].strip():
        section_lines = section_lines[:-1]

    section_text = "\n".join(section_lines)

    # 限制输出长度
    if len(section_text) > 15000:
        section_text = section_text[:15000] + "\n\n...(已截断)"

    logger.debug(
        f"tool read_section 成功: {source} / {match_text} "
        f"({len(section_lines)} 行, {len(section_text)} 字符)"
    )
    return section_text
