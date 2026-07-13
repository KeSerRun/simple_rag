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


def _resolve_full_md(filename: str, partition: str | None = None) -> str | None:
    """统一解析 full.md 文档路径，供多个工具共享。

    同时搜索用户分区和系统分区，含路径穿越防护。
    """
    stem = Path(filename).stem
    base = Path(conf.data_dir) / "uploads"
    candidates = [base / (partition or "") / "chunk_out" / stem / "full.md"]
    if partition and partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")
    for full_md in candidates:
        try:
            r = full_md.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                return str(r)
        except (ValueError, OSError):
            continue
    return None


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
    # LLM 控制返回结果数（默认使用配置值）
    top_k = int(args.get("top_k", conf.candidate_top_k))
    top_k = max(1, min(top_k, conf.retrieval_top_k))
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    logger.debug(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system} top_k={top_k}")

    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions)
    if not chunks:
        logger.debug("tool search_knowledge_base 未检索到相关内容, 返回 0 块")
        return "(知识库中未检索到相关内容)"

    # 截断到 top_k 个
    chunks = chunks[:top_k]

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


def _exec_read_full_document(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_full_document
    读取 MinerU 解析后的完整文档全文。支持 offset 分页（分页大小由配置决定）。
    """
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    resolved = _resolve_full_md(filename, ctx.partition)
    if resolved is None:
        logger.warning(f"tool read_full_document 未找到: {filename}")
        return f"(未找到 {filename} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = Path(resolved).read_text(encoding="utf-8")
        total = len(content)
        max_chars = conf.tool_page_chars
        offset = max(int(args.get("offset", 0)), 0)
        chunk = content[offset:offset + max_chars]
        part_info = ""
        if total > max_chars:
            end = offset + len(chunk)
            if end < total:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符。调用 offset={end} 继续阅读)"
            else:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符 — 已到末尾)"
        logger.debug(f"tool read_full_document 成功: {filename} ({len(chunk)} 字符)")
        return chunk + part_info
    except Exception as e:
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"


def _get_file_stats(filename: str, partition: str | None = None) -> dict:
    """获取文档文件的元信息（大小、修改时间、类型）。"""
    import datetime as _dt
    import mimetypes

    stats = {"size": "", "mtime": "", "type": ""}
    # 优先从 full.md 获取文件信息
    resolved = _resolve_full_md(filename, partition)
    if resolved:
        try:
            s = Path(resolved).stat()
            size = s.st_size
            if size < 1024:
                stats["size"] = f"{size}B"
            elif size < 1024 * 1024:
                stats["size"] = f"{size / 1024:.0f}KB"
            else:
                stats["size"] = f"{size / 1024 / 1024:.1f}MB"
            mtime = _dt.datetime.fromtimestamp(s.st_mtime).strftime("%m-%d %H:%M")
            stats["mtime"] = mtime
        except OSError:
            pass
    # 从扩展名判断类型
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        stats["type"] = "PDF"
    elif ext in (".docx", ".doc"):
        stats["type"] = "Word"
    elif ext in (".xlsx", ".xls"):
        stats["type"] = "Excel"
    elif ext in (".pptx", ".ppt"):
        stats["type"] = "PPT"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        stats["type"] = "Image"
    elif ext in (".md", ".markdown"):
        stats["type"] = "Markdown"
    elif ext in (".txt",):
        stats["type"] = "Text"
    elif ext:
        stats["type"] = ext[1:].upper()
    return stats


def _exec_list_documents(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: list_documents
    列出用户/系统分区的文档，支持关键词过滤。
    返回文档名、类型、大小、修改时间。
    """
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (args.get("pattern") or "").strip().lower()
    list_system = args.get("list_system", True)
    sort_by = args.get("sort_by", "name")  # name, time
    logger.debug(f"tool list_documents pattern={pattern!r} list_system={list_system} "
                 f"partition={ctx.partition} sort={sort_by}")

    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []
    doc_entries = []
    for d in user_docs:
        s = _get_file_stats(d, ctx.partition)
        doc_entries.append({"name": d, **s, "is_system": False})

    if list_system:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        seen = {d["name"] for d in doc_entries}
        for d in system_docs:
            if d not in seen:
                s = _get_file_stats(d, SYSTEM_PARTITION)
                doc_entries.append({"name": d, **s, "is_system": True})
                seen.add(d)

    if pattern:
        doc_entries = [d for d in doc_entries if pattern in d["name"].lower()]

    if not doc_entries:
        return "(当前没有匹配的文档)"

    # 排序
    if sort_by == "time":
        # 有 mtime 的排前面，按 mtime 降序；没有的放最后
        doc_entries.sort(key=lambda d: (not bool(d["mtime"]), d["mtime"]), reverse=True)
    else:
        doc_entries.sort(key=lambda d: d["name"].lower())

    lines = []
    for d in doc_entries:
        icon = "📖" if d["is_system"] else "📄"
        info = " | ".join(p for p in [d["type"], d["size"], d["mtime"]] if p)
        if info:
            lines.append(f"- {icon} {d['name']}  ({info})")
        else:
            lines.append(f"- {icon} {d['name']}")

    return "当前知识库中的文档：\n" + "\n".join(lines)


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


def _exec_read_document_titles(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_document_titles
    读取某篇文档的完整 Markdown 源文件，提取所有 Markdown 标题（# 开头）。
    返回文档的标题目录结构。配合 read_section 使用。
    """
    source = (args.get("source") or "").strip()
    if not source:
        return "(未提供 source 参数)"

    resolved = _resolve_full_md(source, ctx.partition)
    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = Path(resolved).read_text(encoding="utf-8")
    except Exception as e:
        return f"(读取 {source} 失败: {e})"

    # 提取所有 Markdown 标题行
    lines = content.splitlines()
    headings = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
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

    # 1. 定位 full.md 源文件
    resolved = _resolve_full_md(source, ctx.partition)
    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = Path(resolved).read_text(encoding="utf-8")
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
    if len(section_text) > 30000:
        section_text = section_text[:30000] + "\n\n...(已截断)"

    logger.debug(
        f"tool read_section 成功: {source} / {match_text} "
        f"({len(section_lines)} 行, {len(section_text)} 字符)"
    )
    return section_text


def _exec_search_document_content(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: search_document_content
    在文档的全文（full.md）中搜索关键词，返回匹配的文档名和上下文片段。
    类似 grep，但针对知识库文档。
    """
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return "(未提供 keyword 参数)"
    source_filter = (args.get("source") or "").strip().lower()
    max_results = min(int(args.get("max_results", 10)), 50)

    logger.debug(f"tool search_document_content keyword={keyword!r} source={source_filter!r}")

    if not ctx.vector_store:
        return "(知识库不可用)"

    partitions = [ctx.partition] if ctx.partition else []
    try:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
    except Exception:
        system_docs = []

    if source_filter == "__system__":
        doc_names = system_docs
    elif source_filter:
        # 搜索指定文档（可能在任一分区）
        doc_names = [source_filter]
    else:
        user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []
        doc_names = list(dict.fromkeys(user_docs + system_docs))

    keyword_lower = keyword.lower()
    matches = []

    for doc in doc_names:
        # 如果指定了 source_filter（非系统分区），快速过滤
        resolved = _resolve_full_md(doc, ctx.partition)
        if not resolved:
            # 尝试系统分区
            resolved = _resolve_full_md(doc, SYSTEM_PARTITION) if ctx.partition else _resolve_full_md(doc, None)
        if not resolved:
            continue

        try:
            content = Path(resolved).read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.splitlines()
        doc_matches = []
        for i, line in enumerate(lines, 1):
            if keyword_lower in line.lower():
                # 提取前后少量上下文
                snippet = line.strip()[:200]
                doc_matches.append((i, snippet))

        if doc_matches:
            matches.append((doc, doc_matches))

        if sum(len(m[1]) for m in matches) >= max_results:
            break

    if not matches:
        return f"(未找到包含「{keyword}」的文档)"

    # 限制总结果数
    total = 0
    output_lines = [f"搜索「{keyword}」结果："]
    for doc, doc_matches in matches:
        output_lines.append(f"\n📄 {doc}（{len(doc_matches)} 处匹配）")
        for line_no, snippet in doc_matches:
            if total >= max_results:
                break
            output_lines.append(f"  L{line_no}: {snippet}")
            total += 1
        if total >= max_results:
            if len(matches) > 1 or len(matches[0][1]) > max_results:
                output_lines.append(f"\n...(仅显示前 {max_results} 个匹配)")
            break

    return "\n".join(output_lines)
