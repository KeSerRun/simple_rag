# 这个字符串是文件的"文档说明"，描述了本模块的功能：使用 MinerU 进行 PDF 解析，
# 包括 API 客户端调用、内容分块处理、以及 PDF 加载器三个核心部分。
"""MinerU PDF 解析：API 客户端 → 内容分块 → PDF 加载器。"""

from __future__ import annotations

# 导入 json 模块，用于将 JSON 字符串解析为 Python 字典，或将 Python 对象转为 JSON 字符串。
import json
import re
# 导入 time 模块，提供与时间相关的函数，如 sleep（暂停执行）和 time（获取当前时间戳）。
import time
# 导入 uuid 模块，用于生成通用唯一标识符（UUID），保证每次生成的 ID 都是唯一的。
import uuid
# 从 io 模块中导入 BytesIO 类，它允许我们将字节数据当作文件对象来操作（内存中的二进制流）。
from io import BytesIO
# 从 pathlib 模块中导入 Path 类，用于以面向对象的方式处理文件和目录路径，
from pathlib import Path
from typing import Any, Iterator, Optional, TYPE_CHECKING

# 导入 requests 库，这是一个非常流行的 HTTP 请求库，用于向服务器发送
import requests

# 从项目的 base.config 模块中导入 conf 对象，这是一个全局配置对象，
from base.config import conf
# 从项目的 base.logger 模块中导入 logger 对象，这是一个日志记录器，
from base.logger import logger

if TYPE_CHECKING:
    # 从 vector_store 模块导入 Document 类，用于类型注解中的返回值类型标注。
    # 注意：这里使用了 from .vector_store 的相对导入语法，点号表示当前包。
    from .vector_store import Document



# 定义一个自定义异常类 MinerUError，继承自 Python 内置的 Exception 类。
# 这样调用方就可以通过捕获 MinerUError 来专门处理 MinerU 相关的错误。
class MinerUError(Exception):
    """MinerU API 调用异常。"""
    # pass 表示这个类没有额外的方法或属性，只是简单地继承 Exception 的所有行为。
    pass


