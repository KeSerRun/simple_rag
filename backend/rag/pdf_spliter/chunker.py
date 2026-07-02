"""基于 MinerU content_list.json 的切块器"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def html_table_to_markdown(html: str) -> str:
    if BeautifulSoup is None:
        return html
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return html
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "| " + " | ".join(["---"] * width) + " |\n"
    for r in rows[1:]:
        md += "| " + " | ".join(r) + " |\n"
    return md.strip()


def _join(strs: Iterable[str] | None) -> str:
    if not strs:
        return ""
    return " ".join(s.strip() for s in strs if s and s.strip())


def chunk_content_list(content: list[dict], doc_meta: dict, max_chars: int = 1200, min_chars: int = 30) -> list[dict]:
    chunks: list[dict] = []
    section_path: list[str] = []
    text_buf: list[str] = []
    text_page: int | None = None

    def flush_text():
        nonlocal text_buf, text_page
        if not text_buf:
            return
        merged = "\n".join(text_buf).strip()
        text_buf = []
        if len(merged) < min_chars:
            text_page = None
            return
        for piece in _split_long(merged, max_chars):
            chunks.append({**doc_meta, "chunk_type": "text", "section_path": list(section_path), "page": (text_page or 0) + 1, "content": piece})
        text_page = None

    for el in content:
        t = el.get("type")
        page = el.get("page_idx", 0)
        if t == "text":
            text = (el.get("text") or "").strip()
            if not text:
                continue
            lvl = el.get("text_level", 0) or 0
            if lvl >= 1 and not re.match(r"^(图|表)\s*\d+[:：]", text):
                flush_text()
                section_path = section_path[: max(0, lvl - 1)] + [text]
            else:
                if text_page is None:
                    text_page = page
                text_buf.append(text)
        elif t == "equation":
            if text_page is None:
                text_page = page
            text_buf.append((el.get("text") or "").strip())
        elif t == "table":
            flush_text()
            md = html_table_to_markdown(el.get("table_body", ""))
            caption = _join(el.get("table_caption"))
            footnote = _join(el.get("table_footnote"))
            body = []
            if caption:
                body.append(f"**{caption}**")
            body.append(md)
            if footnote:
                body.append(f"_{footnote}_")
            chunks.append({**doc_meta, "chunk_type": "table", "section_path": list(section_path), "page": page + 1, "caption": caption, "footnote": footnote, "content": "\n\n".join(body)})
        elif t in ("image", "chart"):
            flush_text()
            cap_key = "img_caption" if t == "image" else "chart_caption"
            ft_key = "img_footnote" if t == "image" else "chart_footnote"
            caption = _join(el.get(cap_key))
            footnote = _join(el.get(ft_key))
            if not caption and not footnote:
                continue
            chunks.append({**doc_meta, "chunk_type": t, "section_path": list(section_path), "page": page + 1, "caption": caption, "footnote": footnote, "img_path": el.get("img_path", ""), "content": f"{caption}\n{footnote}".strip()})
        elif t in ("header", "footer"):
            continue
    flush_text()
    return chunks


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[。！？\n])", text)
    out, buf = [], ""
    for p in parts:
        if len(buf) + len(p) > max_chars and buf:
            out.append(buf.strip())
            buf = p
        else:
            buf += p
    if buf.strip():
        out.append(buf.strip())
    return out


def main():
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m rag.pdf_spliter.chunker <chunk_out_dir> [chunks.jsonl]")
    out_dir = Path(sys.argv[1])
    out_jsonl = Path(sys.argv[2]) if len(sys.argv) > 2 else out_dir / "chunks_mineru.jsonl"
    candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
    if not candidates:
        raise SystemExit(f"未找到 content_list.json in {out_dir}")
    src = candidates[0]
    print(f"读取: {src}")
    content = json.loads(src.read_text(encoding="utf-8"))
    doc_meta = {"doc_id": out_dir.name, "doc_title": out_dir.name}
    chunks = chunk_content_list(content, doc_meta)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")
    by_type = Counter(c["chunk_type"] for c in chunks)
    print(f"切块完成 -> {out_jsonl}")
    print(f"  总块数: {len(chunks)}")
    for t, n in by_type.most_common():
        print(f"    {t:18s} {n}")


if __name__ == "__main__":
    main()
