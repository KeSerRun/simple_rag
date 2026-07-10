# ===== 模块文档字符串 =====
# 这个字符串是文件的"文档说明"，描述了本模块的功能：使用 MinerU 进行 PDF 解析，
# 包括 API 客户端调用、内容分块处理、以及 PDF 加载器三个核心部分。
"""MinerU PDF 解析：API 客户端 → 内容分块 → PDF 加载器。"""

# ===== 导入标准库模块 =====
# 从 __future__ 导入 annotations，让类型注解中的字符串被当作普通注解处理，
# 这样在类方法中引用尚未定义的类型时不会报错（比如在类内部引用类自身）。
from __future__ import annotations

# 导入 json 模块，用于将 JSON 字符串解析为 Python 字典，或将 Python 对象转为 JSON 字符串。
import json
# 导入 re 模块，提供正则表达式功能，用于在字符串中执行模式匹配和替换操作。
import re
# 导入 time 模块，提供与时间相关的函数，如 sleep（暂停执行）和 time（获取当前时间戳）。
import time
# 导入 uuid 模块，用于生成通用唯一标识符（UUID），保证每次生成的 ID 都是唯一的。
import uuid
# 从 io 模块中导入 BytesIO 类，它允许我们将字节数据当作文件对象来操作（内存中的二进制流）。
from io import BytesIO
# 从 pathlib 模块中导入 Path 类，用于以面向对象的方式处理文件和目录路径，
# 相比字符串拼接路径更加安全和跨平台。
from pathlib import Path
# 从 typing 模块导入类型提示工具，Any 表示任意类型，Iterator 表示迭代器类型，
# Optional 表示可选类型（可以是某个类型或 None），TYPE_CHECKING 是一个特殊的常量，
# 在运行时为 False，仅在类型检查时生效，用于避免循环导入。
from typing import Any, Iterator, Optional, TYPE_CHECKING

# ===== 导入第三方库 =====
# 导入 requests 库，这是一个非常流行的 HTTP 请求库，用于向服务器发送
# GET、POST、PUT 等 HTTP 请求并获取响应。
import requests

# ===== 导入项目内部模块 =====
# 从项目的 base.config 模块中导入 conf 对象，这是一个全局配置对象，
# 包含了从配置文件（如 config.ini）中读取的各种设置项。
from base.config import conf
# 从项目的 base.logger 模块中导入 logger 对象，这是一个日志记录器，
# 用于在控制台或日志文件中输出带时间戳和级别的日志信息。
from base.logger import logger

# ===== 类型检查专用导入（仅在类型检查时执行） =====
# TYPE_CHECKING 在运行阶段是 False，在 IDE 或 mypy 做类型检查时是 True。
# 这样写可以避免在运行时因为循环导入而报错，同时又能享受类型提示的好处。
if TYPE_CHECKING:
    # 从 vector_store 模块导入 Document 类，用于类型注解中的返回值类型标注。
    # 注意：这里使用了 from .vector_store 的相对导入语法，点号表示当前包。
    from .vector_store import Document


# ===== MinerU API 客户端 =====
# ─── MinerU API 客户端 ─────────────────────────────────────────