# 定义 MinerUClient 类，这是 MinerU PDF 解析服务的 API 客户端封装。
# 它负责与 MinerU 的远程 API 进行交互，完成 PDF 文件的上传、解析和结果下载。
class MinerUClient:
    """MinerU PDF 解析 API 客户端（对接精准解析 API v4）。

    流程:
      1. POST {base}/file-urls/batch → 获取签名上传 URL + batch_id
      2. PUT 文件到签名 URL → 系统自动开始解析
      3. GET {base}/extract-results/batch/{batch_id} → 轮询至全部完成
      4. 下载 ZIP → 解压到输出目录
    """

    # 定义类的初始化方法（构造函数），当创建 MinerUClient 实例时自动调用。
    def __init__(self, token: str | None = None):
        # 如果传入了 token 就用传入的，否则从配置对象 conf.mineru_api_key 中读取。
        # Python 的 or 运算符：如果左侧为 None/空/False，则取右侧的值。
        self.token = token or conf.mineru_api_key
        # 检查 token 是否为空（None 或空字符串都算）。
        if not self.token:
            # 如果 token 为空，抛出 MinerUError 异常，并给出友好的错误提示，
            # 告诉用户需要在 config.ini 中配置 mineru_api_key。
            raise MinerUError(
                "缺少 API Token。请在 config.ini 中配置 mineru_api_key "
                "(申请地址: https://mineru.net/apiManage)"
            )
        # 从配置中读取 MinerU API 的基础 URL，并用 rstrip("/") 去掉末尾可能存在的斜杠，
        self._base = conf.mineru_base_url.rstrip("/")
        # 创建一个 requests.Session 会话对象。Session 会在多次请求之间保持 cookies
        # 和连接池，比每次单独使用 requests.get/post 更高效。
        self._session = requests.Session()
        # 值为 "Bearer " 加上 token，这是标准的 Bearer Token 认证方式。
        # headers.update() 会合并更新现有的请求头字典。
        self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        # 使用日志记录器输出一条提示信息，表示 MinerU 客户端已成功初始化，
        # 并显示 token 的前 12 个字符用于识别（出于安全考虑不显示完整 token）。
        logger.info(f"MinerU 客户端就绪: token={self.token[:12]}...")


    # 定义 parse_pdf 方法，这是 MinerUClient 对外暴露的核心方法。
    # pdf_path: PDF 文件的路径（可以是字符串或 Path 对象）
    # work_dir: 工作目录，解析结果会存放于此（可选，不传则使用默认路径）
    # model_version: 模型版本，默认使用 "vlm"（视觉语言模型）
    # language: 文档语言，默认使用 "ch"（中文）
    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None,
                  model_version: str = "vlm", language: str = "ch") -> Path:
        """上传 PDF → 等待解析 → 下载解压，返回输出目录。"""
        # 确保 pdf_path 是一个 Path 对象。如果传入的是字符串，Path() 会将其转换为 Path 对象。
        pdf_path = Path(pdf_path)
        # 在 PDF 文件所在目录下创建 chunk_out 文件夹，再用 PDF 文件名（不含扩展名）作为子文件夹名。
        # Path.stem 属性返回文件名中不包含后缀的部分，例如 "report.pdf" 的 stem 是 "report"。
        work_dir = Path(work_dir or pdf_path.parent / "chunk_out" / pdf_path.stem)
        # 创建 work_dir 目录，parents=True 表示如果父目录不存在也会一并创建，
        # exist_ok=True 表示如果目录已经存在也不会报错。
        work_dir.mkdir(parents=True, exist_ok=True)

        # 第1步：向 API 申请上传 URL（预签名 URL）
        logger.info(f"[1/4] 申请上传 URL: {pdf_path.name}")
        # 调用内部方法 _request_upload_url，传入文件名、模型版本和语言。
        # 该方法返回一个元组 (batch_id, put_url)，分别代表批次 ID 和用于上传文件的预签名 URL。
        batch_id, put_url = self._request_upload_url(pdf_path.name, model_version, language)
        logger.info(f"      batch_id={batch_id}")

        # 第2步：将 PDF 文件上传到预签名 URL
        # 计算文件大小（字节数除以 1024 转为 KB），保留一位小数。
        logger.info(f"[2/4] 上传 PDF ({pdf_path.stat().st_size / 1024:.1f} KB)")
        # 调用内部方法 _upload_file，传入预签名 URL 和文件路径，执行文件上传。
        self._upload_file(put_url, pdf_path)

        logger.info(f"[3/4] 等待解析完成")
        # 调用内部方法 _poll_batch，传入 batch_id，它会循环查询解析状态直至完成或超时。
        results = self._poll_batch(batch_id)
        item = results[0]
        # 检查解析结果的状态是否为 "done"（已完成）。
        if item.get("state") != "done":
            # 如果状态不是 "done"，则抛出异常，显示错误信息。
            # item.get("err_msg") 获取错误消息，如果没有则直接打印整个 item。
            raise MinerUError(f"解析失败: {item.get('err_msg') or item}")

        # 第4步：下载解析结果（ZIP 文件）并解压到工作目录
        zip_url = item["full_zip_url"]
        logger.info(f"[4/4] 下载并解压: {zip_url}")
        # 调用 _download_zip 方法下载 ZIP 并解压到 work_dir，返回 work_dir 本身。
        out = self._download_zip(zip_url, work_dir)
        logger.info(f"      -> {out}")
        return out


    # 定义 _request_upload_url 方法（以下划线开头表示"内部使用"，是 Python 的命名约定）。
    # file_name: 要上传的文件名（如 "report.pdf"）
    # model_version: 使用的解析模型版本
    # 返回值: 一个元组，包含 batch_id（批次ID）和 presigned URL（预签名上传链接）
    def _request_upload_url(self, file_name: str,
                            model_version: str = "vlm",
                            language: str = "ch") -> tuple[str, str]:
        """获取签名上传 URL 和 batch_id。"""
        # 使用 uuid.uuid4() 生成一个随机的 UUID（版本4），并转为字符串形式。
        data_id = str(uuid.uuid4())
        payload = {
            "files": [{"name": file_name, "data_id": data_id}],
            "model_version": model_version,
            "is_ocr": True,
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }
        # 调用 _post 方法向 API 发送 POST 请求，URL 为 base URL 拼接 "/file-urls/batch"。
        body = self._post(f"{self._base}/file-urls/batch", payload)
        # body 的结构预期为: {"batch_id": "...", "file_urls": ["https://..."]}
        # 从返回体中提取 batch_id 和第一个文件的预签名上传 URL，作为元组返回。
        return body["batch_id"], body["file_urls"][0]


    # 定义 _upload_file 方法，用于将本地文件通过 PUT 请求上传到预签名 URL。
    def _upload_file(self, presigned_url: str, file_path: Path):
        """PUT 文件到签名 URL。"""
        # 使用 with 语句以二进制只读模式 ("rb") 打开文件。
        # with 语句保证无论代码是否抛出异常，文件都会被正确关闭。
        with open(file_path, "rb") as f:
            # 使用 requests.put 方法向预签名 URL 发送 PUT 请求，
            # data=f 将文件对象作为请求体发送（requests 会自动流式读取文件内容），
            # timeout=300 设置超时时间为 300 秒（5分钟），防止网络问题导致程序卡死。
            r = requests.put(presigned_url, data=f, timeout=300)
        # 检查响应的 HTTP 状态码，200 表示成功，204 表示无内容（也代表成功）。
        if r.status_code not in (200, 204):
            # 上传失败时抛出 MinerUError，显示状态码和响应体的前 200 个字符。
            raise MinerUError(f"上传失败 status={r.status_code} body={r.text[:200]}")


    # batch_id: 上传时获得的批次 ID
    # interval: 每次轮询之间的等待时间（秒），默认 5 秒
    # max_wait: 最大等待时间（秒），默认 600 秒（10 分钟）
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


    # 定义 _download_zip 方法，用于从 URL 下载 ZIP 压缩包并解压到指定目录。
    # zip_url: ZIP 文件的下载链接
    def _download_zip(self, zip_url: str, out_dir: Path) -> Path:
        """下载并解压 ZIP。"""
        # 使用 requests.get 发送 GET 请求获取 ZIP 文件内容，超时时间 120 秒。
        r = requests.get(zip_url, timeout=120)
        # raise_for_status() 方法检查响应状态码，如果状态码表示请求失败（如 4xx 或 5xx），
        r.raise_for_status()
        # 在函数内部导入 zipfile 模块，这是 Python 内置的 ZIP 文件处理库。
        import zipfile
        # 使用 with 语句打开 ZIP 文件：
        # BytesIO(r.content) 将下载的字节内容包装成可读取的二进制流对象，
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            # 将 ZIP 文件中的所有内容解压到 out_dir 目录。
            # extractall() 会自动创建必要的子目录结构。
            zf.extractall(out_dir)
        return out_dir



    # 定义 _post 方法，用于发送 POST 请求并返回解析后的 JSON 数据。
    # payload: 要发送的请求体（字典形式，会自动转为 JSON）
    def _post(self, url: str, payload: dict) -> dict:
        # 使用 session.post 发送 POST 请求，json=payload 会自动将字典转为 JSON 格式
        # 并设置 Content-Type 为 application/json，timeout=60 秒超时。
        r = self._session.post(url, json=payload, timeout=60)
        return self._check(r)

    def _get(self, url: str) -> dict:
        # 使用 session.get 发送 GET 请求，timeout=60 秒超时。
        r = self._session.get(url, timeout=60)
        return self._check(r)

    @staticmethod
    # resp: requests.Response 对象，即 HTTP 响应的封装。
    def _check(resp: requests.Response) -> dict:
        try:
            # resp.json() 是 requests 库提供的方法，将响应的文本内容解析为 Python 字典。
            body = resp.json()
        # 如果解析失败（例如响应不是合法的 JSON 格式），捕获所有异常。
        except Exception:
            # 显示 HTTP 状态码和响应文本的前 300 个字符方便排查。
            raise MinerUError(
                f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}"
            )
        #   成功: {"code": 0, "data": {...}}
        #   失败: {"success": false, "msgCode": "A0202", "msg": "...", "traceId": "..."}
        # 先处理"success: false"格式的失败响应
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



