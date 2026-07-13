"""MinerU PDF 解析：API 客户端 → 内容分块 → PDF 加载器。"""

from __future__ import annotations

import json
# ---- MinerU API 客户端 ----
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Optional, TYPE_CHECKING

import requests

from base.config import conf
from base.logger import logger

if TYPE_CHECKING:
    from .vector_store import Document

# ---- PDF 分块策略 ----


# ---- MinerUError ----
class MinerUError(Exception):
    """MinerU API 调用异常。"""
    pass


# ---- MinerUClient ----
class MinerUClient:
    """MinerU PDF 解析 API 客户端（对接精准解析 API v4）。

    流程:
      1. POST {base}/file-urls/batch → 获取签名上传 URL + batch_id
      2. PUT 文件到签名 URL → 系统自动开始解析
      3. GET {base}/extract-results/batch/{batch_id} → 轮询至全部完成
      4. 下载 ZIP → 解压到输出目录
    """

# ---- __init__ ----
    def __init__(self, token: str | None = None):
        self.token = token or conf.mineru_api_key
        if not self.token:
            raise MinerUError(
                "缺少 API Token。请在 config.ini 中配置 mineru_api_key "
                "(申请地址: https://mineru.net/apiManage)"
            )
        self._base = conf.mineru_base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        logger.info(f"MinerU 客户端就绪: token={self.token[:12]}...")


# ---- parse_pdf ----
    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None,
                  model_version: str = "vlm", language: str = "ch") -> Path:
        """上传 PDF → 等待解析 → 下载解压，返回输出目录。"""
        pdf_path = Path(pdf_path)
        work_dir = Path(work_dir or pdf_path.parent / "chunk_out" / pdf_path.stem)
        work_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[1/4] 申请上传 URL: {pdf_path.name}")
        batch_id, put_url = self._request_upload_url(pdf_path.name, model_version, language)
        logger.info(f"      batch_id={batch_id}")

        logger.info(f"[2/4] 上传 PDF ({pdf_path.stat().st_size / 1024:.1f} KB)")
        self._upload_file(put_url, pdf_path)

        logger.info(f"[3/4] 等待解析完成")
        results = self._poll_batch(batch_id)
        item = results[0]
        if item.get("state") != "done":
            raise MinerUError(f"解析失败: {item.get('err_msg') or item}")

        zip_url = item["full_zip_url"]
        logger.info(f"[4/4] 下载并解压: {zip_url}")
        out = self._download_zip(zip_url, work_dir)
        logger.info(f"      -> {out}")
        return out


# ---- _request_upload_url ----
    def _request_upload_url(self, file_name: str,
                            model_version: str = "vlm",
                            language: str = "ch") -> tuple[str, str]:
        """获取签名上传 URL 和 batch_id。"""
        data_id = str(uuid.uuid4())
        payload = {
            "files": [{"name": file_name, "data_id": data_id}],
            "model_version": model_version,
            "is_ocr": True,
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }
        body = self._post(f"{self._base}/file-urls/batch", payload)
        # body 的结构预期为: {"batch_id": "...", "file_urls": ["https://..."]}
        return body["batch_id"], body["file_urls"][0]


# ---- _upload_file ----
    def _upload_file(self, presigned_url: str, file_path: Path):
        """PUT 文件到签名 URL。"""
        with open(file_path, "rb") as f:
            r = requests.put(presigned_url, data=f, timeout=300)
        if r.status_code not in (200, 204):
            raise MinerUError(f"上传失败 status={r.status_code} body={r.text[:200]}")