# 定义一个自定义异常类 MinerUError，继承自 Python 内置的 Exception 类。
# 当 MinerU API 调用过程中出现任何错误时，我们会抛出这个异常，
# 这样调用方就可以通过捕获 MinerUError 来专门处理 MinerU 相关的错误。
class MinerUError(Exception):
    """MinerU API 调用异常。"""
    # pass 表示这个类没有额外的方法或属性，只是简单地继承 Exception 的所有行为。
    # 我们定义这个类只是为了能有一个专门的异常类型，方便区分不同的错误。
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
    # token 参数是可选的，如果不传则从全局配置中读取。
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
        # 这样后面拼接 URL 时就不会出现双斜杠的问题。
        self._base = conf.mineru_base_url.rstrip("/")
        # 创建一个 requests.Session 会话对象。Session 会在多次请求之间保持 cookies
        # 和连接池，比每次单独使用 requests.get/post 更高效。
        self._session = requests.Session()
        # 设置会话的默认请求头，添加 Authorization（授权）字段，
        # 值为 "Bearer " 加上 token，这是标准的 Bearer Token 认证方式。
        # headers.update() 会合并更新现有的请求头字典。
        self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        # 使用日志记录器输出一条提示信息，表示 MinerU 客户端已成功初始化，
        # 并显示 token 的前 12 个字符用于识别（出于安全考虑不显示完整 token）。
        logger.info(f"MinerU 客户端就绪: token={self.token[:12]}...")


    # ===== 核心公开方法：解析 PDF =====
    # 定义 parse_pdf 方法，这是 MinerUClient 对外暴露的核心方法。
    # pdf_path: PDF 文件的路径（可以是字符串或 Path 对象）
    # work_dir: 工作目录，解析结果会存放于此（可选，不传则使用默认路径）
    # model_version: 模型版本，默认使用 "vlm"（视觉语言模型）
    # language: 文档语言，默认使用 "ch"（中文）
    # 返回值: Path 对象，指向包含解析结果的输出目录
    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None,
                  model_version: str = "vlm", language: str = "ch") -> Path:
        """上传 PDF → 等待解析 → 下载解压，返回输出目录。"""
        # 确保 pdf_path 是一个 Path 对象。如果传入的是字符串，Path() 会将其转换为 Path 对象。
        pdf_path = Path(pdf_path)
        # 确定工作目录。如果没有传入 work_dir，就创建一个默认路径：
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

        # 第3步：轮询等待 API 解析完成
        logger.info(f"[3/4] 等待解析完成")
        # 调用内部方法 _poll_batch，传入 batch_id，它会循环查询解析状态直至完成或超时。
        # 返回一个列表，其中每个元素是一个字典，代表一个文件的解析结果。
        results = self._poll_batch(batch_id)
        # 因为我们只上传了一个文件，所以取 results 列表的第一个元素。
        item = results[0]
        # 检查解析结果的状态是否为 "done"（已完成）。
        if item.get("state") != "done":
            # 如果状态不是 "done"，则抛出异常，显示错误信息。
            # item.get("err_msg") 获取错误消息，如果没有则直接打印整个 item。
            raise MinerUError(f"解析失败: {item.get('err_msg') or item}")

        # 第4步：下载解析结果（ZIP 文件）并解压到工作目录
        # 从结果中获取 ZIP 文件的下载链接。
        zip_url = item["full_zip_url"]
        logger.info(f"[4/4] 下载并解压: {zip_url}")
        # 调用 _download_zip 方法下载 ZIP 并解压到 work_dir，返回 work_dir 本身。
        out = self._download_zip(zip_url, work_dir)
        logger.info(f"      -> {out}")
        # 返回包含解析结果的输出目录路径。
        return out


    # ===== 内部方法：申请上传 URL =====
    # 定义 _request_upload_url 方法（以下划线开头表示"内部使用"，是 Python 的命名约定）。
    # file_name: 要上传的文件名（如 "report.pdf"）
    # model_version: 使用的解析模型版本
    # language: 文档语言
    # 返回值: 一个元组，包含 batch_id（批次ID）和 presigned URL（预签名上传链接）
    def _request_upload_url(self, file_name: str,
                            model_version: str = "vlm",
                            language: str = "ch") -> tuple[str, str]:
        """获取签名上传 URL 和 batch_id。"""
        # 使用 uuid.uuid4() 生成一个随机的 UUID（版本4），并转为字符串形式。
        # 这个 ID 用于在 API 端标识当前文件。
        data_id = str(uuid.uuid4())
        # 构造要发送给 API 的请求体（payload），这是一个字典。
        payload = {
            # "files" 是一个列表，每个元素是一个文件信息字典。
            # 虽然 MinerU API 支持批量上传多个文件，但我们每次只传一个文件。
            "files": [{"name": file_name, "data_id": data_id}],
            # 指定使用的模型版本。
            "model_version": model_version,
            # 是否启用 OCR（光学字符识别）功能，设置为 True。
            "is_ocr": True,
            # 是否启用公式识别功能，设置为 True。
            "enable_formula": True,
            # 是否启用表格识别功能，设置为 True。
            "enable_table": True,
            # 文档语言，默认是中文。
            "language": language,
        }
        # 调用 _post 方法向 API 发送 POST 请求，URL 为 base URL 拼接 "/file-urls/batch"。
        # 该方法会返回解析后的 JSON 数据中的 "data" 字段。
        body = self._post(f"{self._base}/file-urls/batch", payload)
        # body 的结构预期为: {"batch_id": "...", "file_urls": ["https://..."]}
        # 从返回体中提取 batch_id 和第一个文件的预签名上传 URL，作为元组返回。
        return body["batch_id"], body["file_urls"][0]


    # ===== 内部方法：上传文件 =====
    # 定义 _upload_file 方法，用于将本地文件通过 PUT 请求上传到预签名 URL。
    # presigned_url: API 返回的预签名上传链接（临时有效）
    # file_path: 本地文件的路径
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
        # status_code 不在 (200, 204) 这个元组中就说明上传失败。
        if r.status_code not in (200, 204):
            # 上传失败时抛出 MinerUError，显示状态码和响应体的前 200 个字符。
            raise MinerUError(f"上传失败 status={r.status_code} body={r.text[:200]}")


    # ===== 内部方法：轮询解析结果 =====
    # 定义 _poll_batch 方法，用于循环查询 API 直到解析完成或超时。
    # batch_id: 上传时获得的批次 ID
    # interval: 每次轮询之间的等待时间（秒），默认 5 秒
    # max_wait: 最大等待时间（秒），默认 600 秒（10 分钟）
    # 返回值: 解析结果列表，每个元素是一个字典
    def _poll_batch(self, batch_id: str, interval: float = 5.0,
                    max_wait: float = 1200.0) -> list[dict]:
        """轮询解析结果，返回 extract_result 列表。"""
        deadline = time.time() + max_wait
        start = time.time()
        url = f"{self._base}/extract-results/batch/{batch_id}"
        last_heartbeat = -1
        # 首次拿到非空 results 的时间戳（用于 graceful period）
        first_data_ts: float | None = None

        while True:
            # ── 1. 请求 API ──────────────────────────────────
            body = self._get(url)

            # ── 2. 防御：body 必须是 dict ─────────────────────
            if not isinstance(body, dict):
                raise MinerUError(
                    f"API 返回了意外的 data 类型: {type(body).__name__}, "
                    f"期望 dict, 内容: {str(body)[:200]}"
                )

            # ── 3. 提取 extract_result，处理 null/缺失 ────────
            raw = body.get("extract_result")      # 可能是 None / [] / [items]
            results = raw if isinstance(raw, list) else []

            # ── 4. 显示所有文件的原始 state ──────────────────
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

            # ── 5. 判定完成 ──────────────────────────────────
            done_count = sum(
                1 for it in results
                if it.get("state") in ("done", "failed")
            )
            if results and done_count == len(results):
                return results

            # ── 6. 超时检查 ──────────────────────────────────
            elapsed = time.time() - start
            if time.time() > deadline:
                # 超时 — 附加已有信息方便排查
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

            # ── 7. 30 秒心跳 ─────────────────────────────────
            heartbeat = int(elapsed) // 30
            if heartbeat > last_heartbeat:
                last_heartbeat = heartbeat
                status = (
                    f"{done_count}/{len(results)} 完成"
                    if results else "等待 API 返回结果"
                )
                logger.info(f"[3/4] 仍在等待 (已等待 {elapsed:.0f}s, {status})...")

            time.sleep(interval)


    # ===== 内部方法：下载并解压 ZIP =====
    # 定义 _download_zip 方法，用于从 URL 下载 ZIP 压缩包并解压到指定目录。
    # zip_url: ZIP 文件的下载链接
    # out_dir: 解压目标目录
    # 返回值: 解压后的目录路径
    def _download_zip(self, zip_url: str, out_dir: Path) -> Path:
        """下载并解压 ZIP。"""
        # 使用 requests.get 发送 GET 请求获取 ZIP 文件内容，超时时间 120 秒。
        r = requests.get(zip_url, timeout=120)
        # raise_for_status() 方法检查响应状态码，如果状态码表示请求失败（如 4xx 或 5xx），
        # 它会自动抛出一个 HTTPError 异常。
        r.raise_for_status()
        # 在函数内部导入 zipfile 模块，这是 Python 内置的 ZIP 文件处理库。
        # 在这里导入是为了延迟加载，提高模块初始化的速度。
        import zipfile
        # 使用 with 语句打开 ZIP 文件：
        # BytesIO(r.content) 将下载的字节内容包装成可读取的二进制流对象，
        # zipfile.ZipFile 将这个流作为 ZIP 文件打开。
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            # 将 ZIP 文件中的所有内容解压到 out_dir 目录。
            # extractall() 会自动创建必要的子目录结构。
            zf.extractall(out_dir)
        # 返回解压后的输出目录路径。
        return out_dir


    # ===== HTTP 工具方法 =====
    # ─── HTTP 工具 ──────────────────────────────────

    # 定义 _post 方法，用于发送 POST 请求并返回解析后的 JSON 数据。
    # url: 请求的 URL 地址
    # payload: 要发送的请求体（字典形式，会自动转为 JSON）
    # 返回值: 解析后的数据字典
    def _post(self, url: str, payload: dict) -> dict:
        # 使用 session.post 发送 POST 请求，json=payload 会自动将字典转为 JSON 格式
        # 并设置 Content-Type 为 application/json，timeout=60 秒超时。
        r = self._session.post(url, json=payload, timeout=60)
        # 调用 _check 方法检查响应并返回解析后的数据。
        return self._check(r)

    # 定义 _get 方法，用于发送 GET 请求并返回解析后的 JSON 数据。
    # url: 请求的 URL 地址
    # 返回值: 解析后的数据字典
    def _get(self, url: str) -> dict:
        # 使用 session.get 发送 GET 请求，timeout=60 秒超时。
        r = self._session.get(url, timeout=60)
        # 调用 _check 方法检查响应并返回解析后的数据。
        return self._check(r)

    # 使用 @staticmethod 装饰器将下面的方法定义为"静态方法"。
    # 静态方法不接收 self（实例自身）或 cls（类自身）作为参数，
    # 它就像一个普通的函数，只是因为和类逻辑相关而放在类中。
    @staticmethod
    # 定义 _check 方法，用于统一检查 API 响应并解析 JSON 数据。
    # resp: requests.Response 对象，即 HTTP 响应的封装。
    # 返回值: 解析后的数据字典（API 返回体中的 "data" 字段）
    def _check(resp: requests.Response) -> dict:
        # 尝试将响应体解析为 JSON 格式。
        try:
            # resp.json() 是 requests 库提供的方法，将响应的文本内容解析为 Python 字典。
            body = resp.json()
        # 如果解析失败（例如响应不是合法的 JSON 格式），捕获所有异常。
        except Exception:
            # 抛出 MinerUError，说明收到了非 JSON 格式的响应，
            # 显示 HTTP 状态码和响应文本的前 300 个字符方便排查。
            raise MinerUError(
                f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}"
            )
        # MinerU API 响应有两种格式:
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
        # 再检查标准的 code ≠ 0
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