# 定义一个模块级别的函数（不属于任何类），用于将 MinerU 解析后的 content_list
# content_list: MinerU 解析产出的内容列表，每个元素是一个字典
# doc_meta: 文档元数据字典，包含文档 ID、标题等信息
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
    chunks = []

    # sorted() 函数对 content_list 进行排序，返回一个新的排序后的列表。
    # key 参数指定排序的依据：先按 page_idx（页码）排序，再按 bbox 的 y 坐标（第二个元素）排序。
    sorted_items = sorted(
        content_list,
        # x.get("bbox", [0, 0, 0, 0])[1] 获取边界框的 y 坐标（纵坐标）。
        key=lambda x: (x.get("page_idx", 0), x.get("bbox", [0, 0, 0, 0])[1]),
    )

    for item in sorted_items:
        # 从当前项中获取 "type" 字段，表示内容类型（text/table/chart 等），默认为空字符串。
        typ = item.get("type", "")
        # 获取页码，MinerU 的 page_idx 是从 0 开始计数的，所以我们加 1 变成从 1 开始，
        page = (item.get("page_idx") or 0) + 1  # page_idx 从 0 开始

        # 如果类型是 "header"（页眉）或 "footer"（页脚），
        if typ in ("header", "footer"):
            continue

        if typ == "text":
            # 调用 _extract_text 辅助函数从 item 中提取纯文本内容。
            text = _extract_text(item)
            # 如果提取出的文本为空（None 或空字符串），则跳过此项目。
            if not text:
                continue
            chunks.append({
                "content": text,
                "chunk_type": "text",
                # "section_path": 从标题中提取的章节路径（如 ["第一章", "第一节"]）。
                # 调用 _extract_section 函数解析 item.get("title", "") 中的标题字符串。
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
            })

        elif typ in ("table", "chart"):
            img_path = item.get("img_path", "")
            # "".join(...) 将列表中的字符串拼接成单个字符串，如果为空列表则得到空字符串。
            caption = "".join(item.get(f"{typ}_caption", []) or [])
            footnote = "".join(item.get(f"{typ}_footnote", []) or [])
            # 对于表格，通常是 HTML 格式的 table；对于图表，可能是纯文本描述。
            body_html = item.get("table_body") or item.get("content") or ""
            # 将 HTML 表格转为 Markdown 格式
            # 如果 body_html 有内容，调用 _table_html_to_md 函数将其转为 Markdown 表格格式；
            body_text = _table_html_to_md(body_html) if body_html else ""
            # text 只放 caption，注释和数据单独存
            # 如果标题和正文都为空，则跳过此分块（没有有价值的内容）。
            if not caption and not body_text:
                continue
            chunks.append({
                # "content": 主要内容，优先使用 caption，如果 caption 为空则取 body_text 的前 80 个字符。
                # 如果 len(body_text) > 80 就截取前 80 字符加 "...", 否则用完整 body_text。
                "content": _normalize_text(caption or (body_text[:80] + "..." if len(body_text) > 80 else body_text)),
                # "chunk_type": 分块类型，原始类型 "table" 或 "chart"。
                "chunk_type": typ,
                # "section_path": 章节路径，从标题中提取。
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
                # "img_path": 图片路径（如果有）。
                "img_path": img_path,
                "caption": caption,
                # "footnote": 完整的脚注文本。
                "footnote": footnote,
                # "table_body": 如果是表格则存储 Markdown 格式的表格内容，图表则存空字符串。
                "table_body": body_text if typ == "table" else "",
            })

    # 使用日志记录器输出统计信息：原始 content_list 有多少项，生成了多少个分块。
    logger.info(f"MinerU content_list: {len(content_list)} items -> {len(chunks)} chunks")
    return chunks