# ---- _poll_batch ----
    def _poll_batch(self, batch_id: str, interval: float = 5.0,
                    max_wait: float = 1200.0) -> list[dict]:
        """轮询解析结果，返回 extract_result 列表。"""
        deadline = time.time() + max_wait
        start = time.time()
        url = f"{self._base}/extract-results/batch/{batch_id}"
        last_heartbeat = -1
        first_data_ts: float | None = None

        while True:
            body = self._get(url)

            if not isinstance(body, dict):
                raise MinerUError(
                    f"API 返回了意外的 data 类型: {type(body).__name__}, "
                    f"期望 dict, 内容: {str(body)[:200]}"
                )

            raw = body.get("extract_result")      # 可能是 None / [] / [items]
            results = raw if isinstance(raw, list) else []

            if results:
                states = {
                    it.get("data_id") or it.get("file_name", "?"):
                        it.get("state", "unknown")
                    for it in results
                }
                logger.info(f"轮询状态: {states}")
            else:
                elapsed = time.time() - start
                logger.info(f"extract_result 为空 (已等待 {elapsed:.0f}s), 继续等待...")

            done_count = sum(
                1 for it in results
                if it.get("state") in ("done", "failed")
            )
            if results and done_count == len(results):
                return results

            elapsed = time.time() - start
            if time.time() > deadline:
                parts = [f"轮询超时 ({max_wait:.0f}s) batch={batch_id}"]
                if results:
                    parts.append(f"{done_count}/{len(results)} done")
                    states = {
                        it.get("data_id") or it.get("file_name", "?"):
                            it.get("state", "unknown")
                        for it in results
                    }
                    parts.append(f"states={states}")
                raise MinerUError(" ".join(parts))

            heartbeat = int(elapsed) // 30
            if heartbeat > last_heartbeat:
                last_heartbeat = heartbeat
                status = (
                    f"{done_count}/{len(results)} 完成"
                    if results else "等待 API 返回结果"
                )
                logger.info(f"[3/4] 仍在等待 (已等待 {elapsed:.0f}s, {status})...")

            time.sleep(interval)


# ---- _download_zip ----
    def _download_zip(self, zip_url: str, out_dir: Path) -> Path:
        """下载并解压 ZIP。"""
        r = requests.get(zip_url, timeout=120)
        r.raise_for_status()
        import zipfile
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            zf.extractall(out_dir)
        return out_dir


# ---- _post ----
    def _post(self, url: str, payload: dict) -> dict:
        r = self._session.post(url, json=payload, timeout=60)
        return self._check(r)

# ---- _get ----
    def _get(self, url: str) -> dict:
        r = self._session.get(url, timeout=60)
        return self._check(r)

    @staticmethod
# ---- _check ----
    def _check(resp: requests.Response) -> dict:
        try:
            body = resp.json()
        except Exception:
            raise MinerUError(
                f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}"
            )
        if body.get("success") is False:
            err_code = body.get("msgCode") or "?"
            err_msg = body.get("msg") or "未知错误"
            trace = body.get("traceId") or body.get("trace_id") or ""
            raise MinerUError(
                f"API 错误 code={err_code} msg={err_msg} trace={trace}"
            )
        if body.get("code") != 0:
            raise MinerUError(
                f"API 错误 code={body.get('code')} msg={body.get('msg')} "
                f"trace={body.get('trace_id')}"
            )
        if "data" not in body:
            raise MinerUError(
                f"API 响应缺少 data 字段, body keys={list(body.keys())[:10]}, "
                f"msg={body.get('msg', '')}"
            )
        return body["data"]


# ---- chunk_content_list ----
def chunk_content_list(content_list: list, doc_meta: dict) -> list[dict]:
    """将 MinerU 的 content_list 转为标准化的分块列表。

    MinerU 字段说明:
      - type: text / table / chart / header / footer / image
      - page_idx: 页码（从 0 开始）
      - text / table_body / content: 正文内容
      - img_path: 图片路径
      - table_caption / chart_caption / table_footnote / chart_footnote: 标题/注释
      - bbox: 坐标 [x0, y0, x1, y1]
    """
    # 兼容新版 MiningU JSON 格式（dict 含 content_list 键）
    if isinstance(content_list, dict):
        content_list = content_list.get("content_list", content_list)
    if not isinstance(content_list, list):
        return []
    chunks = []

    sorted_items = sorted(
        content_list,
        key=lambda x: (x.get("page_idx", 0), x.get("bbox", [0, 0, 0, 0])[1]),
    )

    for item in sorted_items:
        typ = item.get("type", "")
        page = (item.get("page_idx") or 0) + 1  # page_idx 从 0 开始

        if typ in ("header", "footer"):
            continue

        if typ == "text":
            text = _extract_text(item)
            if not text:
                continue
            chunks.append({
                "content": text,
                "chunk_type": "text",
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
            })

        elif typ in ("table", "chart"):
            img_path = item.get("img_path", "")
            caption = "".join(item.get(f"{typ}_caption", []) or [])
            footnote = "".join(item.get(f"{typ}_footnote", []) or [])
            body_html = item.get("table_body") or item.get("content") or ""
            body_text = _table_html_to_md(body_html) if body_html else ""
            if not caption and not body_text:
                continue
            chunks.append({
                "content": _normalize_text(caption or (body_text[:80] + "..." if len(body_text) > 80 else body_text)),
                "chunk_type": typ,
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
                "img_path": img_path,
                "caption": caption,
                "footnote": footnote,
                "table_body": body_text if typ == "table" else "",
            })

    logger.info(f"MinerU content_list: {len(content_list)} items -> {len(chunks)} chunks")
    return chunks


