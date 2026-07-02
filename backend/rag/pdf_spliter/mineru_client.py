"""
MinerU 官方 API 客户端 (https://mineru.net)
"""
from __future__ import annotations

import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

import requests

from base.config import conf
from base.logger import logger

API_BASE = conf.mineru_base_url


class MinerUError(Exception):
    pass


class MinerUClient:
    def __init__(self, token: str | None = None, timeout: int = 60):
        self.token = token or conf.mineru_api_key
        self.token_name = "explicit" if token else (conf.mineru_token_name or "default")
        if not self.token:
            raise MinerUError(
                "缺少 API Token. 请在 backend/config.ini [mineru] 段或环境变量 "
                "MINERU_API_KEY 中配置 (申请地址: https://mineru.net/apiManage)"
            )
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        logger.info(f"MinerU 使用 token: {self.token_name} ({self.token[:12]}...)")

    def request_upload_url(
        self, file_name: str, data_id: str | None = None,
        model_version: str = "vlm", is_ocr: bool = True,
        enable_formula: bool = True, enable_table: bool = True,
        language: str = "ch",
    ) -> tuple[str, str, str]:
        data_id = data_id or str(uuid.uuid4())
        payload = {
            "files": [{"name": file_name, "data_id": data_id}],
            "model_version": model_version, "is_ocr": is_ocr,
            "enable_formula": enable_formula, "enable_table": enable_table,
            "language": language,
        }
        r = self.session.post(f"{API_BASE}/file-urls/batch", json=payload, timeout=self.timeout)
        body = self._check(r)
        return body["batch_id"], body["file_urls"][0], data_id

    @staticmethod
    def upload_file(presigned_url: str, file_path: Path, timeout: int = 300):
        with open(file_path, "rb") as f:
            r = requests.put(presigned_url, data=f, timeout=timeout)
        if r.status_code not in (200, 204):
            raise MinerUError(f"上传失败 status={r.status_code} body={r.text[:200]}")

    def poll_batch(self, batch_id: str, interval: float = 5.0, max_wait: float = 600.0) -> list[dict]:
        deadline = time.time() + max_wait
        last_progress = ""
        while True:
            r = self.session.get(
                f"{API_BASE}/extract-results/batch/{batch_id}", timeout=self.timeout,
            )
            body = self._check(r)
            results = body.get("extract_result", [])
            done_count = sum(1 for it in results if it.get("state") in ("done", "failed"))
            progress = f"  {done_count}/{len(results)} 完成"
            if progress != last_progress:
                logger.info(progress)
                last_progress = progress
            if results and done_count == len(results):
                return results
            if time.time() > deadline:
                raise MinerUError(f"轮询超时 ({max_wait}s)")
            time.sleep(interval)

    @staticmethod
    def download_and_unzip(zip_url: str, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        r = requests.get(zip_url, timeout=120)
        r.raise_for_status()
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            zf.extractall(out_dir)
        return out_dir

    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None,
                   model_version: str = "vlm", language: str = "ch") -> Path:
        pdf_path = Path(pdf_path)
        work_dir = Path(work_dir or pdf_path.parent / "chunk_out")
        work_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"1/4 申请上传 URL: {pdf_path.name}")
        batch_id, put_url, data_id = self.request_upload_url(
            pdf_path.name, model_version=model_version, language=language,
        )
        logger.info(f"      batch_id={batch_id}")
        logger.info(f"2/4 上传 PDF ({pdf_path.stat().st_size / 1024:.1f} KB)")
        self.upload_file(put_url, pdf_path)
        logger.info(f"3/4 等待解析完成 (轮询)")
        results = self.poll_batch(batch_id)
        if not results:
            raise MinerUError("未拿到任何结果")
        item = results[0]
        if item.get("state") != "done":
            raise MinerUError(f"解析失败: {item.get('err_msg') or item}")
        logger.info(f"4/4 下载并解压: {item['full_zip_url']}")
        out = self.download_and_unzip(item["full_zip_url"], work_dir)
        logger.info(f"      -> {out}")
        return out

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        try:
            body = resp.json()
        except Exception:
            raise MinerUError(f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}")
        if body.get("code") != 0:
            raise MinerUError(
                f"API 错误 code={body.get('code')} msg={body.get('msg')} trace={body.get('trace_id')}"
            )
        return body["data"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m rag.pdf_spliter.mineru_client <pdf_path>")
    client = MinerUClient()
    out_dir = client.parse_pdf(Path(sys.argv[1]))
    print(f"\n解析完成. 关键产物:")
    for f in sorted(out_dir.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(out_dir)}  ({f.stat().st_size:,} B)")
