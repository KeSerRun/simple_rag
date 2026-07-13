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
    """列出 log 目录下所有日志文件"""
    try:
        log_dir = conf.log_path
        if not os.path.isdir(log_dir):
            return JSONResponse(content={"files": [], "log_path": log_dir})
        files = []
        for fname in os.listdir(log_dir):  # 使用os.listdir()遍历日志目录下的所有文件和子文件夹，fname是文件名
            fpath = os.path.join(log_dir, fname)  # 把目录路径和文件名拼接成完整的文件路径，赋值给fpath
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({  # 把文件信息以字典形式添加到files列表中
                    "name": fname,  # 文件的名称（如"app.log"）
                    "size": stat.st_size,  # 文件的大小（字节数），来自stat对象的st_size属性
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),  # 文件的最后修改时间：先把时间戳转为datetime对象，再转成ISO格式的字符串
                })
        files.sort(key=lambda x: x["modified"], reverse=True)  # 对文件列表按修改时间倒序排序，最新的文件排在最前面
        return JSONResponse(content={"files": files, "log_path": log_dir})
    except Exception as e:
        logger.error(f"获取日志列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 接口2: 下载日志文件 =====
@router.get("/logs/{log_file:path}/download")
@auth_required
@admin_required  # 要求用户必须是管理员
async def download_log(request: Request, log_file: str):
    """下载完整的日志文件"""
    try:
        log_dir = conf.log_path
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))  # 把日志目录和文件名拼接成完整路径，再用normpath规范化路径格式（处理../等特殊符号，防止路径穿越攻击）
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")


        filename = os.path.basename(safe_path)  # 使用os.path.basename从完整路径中提取出文件名（例如从/var/log/app.log提取出app.log）
        return FileResponse(
            safe_path,
            media_type="text/plain",
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',  # Content-Disposition设为attachment表示触发下载，filename指定下载保存的文件名
            },
        )
    except HTTPException:
        raise  # 直接重新抛出，不做额外处理（因为HTTPException本身就是正常的错误响应）
    except Exception as e:
        logger.error(f"下载日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出500服务器内部错误


# ===== 接口3: 读取日志文件内容（分页查看） =====
@router.get("/logs/{log_file:path}")
@auth_required
@admin_required  # 要求用户必须是管理员
async def read_log(
    request: Request,  # 接收HTTP请求对象
    log_file: str,
    lines: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """读取日志文件内容

    - lines:   返回行数(默认 200, 最大 5000)
    - offset:  跳过行数(默认 0)
    - 支持 ?reverse=1 从尾部读取
    """
    try:
        log_dir = conf.log_path
        # 安全校验: 防止路径穿越
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))  # 拼接并规范化路径，防止用户通过../来读取日志目录以外的文件
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")
        if safe_path.endswith(".npy"):
            raise HTTPException(status_code=403, detail="禁止读取二进制文件")

        reverse = request.query_params.get("reverse", "0") == "1"

        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:  # 以只读模式打开日志文件，指定UTF-8编码，errors="replace"表示遇到无法解码的字符时用替代字符替换而不是报错
            all_lines = f.readlines()

        total = len(all_lines)
        if reverse:
            start = max(0, total - offset - lines)  # 计算起始行号：从总行数减去offset再减去lines，但不能小于0
            end = total - offset  # 计算结束行号：总行数减去offset
            if end <= 0:
                return JSONResponse(content={"lines": [], "total": total, "file": log_file})
            chunk = all_lines[start:end]
        else:
            start = offset  # 起始行号就是offset的值
            end = offset + lines  # 结束行号是offset加上lines
            chunk = all_lines[start:end]  # 从all_lines中按[start:end]范围切片，取出对应行


        content = [line.rstrip("\n\r") for line in chunk]  # 用列表推导式遍历每一行，使用rstrip去掉行尾的换行符\n和回车符\r，得到纯文本内容

        return JSONResponse(content={
            "file": log_file,
            "total": total,
            "start": start,
            "end": min(end, total),
            "lines": content,
        })  # JSONResponse结束
    except HTTPException:
        raise  # 直接重新抛出，不做额外封装
    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出500服务器内部错误
