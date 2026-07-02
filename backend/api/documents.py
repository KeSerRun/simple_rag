"""文档管理接口:上传/向量化/列出/清除/下载"""
import glob
import json
import jwt
import mimetypes
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from base.config import conf
from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["documents"])


def _user_tmp_dir(username: str) -> str:
    return f"{conf.vector_store_dir}/tmp/{username}"


def _purge_files(username: str, sources: Optional[List[str]] = None):
    """清理用户暂存目录下的原文件与 chunk 产物。

    sources=None        → 清空整个 tmp/{username}/ (含所有文件 + chunk_out/)
    sources=[...]       → 仅清掉指定文件及其对应的 chunk_out/{stem}/
    """
    tmp_dir = _user_tmp_dir(username)
    if not os.path.isdir(tmp_dir):
        return

    if sources is None:
        try:
            shutil.rmtree(tmp_dir)
            logger.info(f"已清空用户暂存目录: {tmp_dir}")
        except Exception as e:
            logger.warning(f"清空 {tmp_dir} 失败: {e}")
        return

    chunk_root = os.path.join(tmp_dir, "chunk_out")
    for src in sources:
        file_path = os.path.join(tmp_dir, src)
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


@router.post("/add_documents")
@auth_required
async def add_documents(request: Request):
    """添加文档到检索器(任意已登录用户均可,仅作用于自己的分区)"""
    try:
        data = await request.json()
        username = request.state.user["username"]
        documents_path = data.get("documents_path")
        if not documents_path:
            raise HTTPException(status_code=400, detail="No documents provided")
        # 路径穿越防护
        tmp_root = Path(conf.vector_store_dir) / "tmp" / username
        try:
            target = (tmp_root / documents_path).resolve()
            target.relative_to(tmp_root.resolve())
        except (ValueError, OSError):
            raise HTTPException(status_code=403, detail="forbidden")
        if not target.exists():
            raise HTTPException(status_code=400, detail="path not found")
        system.vector_store.store_documents_from_dir(str(target), partition=username)
        return JSONResponse(content={"message": "Documents added successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in add_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in add_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear_documents")
@auth_required
async def clear_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    """清除当前用户自己的所有文档(向量 + 原文件 + chunk 产物)"""
    try:
        username = request.state.user["username"]
        system.vector_store.delete_documents_by_partition(partition=username)
        _purge_files(username, sources=None)
        session_id = x_session_id or request.cookies.get("session_id")
        if session_id:
            system.data_store.insert_session_event(session_id, 'delete_all', [])
        return JSONResponse(content={"message": "User documents cleared successfully"})
    except Exception as e:
        logger.error(f"Error in clear_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear_chosen_documents")
@auth_required
async def clear_chosen_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    """清除当前用户分区中指定来源的文档(向量 + 原文件 + 对应 chunk 产物)"""
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
        logger.error("Invalid JSON format in clear_chosen_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clear_chosen_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
@auth_required
async def upload_file(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    """上传文件到当前用户的暂存目录(任意已登录用户均可)"""
    try:
        username = request.state.user["username"]
        session_id = x_session_id or request.cookies.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")

        results = []
        filenames = []
        for file in files:
            content = await file.read()
            save_path = f"{conf.vector_store_dir}/tmp/{username}/{file.filename}"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(content)
            results.append({
                "filename": file.filename,
                "size": len(content),
                "content_type": file.content_type,
            })
            filenames.append(file.filename)
        if filenames:
            system.data_store.insert_session_event(session_id, 'upload', filenames)
        return JSONResponse(content={"files": results})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload_embeddings")
@auth_required
async def upload_embeddings(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
    stream: bool = Query(False, description="是否 SSE 流式返回处理进度"),
):
    """上传文件并立即向量化入库到当前用户分区(任意已登录用户均可)"""
    username = request.state.user["username"]
    session_id = x_session_id or request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    # 先把所有文件内容读入内存
    files_data = []
    for file in files:
        content = await file.read()
        files_data.append((file.filename, content, file.content_type))

    if stream:
        return StreamingResponse(
            _upload_sse_generator(username, session_id, files_data),
            media_type="text/event-stream",
        )

    # 非流式：保持向后兼容的阻塞模式
    try:
        results = []
        filenames = []
        for filename, content, _ct in files_data:
            save_path = f"{conf.vector_store_dir}/tmp/{username}/{filename}"
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
        logger.error(f"Error in upload_embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{username}")
@auth_required
async def get_documents(request: Request, username: str):
    """获取当前用户分区下的文档列表(路径参数 username 仅用于路由兼容,实际以 token 为准)"""
    try:
        token_username = request.state.user["username"]
        documents = system.vector_store.get_documents_by_partition(partition=token_username)
        return JSONResponse(content={"documents": documents})
    except Exception as e:
        logger.error(f"Error in get_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/file/{filename:path}")
@auth_required
async def download_document(request: Request, filename: str):
    """返回当前用户上传过的原文件, 浏览器可直接打开 (PDF inline) 或下载。

    路径穿越防护: 解析后的真实路径必须在用户暂存目录下。
    """
    username = request.state.user["username"]
    tmp_root = Path(_user_tmp_dir(username)).resolve()
    try:
        target = (tmp_root / filename).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    # 必须在用户暂存目录里, 不能逃出
    try:
        target.relative_to(tmp_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    # inline: 浏览器能预览的类型 (PDF/图片/文本) 直接在新标签打开, 其它类型仍会自动下载
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
    """提供 MinerU 解析产出的图片。支持 ?token= 参数供 <img> 标签加载。"""
    # 验证 token: header 优先, query param 兜底
    auth_token = token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]
    if auth_token:
        try:
            payload = jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])
            request.state.user = payload
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="invalid token")

    base_dir = Path(conf.vector_store_dir) / "tmp" / "*" / "chunk_out" / doc_stem

    # 1) 精确匹配
    candidates = glob.glob(str(base_dir / img_name))
    # 2) 前缀匹配 (hash 被截断)
    if not candidates:
        candidates = sorted(glob.glob(str(base_dir / f"{img_name}*")))
    # 3) 容错: LLM 可能在 doc_stem 后加了 .pdf 等扩展名
    if not candidates and "." in doc_stem:
        stem_clean = doc_stem.rsplit(".", 1)[0]
        base_dir2 = Path(conf.vector_store_dir) / "tmp" / "*" / "chunk_out" / stem_clean
        candidates = sorted(glob.glob(str(base_dir2 / f"{img_name}*")))
    # 4) 容错: 取 images/ 目录下第一张图 (hash 被编造)
    if not candidates and "/" in img_name:
        prefix = img_name.rsplit("/", 1)[0]
        candidates = sorted(glob.glob(str(base_dir / prefix / "*")))
    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")
    target = Path(candidates[0]).resolve()
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")