# ---- _extract_text ----
def _extract_text(item: dict) -> str:
    texts = item.get("text", "")
    if isinstance(texts, list):
        return "".join(texts)
    return str(texts) if texts else ""


# ---- _extract_section ----
def _extract_section(title: str) -> list:
    if not title:
        return []
    return [s.strip() for s in title.split(">") if s.strip()]


# ---- _normalize_text ----
def _normalize_text(text: str) -> str:
    """规范表格/图表中的标点为中文符号，压缩空白。"""
    if not text:
        return ""
    text = text.replace(",", "，")
    text = text.replace(":", "：")
    text = text.replace(";", "；")
    text = text.replace("!", "！")
    text = text.replace("?", "？")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---- _table_html_to_md ----
def _table_html_to_md(html: str) -> str:
    """将 HTML 表格转为 Markdown 表格格式。"""
    import re
    if "<table" not in html:
        return re.sub(r"<[^>]+>", "", html).strip()

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    if not rows:
        return re.sub(r"<[^>]+>", "", html).strip()

    md_rows = []
    for ri, row in enumerate(rows):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        md_cells = []
        for c in cells:
            clean = re.sub(r"<[^>]+>", "", c).strip()
            clean = re.sub(r"\s+", " ", clean)
            md_cells.append(clean)
        md_rows.append("| " + " | ".join(md_cells) + " |")

        if ri == 0 and re.search(r"<th", row, re.IGNORECASE):
            md_rows.append("| " + " | ".join(["---"] * len(md_cells)) + " |")

    return "\n".join(md_rows)


# ---- MinerUPDFLoader ----
class MinerUPDFLoader:
    """MinerU PDF 解析器入口。需要配置 mineru_api_key。"""

# ---- __init__ ----
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

# ---- lazy_load ----
    def lazy_load(self) -> Iterator[Document]:
        from .vector_store import Document
        path = Path(self.file_path)
        client = MinerUClient(token=conf.mineru_api_key or None)
        work_dir = path.parent / "chunk_out" / path.stem
        out_dir = client.parse_pdf(
            path, work_dir=work_dir,
            model_version=conf.mineru_model_version,
            language=conf.mineru_language,
        )
        candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
        if not candidates:
            raise RuntimeError(f"MinerU 输出未找到 content_list.json: {path.name}")
        content = json.loads(candidates[0].read_text(encoding="utf-8"))
        # MinerU 新版返回 {"content_list": [...]}，旧版直接返回 [...]
        if isinstance(content, dict):
            content = content.get("content_list", content)
        doc_meta = {"doc_id": path.stem, "doc_title": path.stem}
        chunks = chunk_content_list(content, doc_meta)
        if not chunks:
            raise RuntimeError(f"MinerU 切块结果为空: {path.name}")
        logger.info(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        for ch in chunks:
            content_text = ch.get("content", "")
            if not content_text:
                continue
            yield Document(
                page_content=content_text,
                metadata={
                    "source": self.file_path,
                    "pre_chunked": True,
                    "chunk_type": ch.get("chunk_type", ""),
                    "section_path": ch.get("section_path", []),
                    "page": ch.get("page"),
                    "caption": ch.get("caption", ""),
                    "footnote": ch.get("footnote", ""),
                    "img_path": ch.get("img_path", ""),
                    "table_body": ch.get("table_body", ""),
                },
            )

# ---- load ----
    def load(self) -> list:
        return list(self.lazy_load())

# ===== MinerU API 客户端 =====

# ===== PDF 下载与缓存 =====

# ===== 分块策略：按段落/标题 =====
