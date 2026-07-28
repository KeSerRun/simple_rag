"""文档管理接口:上传/向量化/列出/清除/下载"""

import glob

import json

import jwt
import re

import mimetypes

import os

import shutil

from pathlib import Path

from typing import List, Optional

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile

from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from base.config import conf

from base.logger import logger

from .deps import auth_required, check_user_storage_limit, system

router = APIRouter(prefix="/api", tags=["documents"])


def _user_upload_dir(username: str) -> str:
    """返回指定用户的暂存目录路径。

    Args:
        username: 用户名(自动转小写)。

    Returns:
        str: ``{conf.data_dir}/uploads/{username}/``。
    """
    return f"{conf.data_dir}/uploads/{username.lower()}"


def _purge_files(username: str, sources: Optional[List[str]] = None):
    """清理用户暂存目录下的原文件与 chunk 产物。

    # ── 清理策略

    - ``sources=None``: 清空整个 ``{upload_dir}/`` (含所有文件 + chunk_out/)
    - ``sources=[...]``: 仅清掉指定文件及其对应的 ``chunk_out/{stem}/``

    Args:
        username: 用户名。
        sources: 要清理的源文件名列表。None 表示全部清理。
    """

    upload_dir = _user_upload_dir(username)

    if not os.path.isdir(upload_dir):
        return

    if sources is None:
        try:
            shutil.rmtree(upload_dir)
            logger.info(f"已清空用户暂存目录: {upload_dir}")
        except Exception as e:
            logger.warning(f"清空 {upload_dir} 失败: {e}")
        return

    chunk_root = os.path.join(upload_dir, "chunk_out")

    for src in sources:
        file_path = os.path.join(upload_dir, src)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.info(f"已删除原文件: {file_path}")
            except Exception as e:
                logger.warning(f"删除 {file_path} 失败: {e}")
            

        mineru_sub = os.path.join(chunk_root, os.path.splitext(src)[0])
        if os.path.isdir(mineru_sub):
            try:
                shutil.rmtree(mineru_sub)
                logger.info(f"已删除 chunk 产物: {mineru_sub}")
            except Exception as e:
                logger.warning(f"删除 {mineru_sub} 失败: {e}")
            