# ===== 内容分块处理 =====
# ─── 内容分块 ─────────────────────────────────────────────────

# 定义一个模块级别的函数（不属于任何类），用于将 MinerU 解析后的 content_list
# 转换为标准化的分块列表。每个分块代表一个独立的内容单元（段落、表格或图表）。
# content_list: MinerU 解析产出的内容列表，每个元素是一个字典
# doc_meta: 文档元数据字典，包含文档 ID、标题等信息
# 返回值: 分块列表，每个分块是一个字典，包含内容、类型、页码等信息
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
    # 初始化一个空列表，用于存储分块后的结果。
    chunks = []

    # 按页码和 y 坐标排序，确保阅读顺序
    # sorted() 函数对 content_list 进行排序，返回一个新的排序后的列表。
    # key 参数指定排序的依据：先按 page_idx（页码）排序，再按 bbox 的 y 坐标（第二个元素）排序。
    # 这样做的目的是保持文档的自然阅读顺序（从上到下，从左到右）。
    sorted_items = sorted(
        content_list,
        # lambda 表达式定义了一个匿名函数，输入 x（列表中的每个元素），
        # 返回一个元组 (页码, y坐标)，sorted 根据这个元组排序。
        # x.get("page_idx", 0) 从字典中获取页码，默认 0。
        # x.get("bbox", [0, 0, 0, 0])[1] 获取边界框的 y 坐标（纵坐标）。
        key=lambda x: (x.get("page_idx", 0), x.get("bbox", [0, 0, 0, 0])[1]),
    )

    # 遍历排序后的内容项列表。
    for item in sorted_items:
        # 从当前项中获取 "type" 字段，表示内容类型（text/table/chart 等），默认为空字符串。
        typ = item.get("type", "")
        # 获取页码，MinerU 的 page_idx 是从 0 开始计数的，所以我们加 1 变成从 1 开始，
        # 这样更符合人类阅读习惯。如果 page_idx 为 None 则用 0。
        page = (item.get("page_idx") or 0) + 1  # page_idx 从 0 开始

        # 跳过页眉页脚
        # 如果类型是 "header"（页眉）或 "footer"（页脚），
        # 这些内容通常不包含文档的核心信息，所以我们直接跳过，不纳入分块。
        if typ in ("header", "footer"):
            continue

        # 处理文本类型的内容
        if typ == "text":
            # 调用 _extract_text 辅助函数从 item 中提取纯文本内容。
            text = _extract_text(item)
            # 如果提取出的文本为空（None 或空字符串），则跳过此项目。
            if not text:
                continue
            # 将提取的文本作为一个分块添加到 chunks 列表中。
            chunks.append({
                # "content": 文本内容，用于后续检索和展示。
                "content": text,
                # "chunk_type": 分块类型，这里标记为 "text"。
                "chunk_type": "text",
                # "section_path": 从标题中提取的章节路径（如 ["第一章", "第一节"]）。
                # 调用 _extract_section 函数解析 item.get("title", "") 中的标题字符串。
                "section_path": _extract_section(item.get("title", "")),
                # "page": 当前内容所在的页码。
                "page": page,
            })

        # 处理表格或图表类型的内容
        elif typ in ("table", "chart"):
            # 从当前项中获取图片路径（如果有的话），用于后续展示图片版。
            img_path = item.get("img_path", "")
            # 获取标题（caption），类型可能是表格标题或图表标题。
            # "".join(...) 将列表中的字符串拼接成单个字符串，如果为空列表则得到空字符串。
            caption = "".join(item.get(f"{typ}_caption", []) or [])
            # 获取脚注（footnote），同样可能是列表形式，用 join 拼接。
            footnote = "".join(item.get(f"{typ}_footnote", []) or [])
            # 获取表格主体 HTML 或图表的文本内容。
            # 对于表格，通常是 HTML 格式的 table；对于图表，可能是纯文本描述。
            body_html = item.get("table_body") or item.get("content") or ""
            # 将 HTML 表格转为 Markdown 格式
            # 如果 body_html 有内容，调用 _table_html_to_md 函数将其转为 Markdown 表格格式；
            # 否则 body_text 为空字符串。
            body_text = _table_html_to_md(body_html) if body_html else ""
            # text 只放 caption，注释和数据单独存
            # 如果标题和正文都为空，则跳过此分块（没有有价值的内容）。
            if not caption and not body_text:
                continue
            # 将表格或图表作为一个分块添加到 chunks 列表中。
            chunks.append({
                # "content": 主要内容，优先使用 caption，如果 caption 为空则取 body_text 的前 80 个字符。
                # 这里使用了一个条件表达式（三元运算符）：
                # 如果 len(body_text) > 80 就截取前 80 字符加 "...", 否则用完整 body_text。
                "content": _normalize_text(caption or (body_text[:80] + "..." if len(body_text) > 80 else body_text)),
                # "chunk_type": 分块类型，原始类型 "table" 或 "chart"。
                "chunk_type": typ,
                # "section_path": 章节路径，从标题中提取。
                "section_path": _extract_section(item.get("title", "")),
                # "page": 页码。
                "page": page,
                # "img_path": 图片路径（如果有）。
                "img_path": img_path,
                # "caption": 完整的标题文本。
                "caption": caption,
                # "footnote": 完整的脚注文本。
                "footnote": footnote,
                # "table_body": 如果是表格则存储 Markdown 格式的表格内容，图表则存空字符串。
                "table_body": body_text if typ == "table" else "",
            })

    # 使用日志记录器输出统计信息：原始 content_list 有多少项，生成了多少个分块。
    logger.info(f"MinerU content_list: {len(content_list)} items -> {len(chunks)} chunks")
    # 返回最终的分块列表。
    return chunks