# 定义 _extract_text 函数，从 MinerU 的内容项中提取纯文本。
def _extract_text(item: dict) -> str:
    texts = item.get("text", "")
    if isinstance(texts, list):
        # 如果是列表，则用空字符串 "" 将所有元素拼接在一起。
        return "".join(texts)
    return str(texts) if texts else ""


# 例如 "第一章 > 第一节" 会被解析为 ["第一章", "第一节"]。
# title: 标题字符串（可能包含 ">" 分隔符）
def _extract_section(title: str) -> list:
    if not title:
        return []
    # 使用 title.split(">") 将字符串按 ">" 分割成列表，
    # 然后遍历列表中的每个元素，用 s.strip() 去掉首尾空白字符，
    # 最后用 if s.strip() 过滤掉空白元素（如 ">" 前后的空格）。
    return [s.strip() for s in title.split(">") if s.strip()]


# 将英文标点替换为中文标点，并压缩多余的空白字符。
def _normalize_text(text: str) -> str:
    """规范表格/图表中的标点为中文符号，压缩空白。"""
    if not text:
        return ""
    # 将英文逗号 "," 替换为中文逗号 "，"。
    text = text.replace(",", "，")
    # 将英文冒号 ":" 替换为中文冒号 "："。
    text = text.replace(":", "：")
    # 将英文分号 ";" 替换为中文分号 "；"。
    text = text.replace(";", "；")
    # 将英文感叹号 "!" 替换为中文感叹号 "！"。
    text = text.replace("!", "！")
    # 将英文问号 "?" 替换为中文问号 "？"。
    text = text.replace("?", "？")
    # 使用正则表达式 re.sub(r"\s+", " ", text) 将所有连续的空白字符
    # （包括空格、制表符、换行等）替换为单个空格，然后去除首尾空白。
    text = re.sub(r"\s+", " ", text).strip()
    return text