_ILLEGAL_CHARS = re.compile(r'[\x00-\x1f\\/:*?"<>|]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_MAX_FILENAME_BYTES = 200


def _sanitize_filename(raw: str) -> str:
    """清理上传文件名：去路径、去非法字符、去尾部空格/点、长度限制、拒绝保留名称。

    Args:
        raw: 用户传入的原始文件名。

    Returns:
        清理后的安全文件名。

    Raises:
        HTTPException 400: 清理后文件名为空或不合法。
    """
    # 1. 只取文件名最后一段
    name = os.path.basename(raw)

    # 2. 替换 ASCII 控制字符和 Windows 非法字符为下划线
    name = _ILLEGAL_CHARS.sub("_", name)

    # 3. Windows 自动修剪尾部空格和点
    name = name.rstrip(" .")

    # 4. 空名或只有扩展名
    if not name or name.startswith("."):
        raise HTTPException(status_code=400, detail=f"无效的文件名: {raw}")

    # 5. Windows 保留设备名（不区分大小写）
    stem = name.rsplit(".", 1)[0].lower()
    if stem in _WINDOWS_RESERVED:
        raise HTTPException(status_code=400, detail=f"文件名为系统保留名称: {name}")

    # 6. UTF-8 字节长度限制
    if len(name.encode("utf-8")) > _MAX_FILENAME_BYTES:
        encoded = name.encode("utf-8")[:_MAX_FILENAME_BYTES]
        name = encoded.decode("utf-8", errors="ignore").rstrip(" .")
        if not name:
            raise HTTPException(status_code=400, detail=f"文件名过长: {raw}")

    return name


@router.post("/add_documents")

@auth_required
async def add_documents(request: Request):

    """添加文档到检索器(任意已登录用户均可,仅作用于自己的分区)。

    # ── 处理流程

    1. 从 token 获取用户名
    2. 解析文档路径,做路径穿越防护(resolve + relative_to)
    3. 调用 ``system.vector_store.store_documents_from_dir`` 入库

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"documents_path": str}``。

    Returns:
        JSONResponse: ``{"message": "Documents added successfully"}``。

    Raises:
        HTTPException 400: 缺少路径、路径不存在或 JSON 无效。
        HTTPException 403: 路径穿越。
        HTTPException 500: 添加失败。
    """

    try:
        data = await request.json()

        username = request.state.user["username"]

        documents_path = data.get("documents_path")

        if not documents_path:
            raise HTTPException(status_code=400, detail="No documents provided")

        upload_root = Path(conf.data_dir) / "uploads" / username.lower()

        try:
            target = (upload_root / documents_path).resolve()
            target.relative_to(upload_root.resolve())
        except (ValueError, OSError):
            raise HTTPException(status_code=403, detail="forbidden")

        if not target.exists():
            raise HTTPException(status_code=400, detail="path not found")

        system.vector_store.store_documents_from_dir(str(target), partition=username)

        return JSONResponse(content={"message": "Documents added successfully"})

    except json.JSONDecodeError:
        logger.error("添加文档请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"添加文档失败: {e}")


@router.post("/clear_documents")

@auth_required
async def clear_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):

    """清除当前用户自己的所有文档(向量 + 原文件 + chunk 产物)。

    # ── 清理范围

    - 向量库中该分区的所有文档 (delete_documents_by_partition)
    - 暂存目录所有文件及 chunk_out/ (_purge_files all)

    Args:
        request: FastAPI 请求对象。
        x_session_id: 可选,从 ``X-Session-ID`` 头获取会话 ID,用于记录事件。

    Returns:
        JSONResponse: ``{"message": "User documents cleared successfully"}``。

    Raises:
        HTTPException 500: 清除失败。
    """

    try:
        username = request.state.user["username"]

        system.vector_store.delete_documents_by_partition(partition=username)

        _purge_files(username, sources=None)

        session_id = x_session_id or request.cookies.get("session_id")

        if session_id:
            system.data_store.insert_session_event(session_id, 'delete_all', [])

        return JSONResponse(content={"message": "User documents cleared successfully"})

    except Exception as e:
        logger.error(f"清除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear_chosen_documents")

@auth_required
async def clear_chosen_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):

    """清除当前用户分区中指定来源的文档(向量 + 原文件 + 对应 chunk 产物)。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"sources": [str, ...]}``。
        x_session_id: 可选,``X-Session-ID`` 头。

    Returns:
        JSONResponse: ``{"message": "Selected documents cleared successfully"}``。

    Raises:
        HTTPException 400: 缺少 sources 或 JSON 无效。
        HTTPException 500: 清除失败。
    """

    try:
        data = await request.json()

        username = request.state.user["username"]

        sources = data.get("sources")

        if not sources:
            raise HTTPException(status_code=400, detail="No sources provided")

        system.vector_store.delete_documents_by_sources(sources=sources, partition=username)

        _purge_files(username, sources=sources)

        session_id = x_session_id or request.cookies.get("session_id")

        if session_id:
            system.data_store.insert_session_event(session_id, 'delete', sources)

        return JSONResponse(content={"message": "Selected documents cleared successfully"})

    except json.JSONDecodeError:
        logger.error("清除文档请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"清除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")

@auth_required
async def upload_file(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
):

    """上传文件到当前用户的暂存目录(任意已登录用户均可)。

    # ── 限制

    仅支持 PDF 文件;需要提供 ``X-Session-ID`` 头或 ``session_id`` cookie。

    Args:
        request: FastAPI 请求对象。
        files: 上传文件列表(仅 PDF)。
        x_session_id: 会话 ID(可选,可从 cookie 回退)。

    Returns:
        JSONResponse: ``{"files": [{"filename": str, "size": int, "content_type": str}, ...]}``。

    Raises:
        HTTPException 400: 缺少 session_id 或非 PDF 文件。
        HTTPException 500: 上传失败。
    """

    try:
        username = request.state.user["username"]

        session_id = x_session_id or request.cookies.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")

        results = []

        filenames = []

        for file in files:
            content = await file.read()

            basename = _sanitize_filename(file.filename)

            if not basename.lower().endswith('.pdf'):
                raise HTTPException(status_code=400, detail=f"仅支持 PDF 文件，收到: {basename}")

            save_path = f"{conf.data_dir}/uploads/{username.lower()}/{basename}"

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, "wb") as f:
                f.write(content)

            results.append({
                "filename": basename,
                "size": len(content),
                "content_type": file.content_type,
            })

            filenames.append(basename)

        if filenames:
            system.data_store.insert_session_event(session_id, 'upload', filenames)

        return JSONResponse(content={"files": results})

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"上传文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload_embeddings")