# ===== 辅助函数：提取文本 =====
# 定义 _extract_text 函数，从 MinerU 的内容项中提取纯文本。
# item: MinerU 内容项字典
# 返回值: 提取后的文本字符串
def _extract_text(item: dict) -> str:
    # 从字典中获取 "text" 字段，可能是一个字符串，也可能是一个字符串列表。
    texts = item.get("text", "")
    # 判断 texts 是否是列表类型。
    if isinstance(texts, list):
        # 如果是列表，则用空字符串 "" 将所有元素拼接在一起。
        return "".join(texts)
    # 如果不是列表（而是字符串），则转成字符串返回。
    # 如果 texts 有内容则返回 str(texts)，否则返回空字符串 ""。
    return str(texts) if texts else ""


# ===== 辅助函数：提取章节路径 =====
# 定义 _extract_section 函数，将标题字符串解析为章节路径列表。
# 例如 "第一章 > 第一节" 会被解析为 ["第一章", "第一节"]。
# title: 标题字符串（可能包含 ">" 分隔符）
# 返回值: 章节路径列表
def _extract_section(title: str) -> list:
    # 如果 title 为空（None 或空字符串），直接返回空列表。
    if not title:
        return []
    # 使用 title.split(">") 将字符串按 ">" 分割成列表，
    # 然后遍历列表中的每个元素，用 s.strip() 去掉首尾空白字符，
    # 最后用 if s.strip() 过滤掉空白元素（如 ">" 前后的空格）。
    # 最终返回一个列表推导式的结果。
    return [s.strip() for s in title.split(">") if s.strip()]


