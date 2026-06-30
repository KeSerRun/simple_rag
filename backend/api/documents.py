"""文档管理接口:上传/向量化/列出/清除/下载"""
import glob
import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from base.config import conf
from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["documents"])


def _user_tmp_dir(username: str) -> str:
    return f"{conf.vector_store_dir}/tmp/{username}"


def _purge_files(username: str, sources: Optional[List[str]] = None):
    """清理用户暂存目录下的原文件与 MinerU 产物。

    sources=None        → 清空整个 tmp/{username}/ (含所有文件 + mineru_out/)
    sources=[...]       → 仅清掉指定文件及其对应的 mineru_out/{stem}/
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

    mineru_root = os.path.join(tmp_dir, "mineru_out")
    for src in sources:
        file_path = os.path.join(tmp_dir, src)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.info(f"已删除原文件: {file_path}")
            except Exception as e:
                logger.warning(f"删除 {file_path} 失败: {e}")
        mineru_sub = os.path.join(mineru_root, os.path.splitext(src)[0])
        if os.path.isdir(mineru_sub):
            try:
                shutil.rmtree(mineru_sub)
                logger.info(f"已删除 MinerU 产物: {mineru_sub}")
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
    """清除当前用户自己的所有文档(向量 + 原文件 + MinerU 产物)"""
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


@router.post("/clear_chosed_documents")
@auth_required
async def clear_chosed_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    """清除当前用户分区中指定来源的文档(向量 + 原文件 + 对应 MinerU 产物)"""
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
        logger.error("Invalid JSON format in clear_chosed_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clear_chosed_documents: {str(e)}")
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
):
    """上传文件并立即向量化入库到当前用户分区(任意已登录用户均可)"""
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
            # 同名上传: 先清旧 (向量 + 原文件 + MinerU 产物), 再写入新内容
            logger.info(f"准备删除同名文档旧向量: {file.filename}, partition={username}")
            system.vector_store.delete_documents_by_sources([file.filename], partition=username)
            _purge_files(username, sources=[file.filename])
            with open(save_path, "wb") as f:
                f.write(content)
            results.append({
                "filename": file.filename,
                "size": len(content),
                "content_type": file.content_type,
            })
            filenames.append(file.filename)
            system.vector_store.store_documents_from_dir(save_path, partition=username)
        # 记录上传的文件名，供生成答案时注入上下文
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
    doc_stem: str,
    img_name: str,
):
    """提供 MinerU 解析产出的图片 (供 markdown `<img>` 标签加载)。"""
    pattern = str(Path(conf.vector_store_dir) / "tmp" / "*" / "mineru_out" / doc_stem / img_name)
    candidates = glob.glob(pattern)
    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")
    target = Path(candidates[0]).resolve()
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")