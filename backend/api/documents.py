"""文档管理接口:上传/向量化/列出/清除"""
import json
import os
from typing import List

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["documents"])


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
        documents_path = f"{conf.vector_store_dir}/tmp/{username}/{documents_path}"
        system.vector_store.store_documents_from_dir(documents_path, partition=username)
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
async def clear_documents(request: Request):
    """清除当前用户自己的所有文档"""
    try:
        username = request.state.user["username"]
        system.vector_store.delete_documents_by_partition(partition=username)
        return JSONResponse(content={"message": "User documents cleared successfully"})
    except Exception as e:
        logger.error(f"Error in clear_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear_chosed_documents")
@auth_required
async def clear_chosed_documents(request: Request):
    """清除当前用户分区中指定来源的文档"""
    try:
        data = await request.json()
        username = request.state.user["username"]
        sources = data.get("sources")
        if not sources:
            raise HTTPException(status_code=400, detail="No sources provided")
        system.vector_store.delete_documents_by_sources(sources=sources, partition=username)
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
        system.record_upload(session_id, filenames)
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
            with open(save_path, "wb") as f:
                f.write(content)
            results.append({
                "filename": file.filename,
                "size": len(content),
                "content_type": file.content_type,
            })
            filenames.append(file.filename)
            # 同名文档先删旧向量，避免重复
            logger.info(f"准备删除同名文档旧向量: {file.filename}, partition={username}")
            system.vector_store.delete_documents_by_sources([file.filename], partition=username)
            system.vector_store.store_documents_from_dir(save_path, partition=username)
        # 记录上传的文件名，供生成答案时注入上下文
        system.record_upload(session_id, filenames)
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