# 定义 _table_html_to_md 函数，用于将 HTML 格式的表格转为 Markdown 表格格式。
# html: HTML 字符串，可能包含 `<table>` 标签
def _table_html_to_md(html: str) -> str:
    """将 HTML 表格转为 Markdown 表格格式。"""
    import re
    # 检查 HTML 字符串中是否包含 "<table" 标签。
    if "<table" not in html:
        # re.sub(r"<[^>]+>", "", html) 匹配并删除所有以 "<" 开头、">" 结尾的标签。
        return re.sub(r"<[^>]+>", "", html).strip()

    # 使用正则表达式查找所有表格行 <tr>...</tr> 的内容。
    # re.findall() 返回所有匹配的列表，re.DOTALL 标志让 "." 也能匹配换行符。
    #   <tr[^>]*>   - 匹配 <tr> 标签及其可能的属性
    #   (.*?)       - 非贪婪匹配标签内的内容（捕获组）
    #   </tr>       - 匹配结束标签
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    if not rows:
        return re.sub(r"<[^>]+>", "", html).strip()

    md_rows = []
    for ri, row in enumerate(rows):
        # 在当前行中查找所有单元格 <td>...</td> 或 <th>...</th> 的内容。
        #   <t[hd][^>]*> - 匹配 <td 或 <th 标签及属性
        #   (.*?)        - 非贪婪匹配单元格内容（捕获组）
        #   </t[hd]>     - 匹配 </td> 或 </th> 结束标签
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        md_cells = []
        for c in cells:
            # 清除单元格内容中的所有 HTML 标签，留下纯文本。
            clean = re.sub(r"<[^>]+>", "", c).strip()
            clean = re.sub(r"\s+", " ", clean)
            # 将处理后的单元格文本添加到 md_cells 列表中。
            md_cells.append(clean)
        # 将当前行转换为 Markdown 表格行格式：以 "| " 开头和结尾，单元格之间用 " | " 分隔。
        md_rows.append("| " + " | ".join(md_cells) + " |")

        # re.search() 在字符串中搜索正则表达式匹配，re.IGNORECASE 忽略大小写。
        if ri == 0 and re.search(r"<th", row, re.IGNORECASE):
            # 在表头行之后添加 Markdown 分隔行，"---" 表示列与列之间的分割线，
            # 数量与单元格数量相同，用 "|" 包裹，单元格间用 " | " 分隔。
            md_rows.append("| " + " | ".join(["---"] * len(md_cells)) + " |")

    # 将所有行用换行符 "\n" 连接起来，返回完整的 Markdown 表格字符串。
    return "\n".join(md_rows)