# ===== 辅助函数：规范文本标点 =====
# 定义 _normalize_text 函数，用于规范表格/图表中的标点符号。
# 将英文标点替换为中文标点，并压缩多余的空白字符。
# text: 原始文本字符串
# 返回值: 规范化后的文本字符串
def _normalize_text(text: str) -> str:
    """规范表格/图表中的标点为中文符号，压缩空白。"""
    # 如果文本为空，直接返回空字符串。
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
    # 返回处理后的文本。
    return text


# ===== 辅助函数：HTML 表格转 Markdown =====
# 定义 _table_html_to_md 函数，用于将 HTML 格式的表格转为 Markdown 表格格式。
# html: HTML 字符串，可能包含 `<table>` 标签
# 返回值: Markdown 格式的表格文本
def _table_html_to_md(html: str) -> str:
    """将 HTML 表格转为 Markdown 表格格式。"""
    # 在函数内部导入 re 模块，这是一种延迟导入方式，减少模块加载时的开销。
    import re
    # 检查 HTML 字符串中是否包含 "<table" 标签。
    if "<table" not in html:
        # 如果没有表格标签，则直接删除所有 HTML 标签，返回纯文本。
        # re.sub(r"<[^>]+>", "", html) 匹配并删除所有以 "<" 开头、">" 结尾的标签。
        return re.sub(r"<[^>]+>", "", html).strip()

    # 使用正则表达式查找所有表格行 <tr>...</tr> 的内容。
    # re.findall() 返回所有匹配的列表，re.DOTALL 标志让 "." 也能匹配换行符。
    # 正则表达式解释：
    #   <tr[^>]*>   - 匹配 <tr> 标签及其可能的属性
    #   (.*?)       - 非贪婪匹配标签内的内容（捕获组）
    #   </tr>       - 匹配结束标签
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    # 如果没有找到任何行，则同样删除所有 HTML 标签返回纯文本。
    if not rows:
        return re.sub(r"<[^>]+>", "", html).strip()

    # 初始化一个列表，用于存储转换后的 Markdown 表格行。
    md_rows = []
    # 使用 enumerate 遍历所有行，同时获取行索引 ri 和行内容 row。
    for ri, row in enumerate(rows):
        # 在当前行中查找所有单元格 <td>...</td> 或 <th>...</th> 的内容。
        # 正则表达式解释：
        #   <t[hd][^>]*> - 匹配 <td 或 <th 标签及属性
        #   (.*?)        - 非贪婪匹配单元格内容（捕获组）
        #   </t[hd]>     - 匹配 </td> 或 </th> 结束标签
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        # 初始化一个列表，用于存储当前行中所有单元格的纯文本内容。
        md_cells = []
        # 遍历当前行中的所有单元格。
        for c in cells:
            # 清除单元格内容中的所有 HTML 标签，留下纯文本。
            clean = re.sub(r"<[^>]+>", "", c).strip()
            # 压缩单元格内容中的连续空白为单个空格。
            clean = re.sub(r"\s+", " ", clean)
            # 将处理后的单元格文本添加到 md_cells 列表中。
            md_cells.append(clean)
        # 将当前行转换为 Markdown 表格行格式：以 "| " 开头和结尾，单元格之间用 " | " 分隔。
        md_rows.append("| " + " | ".join(md_cells) + " |")

        # 表头后加分隔行
        # 如果是第一行（ri == 0），并且该行中包含 <th> 标签（即表头行），
        # re.search() 在字符串中搜索正则表达式匹配，re.IGNORECASE 忽略大小写。
        if ri == 0 and re.search(r"<th", row, re.IGNORECASE):
            # 在表头行之后添加 Markdown 分隔行，"---" 表示列与列之间的分割线，
            # 数量与单元格数量相同，用 "|" 包裹，单元格间用 " | " 分隔。
            md_rows.append("| " + " | ".join(["---"] * len(md_cells)) + " |")

    # 将所有行用换行符 "\n" 连接起来，返回完整的 Markdown 表格字符串。
    return "\n".join(md_rows)