@auth_required
async def upload_embeddings(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
    stream: bool = Query(False, description="是否 SSE 流式返回处理进度"),
):

    """上传文件并立即向量化入库到当前用户分区(任意已登录用户均可)。

    # ── 处理流程

    1. 上传前先检查存储配额 (check_user_storage_limit)
    2. 删除同名文档旧向量 (delete_documents_by_sources)
    3. 保存文件后立即调用 store_documents_from_dir 入库
    4. 支持 SSE 流式返回处理进度

    Args:
        request: FastAPI 请求对象。
        files: 上传文件列表(仅 PDF)。
        x_session_id: 会话 ID。
        stream: 是否以 SSE 流式返回处理进度,默认 False。

    Returns:
        JSONResponse: 非流式返回 ``{"files": [...]}``。
        StreamingResponse: 流式返回 ``text/event-stream``。

    Raises:
        HTTPException 400: 缺少 session_id 或非 PDF 文件。
        HTTPException 413: 存储空间不足。
        HTTPException 500: 处理失败。
    """

    username = request.state.user["username"]

    session_id = x_session_id or request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    files_data = []

    total_upload_bytes = 0

    for file in files:
        content = await file.read()
        basename = _sanitize_filename(file.filename)

        if not basename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail=f"仅支持 PDF 文件，收到: {basename}")

        files_data.append((basename, content, file.content_type))

        total_upload_bytes += len(content)

    role = request.state.user.get("role", "user")

    ok, current_mb, max_mb = check_user_storage_limit(username, role, total_upload_bytes)

    if not ok:
        raise HTTPException(
            status_code=413,
            detail=f"存储空间不足：已用 {current_mb}MB / 上限 {max_mb}MB，请清理旧文档后再上传",
        )

    if stream:
        return StreamingResponse(
            _upload_sse_generator(username, session_id, files_data),
            media_type="text/event-stream",
        )

    try:
        results = []

        filenames = []

        for filename, content, _ct in files_data:
            save_path = f"{conf.data_dir}/uploads/{username.lower()}/{filename}"

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            logger.info(f"准备删除同名文档旧向量: {filename}, partition={username}")

            system.vector_store.delete_documents_by_sources([filename], partition=username)

            _purge_files(username, sources=[filename])

            with open(save_path, "wb") as f:
                f.write(content)

            results.append({"filename": filename, "size": len(content), "content_type": _ct})

            filenames.append(filename)

            system.vector_store.store_documents_from_dir(save_path, partition=username)

        if filenames:
            system.data_store.insert_session_event(session_id, 'upload', filenames)

        return JSONResponse(content={"files": results})

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"上传向量化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{username}")

@auth_required
async def get_documents(request: Request, username: str):

    """获取当前用户分区下的文档列表。

    # ── 安全

    路径参数 username 仅用于路由兼容,实际以 token 为准。

    Args:
        request: FastAPI 请求对象。
        username: URL 路径参数(仅用于路由匹配,实际以 token username 查询)。

    Returns:
        JSONResponse: ``{"documents": [...]}``。

    Raises:
        HTTPException 500: 查询失败。
    """

    try:
        token_username = request.state.user["username"]

        documents = system.vector_store.get_documents_by_partition(partition=token_username)

        return JSONResponse(content={"documents": documents})

    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/storage/info")

@auth_required
async def get_storage_info(request: Request):

    """获取当前用户的存储使用情况。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"current_mb": float, "max_mb": float, "limit_enabled": bool, "ok": bool}``。
    """

    try:
        username = request.state.user["username"]

        role = request.state.user.get("role", "user")

        ok, current_mb, max_mb = check_user_storage_limit(username, role)

        return JSONResponse(content={
            "current_mb": current_mb,
            "max_mb": max_mb,
            "limit_enabled": max_mb > 0 and role != "admin",
            "ok": ok,
        })

    except Exception as e:
        return JSONResponse(content={"current_mb": 0, "max_mb": 0, "limit_enabled": False, "ok": True})