def _upload_sse_generator(username: str, session_id: str, files_data: list):
    """SSE 生成器：上传处理各阶段状态事件。"""
    import json as _json
    from rag.core.document_process import process_documents_from_dir
    results = []
    filenames = []

    def _sse(data: dict) -> str:
        return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"

    for idx, (filename, content, _ct) in enumerate(files_data):
        save_path = f"{conf.vector_store_dir}/tmp/{username}/{filename}"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        yield _sse({"status": "uploading", "text": "文档上传", "file": filename})
        # 同名文档: 先清旧向量 + chunk 产物
        system.vector_store.delete_documents_by_sources([filename], partition=username)
        _purge_files(username, sources=[filename])
        with open(save_path, "wb") as f:
            f.write(content)

        yield _sse({"status": "parsing", "text": "文档解析", "file": filename})
        documents = process_documents_from_dir(save_path)
        if not documents:
            yield _sse({"status": "error", "text": "解析失败", "file": filename})
            continue

        yield _sse({"status": "embedding", "text": "词嵌入", "file": filename})
        system.vector_store.add_documents(documents, partition=username)

        results.append({"filename": filename, "size": len(content), "content_type": _ct})
        filenames.append(filename)

    if filenames:
        system.data_store.insert_session_event(session_id, 'upload', filenames)

    yield _sse({"status": "done", "text": "入库成功", "files": results})