# ===== PDF 加载器 =====
# ─── PDF 加载器 ───────────────────────────────────────────────

# 定义 MinerUPDFLoader 类，这是 MinerU PDF 解析器的入口类。
# 对外提供简单的接口，用户只需传入 PDF 文件路径即可获得解析结果。
class MinerUPDFLoader:
    """MinerU PDF 解析器入口。需要配置 mineru_api_key。"""

    # 初始化方法，接收 PDF 文件的路径作为参数。
    # file_path: PDF 文件的路径（字符串格式）
    def __init__(self, file_path: str) -> None:
        # 将传入的文件路径保存在实例属性 self.file_path 中，供后续使用。
        self.file_path = file_path

    # ===== 懒加载方法（生成器） =====
    # 定义 lazy_load 方法，它是一个生成器函数（因为使用了 yield 关键字）。
    # 生成器不会一次性返回所有结果，而是逐个 yield 产生，节省内存。
    # 返回值: Iterator[Document] 是一个迭代器，每次迭代返回一个 Document 对象。
    def lazy_load(self) -> Iterator[Document]:
        # 在方法内部导入 Document 类，避免模块顶层的循环导入问题。
        from .vector_store import Document
        # 将 self.file_path 转为 Path 对象，方便使用 pathlib 的丰富方法。
        path = Path(self.file_path)
        # 创建 MinerUClient 实例，传入 API Token（如果配置中没有则传 None）。
        client = MinerUClient(token=conf.mineru_api_key or None)
        # 构造工作目录路径：在 PDF 所在目录下创建 chunk_out 子文件夹，
        # 再用 PDF 文件名（不含扩展名）作为最内层文件夹的名称。
        work_dir = path.parent / "chunk_out" / path.stem
        # 调用客户端的 parse_pdf 方法执行完整的解析流程（上传 -> 等待 -> 下载解压），
        # 传入 PDF 路径、工作目录、模型版本和语言设置（从配置中读取）。
        out_dir = client.parse_pdf(
            path, work_dir=work_dir,
            model_version=conf.mineru_model_version,
            language=conf.mineru_language,
        )
        # 在输出目录中递归搜索所有名为 "*content_list.json" 的文件，
        # 并排除文件名包含 "v2" 的文件（旧版本格式不兼容）。
        # out_dir.rglob("*content_list.json") 递归地匹配所有子目录中的文件。
        candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
        # 如果没有找到 content_list.json 文件，说明解析结果异常。
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
        # 如果分块结果为空列表，说明没有提取到任何有效内容。
        if not chunks:
            # 抛出 RuntimeError 异常。
            raise RuntimeError(f"MinerU 切块结果为空: {path.name}")
        # 记录日志：解析完成，并显示生成了多少个分块。
        logger.info(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        # 遍历每个分块，使用 yield 逐个返回 Document 对象（生成器的特性）。
        for ch in chunks:
            # 获取分块中的文本内容，如果不存在则取空字符串。
            content_text = ch.get("content", "")
            # 如果内容为空，跳过这个分块，不生成 Document 对象。
            if not content_text:
                continue
            # 使用 yield 关键字返回一个 Document 对象。yield 类似 return，
            # 但函数的状态会被保留，下次调用时会从 yield 之后继续执行。
            yield Document(
                # page_content: 文档的文本内容，用于后续的向量化索引和检索。
                page_content=content_text,
                # metadata: 文档的元数据字典，包含来源、类型、位置等信息。
                metadata={
                    # "source": 原始 PDF 文件的路径。
                    "source": self.file_path,
                    # "pre_chunked": 标记该文档是预先分块过的（True），
                    # 后续的分块器会识别这个标记并跳过再次分块。
                    "pre_chunked": True,
                    # "chunk_type": 分块类型（text/table/chart）。
                    "chunk_type": ch.get("chunk_type", ""),
                    # "section_path": 章节路径列表。
                    "section_path": ch.get("section_path", []),
                    # "page": 页码。
                    "page": ch.get("page"),
                    # "caption": 标题文本（表格或图表的标题）。
                    "caption": ch.get("caption", ""),
                    # "footnote": 脚注文本。
                    "footnote": ch.get("footnote", ""),
                    # "img_path": 图片路径（如果有配图）。
                    "img_path": ch.get("img_path", ""),
                    # "table_body": 表格的 Markdown 格式内容。
                    "table_body": ch.get("table_body", ""),
                },
            )

    # ===== 批量加载方法 =====
    # 定义 load 方法，一次性加载所有分块并以列表形式返回。
    # 内部调用了 lazy_load 生成器，并用 list() 将生成器的所有产出收集为列表。
    # 返回值: Document 对象列表
    def load(self) -> list:
        # list(self.lazy_load()) 会遍历生成器，收集所有 yield 出来的 Document 对象，
        # 最终返回一个包含所有文档的列表。
        return list(self.lazy_load())