@router.get("/documents/file/{filename:path}")

@auth_required
async def download_document(request: Request, filename: str):

    """返回当前用户上传过的原文件,浏览器可直接打开(PDF inline)或下载。

    # ── 安全

    路径穿越防护: 解析后的真实路径必须在用户暂存目录下。

    Args:
        request: FastAPI 请求对象。
        filename: 文件名(可含子路径)。

    Returns:
        FileResponse: 文件响应,Content-Disposition 为 inline。

    Raises:
        HTTPException 400: 文件名字符不合法。
        HTTPException 403: 路径穿越。
        HTTPException 404: 文件不存在。
    """

    username = request.state.user["username"]

    upload_root = Path(_user_upload_dir(username)).resolve()

    try:
        target = (upload_root / filename).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")

    try:
        target.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline",
    )


@router.get("/documents/image/{doc_stem}/{img_name:path}")

async def serve_mineru_image(
    request: Request,
    doc_stem: str,
    img_name: str,
    token: str = Query(None),
):

    """提供 MinerU 解析产出的图片。

    # ── 认证

    同时支持 ``Authorization: Bearer <token>`` 头和 ``?token=`` 查询参数,
    供 HTML ``<img>`` 标签直接加载使用。

    # ── 查找策略

    逐级放宽匹配条件:
    1. 精确 ``{doc_stem}/{img_name}``
    2. 带通配符 ``{doc_stem}*``
    3. 去掉 doc_stem 扩展名再尝试
    4. img_name 含子路径时搜索 ``{doc_stem}/{prefix}/*``

    Args:
        request: FastAPI 请求对象。
        doc_stem: 文档 stem(文件名不含扩展名)。
        img_name: 图片文件名(可含子路径)。
        token: 可选 JWT token 查询参数。

    Returns:
        FileResponse: 图片文件,Content-Disposition 为 inline。

    Raises:
        HTTPException 401: token 无效。
        HTTPException 404: 图片未找到。
    """

    auth_token = token

    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]

    if not auth_token:
        raise HTTPException(status_code=401, detail="missing token")

    try:
        payload = jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])

        request.state.user = payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    base_dir = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / doc_stem

    candidates = glob.glob(str(base_dir / img_name))

    if not candidates:
        candidates = sorted(glob.glob(str(base_dir / f"{img_name}*")))

    if not candidates and "." in doc_stem:
        stem_clean = doc_stem.rsplit(".", 1)[0]
        base_dir2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / stem_clean
        candidates = sorted(glob.glob(str(base_dir2 / f"{img_name}*")))

    if not candidates:
        base_dir_fuzzy = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
        candidates = sorted(glob.glob(str(base_dir_fuzzy / img_name)))
        if not candidates:
            candidates = sorted(glob.glob(str(base_dir_fuzzy / f"{img_name}*")))

        if not candidates and "." in doc_stem:
            stem_clean = doc_stem.rsplit(".", 1)[0]
            base_dir_fuzzy2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
            candidates = sorted(glob.glob(str(base_dir_fuzzy2 / img_name)))
            if not candidates:
                candidates = sorted(glob.glob(str(base_dir_fuzzy2 / f"{img_name}*")))

    if not candidates and "/" in img_name:
        prefix = img_name.rsplit("/", 1)[0]
        candidates = sorted(glob.glob(str(base_dir / prefix / "*")))
        if not candidates:
            base_dir_fuzzy = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
            candidates = sorted(glob.glob(str(base_dir_fuzzy / prefix / "*")))

        if not candidates and "." in doc_stem:
            stem_clean = doc_stem.rsplit(".", 1)[0]
            base_dir_extless = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / stem_clean
            candidates = sorted(glob.glob(str(base_dir_extless / prefix / "*")))
            if not candidates:
                base_dir_fuzzy2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
                candidates = sorted(glob.glob(str(base_dir_fuzzy2 / prefix / "*")))

    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")


@router.get("/documents/image/{img_name:path}")