# 定义 MinerUPDFLoader 类，这是 MinerU PDF 解析器的入口类。
class MinerUPDFLoader:
    """MinerU PDF 解析器入口。需要配置 mineru_api_key。"""

    # file_path: PDF 文件的路径（字符串格式）
    def __init__(self, file_path: str) -> None:
        # 将传入的文件路径保存在实例属性 self.file_path 中，供后续使用。
        self.file_path = file_path

    # 定义 lazy_load 方法，它是一个生成器函数（因为使用了 yield 关键字）。
    # 返回值: Iterator[Document] 是一个迭代器，每次迭代返回一个 Document 对象。
    def lazy_load(self) -> Iterator[Document]:
        from .vector_store import Document
        # 将 self.file_path 转为 Path 对象，方便使用 pathlib 的丰富方法。
        path = Path(self.file_path)
        # 创建 MinerUClient 实例，传入 API Token（如果配置中没有则传 None）。
        client = MinerUClient(token=conf.mineru_api_key or None)
        # 构造工作目录路径：在 PDF 所在目录下创建 chunk_out 子文件夹，
        # 再用 PDF 文件名（不含扩展名）作为最内层文件夹的名称。
        work_dir = path.parent / "chunk_out" / path.stem
        # 调用客户端的 parse_pdf 方法执行完整的解析流程（上传 -> 等待 -> 下载解压），
        out_dir = client.parse_pdf(
            path, work_dir=work_dir,
            model_version=conf.mineru_model_version,
            language=conf.mineru_language,
        )
        # 在输出目录中递归搜索所有名为 "*content_list.json" 的文件，
        # 并排除文件名包含 "v2" 的文件（旧版本格式不兼容）。
        # out_dir.rglob("*content_list.json") 递归地匹配所有子目录中的文件。
        candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
        if not candidates:
            # 抛出 RuntimeError 运行时异常，提示未找到解析结果文件。
            raise RuntimeError(f"MinerU 输出未找到 content_list.json: {path.name}")
        # 读取找到的第一个 content_list.json 文件，使用 UTF-8 编码打开，
        # json.loads() 将 JSON 字符串解析为 Python 对象（列表或字典）。
        content = json.loads(candidates[0].read_text(encoding="utf-8"))
        # 构造文档元数据字典，包含文档 ID 和文档标题（都使用文件名 stem）。
        doc_meta = {"doc_id": path.stem, "doc_title": path.stem}
        # 调用 chunk_content_list 函数，将 MinerU 的内容列表转换为标准化的分块列表。
        chunks = chunk_content_list(content, doc_meta)
        if not chunks:
            raise RuntimeError(f"MinerU 切块结果为空: {path.name}")
        # 记录日志：解析完成，并显示生成了多少个分块。
        logger.info(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        # 遍历每个分块，使用 yield 逐个返回 Document 对象（生成器的特性）。
        for ch in chunks:
            content_text = ch.get("content", "")
            if not content_text:
                continue
            # 使用 yield 关键字返回一个 Document 对象。yield 类似 return，
            # 但函数的状态会被保留，下次调用时会从 yield 之后继续执行。
            yield Document(
                page_content=content_text,
                # metadata: 文档的元数据字典，包含来源、类型、位置等信息。
                metadata={
                    # "source": 原始 PDF 文件的路径。
                    "source": self.file_path,
                    # "pre_chunked": 标记该文档是预先分块过的（True），
                    "pre_chunked": True,
                    # "chunk_type": 分块类型（text/table/chart）。
                    "chunk_type": ch.get("chunk_type", ""),
                    # "section_path": 章节路径列表。
                    "section_path": ch.get("section_path", []),
                    "page": ch.get("page"),
                    # "caption": 标题文本（表格或图表的标题）。
                    "caption": ch.get("caption", ""),
                    "footnote": ch.get("footnote", ""),
                    # "img_path": 图片路径（如果有配图）。
                    "img_path": ch.get("img_path", ""),
                    # "table_body": 表格的 Markdown 格式内容。
                    "table_body": ch.get("table_body", ""),
                },
            )

    # 内部调用了 lazy_load 生成器，并用 list() 将生成器的所有产出收集为列表。
    def load(self) -> list:
        # list(self.lazy_load()) 会遍历生成器，收集所有 yield 出来的 Document 对象，
        return list(self.lazy_load())
