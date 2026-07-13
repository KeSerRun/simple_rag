"""管理后台 API - 日志查看"""
import os
from datetime import datetime

from . import router
from ..deps import admin_required, auth_required
from base.config import conf
from base.logger import logger

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

@router.get("/logs")
@auth_required
@admin_required
async def list_logs(request: Request):
    """列出 log 目录下所有日志文件。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"files": [{"name": str, "size": int, "modified": str}, ...], "log_path": str}``,
        按修改时间倒序排列。

    Raises:
        HTTPException 500: 读取目录失败。
    """
    try:
        log_dir = conf.log_path
        if not os.path.isdir(log_dir):
            return JSONResponse(content={"files": [], "log_path": log_dir})
        files = []
        for fname in os.listdir(log_dir):
            fpath = os.path.join(log_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
        return JSONResponse(content={"files": files, "log_path": log_dir})
    except Exception as e:
        logger.error(f"获取日志列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{log_file:path}/download")
@auth_required
@admin_required
async def download_log(request: Request, log_file: str):
    """下载完整的日志文件。

    # ── 安全

    路径穿越防护:解析后的真实路径必须在 log_dir 下。

    Args:
        request: FastAPI 请求对象。
        log_file: 日志文件路径(相对于 log_dir)。

    Returns:
        FileResponse: 以附件形式返回日志文件(text/plain)。

    Raises:
        HTTPException 403: 路径穿越尝试。
        HTTPException 404: 文件不存在。
        HTTPException 500: 下载失败。
    """
    try:
        log_dir = conf.log_path
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")


        filename = os.path.basename(safe_path)
        return FileResponse(
            safe_path,
            media_type="text/plain",
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{log_file:path}")
@auth_required
@admin_required
async def read_log(
    request: Request,
    log_file: str,
    lines: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """读取日志文件内容。

    # ── 参数说明

    - lines: 返回行数(默认 200, 最大 5000)
    - offset: 跳过行数(默认 0)
    - 支持 ``?reverse=1`` 从尾部读取

    # ── 安全

    路径穿越防护;禁止读取 .npy 二进制文件。

    Args:
        request: FastAPI 请求对象(用于读取 query 参数 ``reverse``)。
        log_file: 日志文件路径(相对于 log_dir)。
        lines: 返回行数,默认 200。
        offset: 跳过行数,默认 0。

    Returns:
        JSONResponse: ``{"file": str, "total": int, "start": int, "end": int, "lines": [...]}``。

    Raises:
        HTTPException 403: 路径穿越或二进制文件。
        HTTPException 404: 文件不存在。
        HTTPException 500: 读取失败。
    """
    try:
        log_dir = conf.log_path
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")
        if safe_path.endswith(".npy"):
            raise HTTPException(status_code=403, detail="禁止读取二进制文件")

        reverse = request.query_params.get("reverse", "0") == "1"

        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total = len(all_lines)
        if reverse:
            start = max(0, total - offset - lines)
            end = total - offset
            if end <= 0:
                return JSONResponse(content={"lines": [], "total": total, "file": log_file})
            chunk = all_lines[start:end]
        else:
            start = offset
            end = offset + lines
            chunk = all_lines[start:end]


        content = [line.rstrip("\n\r") for line in chunk]

        return JSONResponse(content={
            "file": log_file,
            "total": total,
            "start": start,
            "end": min(end, total),
            "lines": content,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