async def serve_mineru_image_global(
    request: Request,
    img_name: str,
    token: str = Query(None),
):

    """全局搜索 MinerU 图片。

    # ── 适用场景

    当前端无法提供正确的 doc_stem,仅有图片 hash 时使用。
    通过通配符 ``uploads/*/chunk_out/*/images/{img_name}`` 全局搜索。

    Args:
        request: FastAPI 请求对象。
        img_name: 图片路径(可含子路径)。
        token: 可选 JWT token 查询参数。

    Returns:
        FileResponse: 图片文件。

    Raises:
        HTTPException 401: token 无效。
        HTTPException 404: 图片未找到。
    """

    auth_token = token

    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]

    if not auth_token:
        raise HTTPException(status_code=401, detail="missing token")

    try:
        payload = jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])
        request.state.user = payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    img_name = img_name.rstrip("/")

    if img_name.startswith("images/"):
        img_name = img_name[7:]

    search_pattern = str(Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / img_name)

    candidates = sorted(glob.glob(search_pattern))

    if not candidates:
        name_without_ext = img_name.rsplit(".", 1)[0] if "." in img_name else img_name

        search_pattern_fuzzy = str(Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / f"{name_without_ext}*")
        candidates = sorted(glob.glob(search_pattern_fuzzy))

    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")


def _upload_sse_generator(username: str, session_id: str, files_data: list):

    """SSE 生成器:上传处理各阶段状态事件。

    # ── 事件流

    - ``{"status": "uploading", ...}``: 文件上传中
    - ``{"status": "parsing", ...}``: 文档解析中
    - ``{"status": "embedding", ...}``: 向量化中
    - ``{"status": "done", ...}``: 处理完成
    - ``{"status": "error", ...}``: 处理失败

    使用 ``ThreadPoolExecutor`` 并发处理文档解析和向量化,
    受 ``conf.parse_workers`` 控制并发度。

    Args:
        username: 当前用户(用于分区归属)。
        session_id: 会话 ID(用于记录事件)。
        files_data: ``[(filename, content_bytes, content_type), ...]`` 列表。

    Yields:
        str: SSE 格式的 data 行。
    """

    import json as _json

    from rag.vector_store import process_documents_from_dir

    results = []

    filenames = []

    error_count = 0

    def _sse(data: dict) -> str:

        return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"

    saved_files = []
    for idx, (filename, content, _ct) in enumerate(files_data):
        save_path = f"{conf.data_dir}/uploads/{username.lower()}/{filename}"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        yield _sse({"status": "uploading", "text": "文档上传", "file": filename, "progress": f"{idx+1}/{len(files_data)}"})

        system.vector_store.delete_documents_by_sources([filename], partition=username)
        _purge_files(username, sources=[filename])

        with open(save_path, "wb") as f:
            f.write(content)
        saved_files.append((filename, save_path, len(content), _ct))

    count = len(saved_files)
    text = f"正在处理 {count} 个文件..." if count > 1 else "正在处理文件..."
    yield _sse({"status": "info", "text": text})

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _process_one(fn, sp, usr):
        events = []
        events.append({"status": "parsing", "text": "文档解析", "file": fn})
        documents = process_documents_from_dir(sp)
        if not documents:
            events.append({"status": "error", "text": "解析失败", "file": fn})
            return events, None, None

        events.append({"status": "embedding", "text": "词嵌入", "file": fn})
        try:
            system.vector_store.add_documents(documents, partition=usr)
        except Exception as e:
            logger.error(f"文档嵌入入库失败 ({fn}): {e}")
            events.append({"status": "error", "text": f"嵌入失败: {e}", "file": fn})
            return events, None, None

        events.append({"status": "done", "text": "处理完成", "file": fn})
        return events, fn, None

    with ThreadPoolExecutor(max_workers=conf.mineru_max_concurrency) as pool:
        futures = {pool.submit(_process_one, fn, sp, username): fn for fn, sp, *_ in saved_files}
        for future in as_completed(futures):
            events, fn, _ = future.result()
            for e in events:
                yield _sse(e)
            if fn:
                results.append({"filename": fn})
                filenames.append(fn)
            else:
                error_count += 1

    if filenames:
        system.data_store.insert_session_event(session_id, 'upload', filenames)

    if error_count > 0 and not results:
        yield _sse({"status": "done", "text": "所有文件均处理失败", "files": results})

    elif error_count > 0:
        yield _sse({"status": "done", "text": f"入库完成，{error_count} 个文件失败", "files": results})

    else:
        yield _sse({"status": "done", "text": "入库成功", "files": results})



