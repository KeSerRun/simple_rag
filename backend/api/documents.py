"""文档管理接口:上传/向量化/列出/清除/下载"""
# 这个文件定义了"文档管理"相关的所有 API 接口，包括上传文件、把文件转成向量存入数据库、
# 列出已上传的文档、清除文档、下载文件等功能。

import glob
# 导入 glob 模块，用于查找符合特定规则的文件路径名（支持通配符 * 和 ?）

import json
# 导入 json 模块，用于处理 JSON 格式的数据（解析请求体、生成响应数据）

import jwt
# 导入 jwt 模块，用于生成和验证 JWT（JSON Web Token）令牌，用来做用户身份验证

import mimetypes
# （比如 .pdf 对应 application/pdf，浏览器根据这个决定如何打开文件）

import os

import shutil

from pathlib import Path
# 相比 os.path 更现代、更简洁

from typing import List, Optional
# 从 typing 模块导入类型提示工具：List 表示列表类型，Optional 表示可选类型

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
#   APIRouter  - 创建路由分组
#   HTTPException - 抛出 HTTP 错误响应
#   UploadFile - FastAPI 的文件上传类型

from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
#   StreamingResponse - 返回流式响应（SSE 方式，逐步推送数据给前端）

from base.config import conf
# 包含了数据库路径、密钥、存储限制等所有配置项

from base.logger import logger
# 方便调试和排查问题

from .deps import auth_required, check_user_storage_limit, system
#   auth_required            - 登录验证装饰器，加在路由函数上要求用户必须登录
#   check_user_storage_limit - 检查用户存储空间是否超限的函数
#   system                   - 系统核心对象，包含向量存储、数据存储等功能

router = APIRouter(prefix="/api", tags=["documents"])
# 创建一个 APIRouter 实例，所有通过这个 router 注册的路由都会自动加上 "/api" 前缀
# tags=["documents"] 表示在 API 文档（Swagger）中这些接口归类到 "documents" 分组下


def _user_upload_dir(username: str) -> str:
    # Windows 文件系统不区分大小写，统一转小写避免用户目录冲突
    return f"{conf.data_dir}/uploads/{username.lower()}"


def _purge_files(username: str, sources: Optional[List[str]] = None):
    #   username - 字符串，用户名
    #   sources  - 可选，字符串列表，指定要清理哪些文件
    #             为 None 时清理该用户的所有文件，为列表时只清理列表中的文件

    """清理用户暂存目录下的原文件与 chunk 产物。

    sources=None        → 清空整个 tmp/{username}/ (含所有文件 + chunk_out/)
    sources=[...]       → 仅清掉指定文件及其对应的 chunk_out/{stem}/
    """
    # 如果 sources 是 None，就删除用户目录下所有内容（整个文件夹都删掉）
    # 如果 sources 是列表，只删除列表中的文件以及对应的 chunk 产物

    upload_dir = _user_upload_dir(username)

    if not os.path.isdir(upload_dir):
        return

    if sources is None:
        # 如果 sources 为 None，表示要清空整个用户目录
        try:
            shutil.rmtree(upload_dir)
            # 用 shutil.rmtree() 递归删除整个目录及其所有子文件和子目录
            logger.info(f"已清空用户暂存目录: {upload_dir}")
        except Exception as e:
            # 如果删除过程中发生任何异常（比如权限不足、文件被占用等）
            logger.warning(f"清空 {upload_dir} 失败: {e}")
            # 记录 WARNING 级别的日志，提示删除失败及原因
        return

    # 如果不是全量清除，只清除指定文件
    chunk_root = os.path.join(upload_dir, "chunk_out")

    for src in sources:
        # 遍历 sources 列表中的每个文件名
        file_path = os.path.join(upload_dir, src)
        # 拼接出原始文件的完整路径：上传目录 + 文件名
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                # 如果是文件，就删除它
                logger.info(f"已删除原文件: {file_path}")
                # 记录日志
            except Exception as e:
                # 删除失败时
                logger.warning(f"删除 {file_path} 失败: {e}")
              

        # 清理对应的 chunk 产物目录
        mineru_sub = os.path.join(chunk_root, os.path.splitext(src)[0])
        # os.path.splitext(src)[0] 是去掉文件扩展名后的文件名
        # 例如 "demo.pdf" → "demo"
        # 然后拼接出 chunk 产物目录路径：chunk_out/demo/
        if os.path.isdir(mineru_sub):
            # 判断该目录是否存在
            try:
                shutil.rmtree(mineru_sub)
                # 递归删除整个 chunk 产物目录
                logger.info(f"已删除 chunk 产物: {mineru_sub}")
                # 记录日志
            except Exception as e:
                # 删除失败时
                logger.warning(f"删除 {mineru_sub} 失败: {e}")
              


@router.post("/add_documents")

@auth_required
# 使用 auth_required 装饰器，要求请求必须携带有效的登录令牌

async def add_documents(request: Request):
    # request: FastAPI 的 Request 对象，包含请求的所有信息（请求体、请求头等）

    """添加文档到检索器(任意已登录用户均可,仅作用于自己的分区)"""
    # 但每个用户只能管理自己的分区，不会影响其他用户的数据

    try:
        # 开始 try 块，捕获可能发生的异常
        data = await request.json()
        # 从请求体中解析 JSON 数据，await 表示异步等待

        username = request.state.user["username"]
        # request.state.user 是由 auth_required 装饰器在验证令牌后设置的

        documents_path = data.get("documents_path")

        if not documents_path:
            # 如果 documents_path 为空或不存在
            raise HTTPException(status_code=400, detail="No documents provided")
            # 抛出 HTTP 400 错误（客户端请求错误），提示未提供文档路径

        # 路径穿越防护
        upload_root = Path(conf.data_dir) / "uploads" / username.lower()

        try:
            target = (upload_root / documents_path).resolve()
            # 拼接用户的 documents_path 到 upload_root 根目录下
            # .resolve() 解析出真实的绝对路径（处理 .. 和符号链接等）
            target.relative_to(upload_root.resolve())
            # 检查 target 是否在 upload_root 目录之内
            # 如果 documents_path 包含 "../" 试图跳到目录外，这里会抛出 ValueError
        except (ValueError, OSError):
            # 如果路径不在允许范围内，或者路径解析出错
            raise HTTPException(status_code=403, detail="forbidden")
            # 抛出 HTTP 403 错误（禁止访问），防止目录穿越攻击

        if not target.exists():
            # 检查目标路径是否存在
            raise HTTPException(status_code=400, detail="path not found")
            # 如果不存在，抛出 HTTP 400 错误，提示路径未找到

        system.vector_store.store_documents_from_dir(str(target), partition=username)
        # 调用向量存储对象的方法，从指定目录读取文档并存入向量库

        return JSONResponse(content={"message": "Documents added successfully"})

    except json.JSONDecodeError:
        # 捕获 JSON 解析错误（请求体不是合法的 JSON 格式）
        logger.error("添加文档请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"添加文档失败: {e}")


@router.post("/clear_documents")
# 注册 POST 请求路由，路径为 /api/clear_documents

@auth_required
# 要求用户必须登录

async def clear_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    # 异步函数，清除当前用户所有文档
    # request: 请求对象
    #   Header(None, alias="X-Session-ID") 表示：
    #   - 从名为 "X-Session-ID" 的请求头中取值

    """清除当前用户自己的所有文档(向量 + 原文件 + chunk 产物)"""
    # 函数说明：删除当前用户的向量数据、原始上传文件、以及解析产出的 chunk 文件

    try:
        username = request.state.user["username"]

        system.vector_store.delete_documents_by_partition(partition=username)
        # 调用向量存储的方法，删除该用户分区下的所有向量数据

        _purge_files(username, sources=None)
        # 调用辅助函数，sources=None 表示清空该用户的所有原始文件和 chunk 产物

        session_id = x_session_id or request.cookies.get("session_id")

        if session_id:
            # 如果 session_id 存在
            system.data_store.insert_session_event(session_id, 'delete_all', [])

        return JSONResponse(content={"message": "User documents cleared successfully"})

    except Exception as e:
        logger.error(f"清除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear_chosen_documents")
# 注册 POST 请求路由，路径为 /api/clear_chosen_documents

@auth_required
# 要求用户必须登录

async def clear_chosen_documents(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    # 异步函数，清除用户指定的部分文档

    """清除当前用户分区中指定来源的文档(向量 + 原文件 + 对应 chunk 产物)"""

    try:
        data = await request.json()

        username = request.state.user["username"]

        sources = data.get("sources")

        if not sources:
            # 如果 sources 为空或不存在
            raise HTTPException(status_code=400, detail="No sources provided")

        system.vector_store.delete_documents_by_sources(sources=sources, partition=username)
        # 调用向量存储的方法，根据文件名列表删除对应的向量数据

        _purge_files(username, sources=sources)
        # 调用辅助函数，只清理 sources 列表中指定的原始文件和 chunk 产物

        session_id = x_session_id or request.cookies.get("session_id")

        if session_id:
            # 如果 session_id 存在
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
# 注册 POST 请求路由，路径为 /api/upload

@auth_required
# 要求用户必须登录

async def upload_file(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
):
    # 异步函数，上传文件到用户暂存目录
    # files: UploadFile 类型的列表，File(...) 表示这是一个必须的文件上传字段
    #   UploadFile 是 FastAPI 提供的文件上传类型，包含文件名、内容类型等属性

    """上传文件到当前用户的暂存目录(任意已登录用户均可)"""

    try:
        username = request.state.user["username"]

        session_id = x_session_id or request.cookies.get("session_id")

        if not session_id:
            # 如果 session_id 不存在
            raise HTTPException(status_code=400, detail="缺少 session_id")

        results = []

        filenames = []

        import os

        for file in files:
            content = await file.read()
            # 异步读取文件内容到内存中，content 是字节数据

            basename = os.path.basename(file.filename)

            if not basename.lower().endswith('.pdf'):
                raise HTTPException(status_code=400, detail=f"仅支持 PDF 文件，收到: {basename}")

            save_path = f"{conf.data_dir}/uploads/{username.lower()}/{basename}"
            # 构造文件保存路径：配置目录/uploads/用户名/文件名

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            # os.makedirs() 递归创建目录，exist_ok=True 表示如果目录已存在也不报错

            with open(save_path, "wb") as f:
                # 以二进制写入模式打开文件
                # "wb" 表示以二进制格式写入（覆盖已存在的文件）
                f.write(content)

            results.append({
                # 将文件信息添加到 results 列表
                "filename": basename,
                # 文件名
                "size": len(content),
                # 文件大小（字节数）
                "content_type": file.content_type,
                # 文件的 MIME 类型（如 application/pdf、image/png 等）
            })

            filenames.append(basename)
            # 将文件名添加到 filenames 列表

        if filenames:
            # 如果有文件上传成功
            system.data_store.insert_session_event(session_id, 'upload', filenames)
            # 记录上传事件到数据存储中

        return JSONResponse(content={"files": results})

    except HTTPException:
        # 捕获 HTTPException
        raise
        # 重新抛出

    except Exception as e:
        logger.error(f"上传文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload_embeddings")
# 注册 POST 请求路由，路径为 /api/upload_embeddings

@auth_required
# 要求用户必须登录

async def upload_embeddings(
    request: Request,
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(None, alias="X-Session-ID"),
    stream: bool = Query(False, description="是否 SSE 流式返回处理进度"),
):
    #   如果为 True，使用 SSE (Server-Sent Events) 技术逐步返回处理进度
    #   SSE 允许服务器向客户端推送数据，适合长时间操作

    """上传文件并立即向量化入库到当前用户分区(任意已登录用户均可)"""

    username = request.state.user["username"]

    session_id = x_session_id or request.cookies.get("session_id")

    if not session_id:
        # 如果 session_id 不存在
        raise HTTPException(status_code=400, detail="缺少 session_id")

    # 先把所有文件内容读入内存（需要实际大小才能检查存储上限）
    files_data = []

    total_upload_bytes = 0

    import os

    for file in files:
        content = await file.read()
        # 异步读取文件内容
        # 丢弃目录层级，只保留文件名
        basename = os.path.basename(file.filename)

        if not basename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail=f"仅支持 PDF 文件，收到: {basename}")

        files_data.append((basename, content, file.content_type))
        # 将文件信息以元组形式添加到 files_data 列表
        # 元组包含三个元素：(文件名, 文件内容, 文件类型)

        total_upload_bytes += len(content)
        # 累加文件字节数到总大小

    # 检查用户存储上限（admin 不受限制）
    role = request.state.user.get("role", "user")
    # admin 角色不受存储限制

    ok, current_mb, max_mb = check_user_storage_limit(username, role, total_upload_bytes)
    # 调用检查函数，传入用户名、角色、本次上传总字节数
    #   ok        - 布尔值，是否在存储限制内
    #   current_mb - 当前已使用的存储空间（MB）
    #   max_mb    - 允许的最大存储空间（MB）

    if not ok:
        # 如果超出存储限制
        raise HTTPException(
            status_code=413,
            detail=f"存储空间不足：已用 {current_mb}MB / 上限 {max_mb}MB，请清理旧文档后再上传",
        )

    if stream:
        # 如果请求了流式处理模式
        return StreamingResponse(
            _upload_sse_generator(username, session_id, files_data),
            # 它会逐步处理文件并通过 SSE 事件推送进度
            media_type="text/event-stream",
        )

    # 非流式：保持向后兼容的阻塞模式
    try:
        results = []
        # 初始化结果列表

        filenames = []
        # 初始化文件名列表

        for filename, content, _ct in files_data:
            # 遍历所有文件数据
            # _ct 是 content_type，以下划线开头表示"内部使用，不直接访问"的约定
            save_path = f"{conf.data_dir}/uploads/{username.lower()}/{filename}"
            # 构造文件保存路径

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            logger.info(f"准备删除同名文档旧向量: {filename}, partition={username}")
            # 记录日志：准备删除同名文档的旧向量数据

            system.vector_store.delete_documents_by_sources([filename], partition=username)

            _purge_files(username, sources=[filename])
            # 清理同名的原始文件和 chunk 产物

            with open(save_path, "wb") as f:
                # 以二进制写入模式打开文件
                f.write(content)
                # 将文件内容写入磁盘

            results.append({"filename": filename, "size": len(content), "content_type": _ct})
            # 记录处理结果

            filenames.append(filename)
            # 记录文件名

            system.vector_store.store_documents_from_dir(save_path, partition=username)
            # 从文件路径读取文档，进行向量化并存入当前用户的分区

        if filenames:
            # 如果有文件处理成功
            system.data_store.insert_session_event(session_id, 'upload', filenames)
            # 记录上传事件

        return JSONResponse(content={"files": results})

    except HTTPException:
        # 捕获 HTTPException
        raise
        # 重新抛出

    except Exception as e:
        logger.error(f"上传向量化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{username}")
# 注册 GET 请求路由，路径为 /api/documents/{username}

@auth_required
# 要求用户必须登录

async def get_documents(request: Request, username: str):

    """获取当前用户分区下的文档列表(路径参数 username 仅用于路由兼容,实际以 token 为准)"""
    # 函数说明：虽然 URL 中有 username 参数，但实际以登录令牌中的用户名为准

    try:
        token_username = request.state.user["username"]

        documents = system.vector_store.get_documents_by_partition(partition=token_username)

        return JSONResponse(content={"documents": documents})

    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/storage/info")
# 注册 GET 请求路由，路径为 /api/documents/storage/info
# 这个路由定义在 /documents/{username} 之后，但 FastAPI 会优先匹配精确路径
# 所以不会和上面的 {username} 路由冲突

@auth_required
# 要求用户必须登录

async def get_storage_info(request: Request):

    """获取当前用户的存储使用情况"""

    try:
        username = request.state.user["username"]

        role = request.state.user.get("role", "user")

        from .deps import check_user_storage_limit

        ok, current_mb, max_mb = check_user_storage_limit(username, role)
        # 此时只查询当前使用量，不检查是否能容纳新文件

        return JSONResponse(content={
            "current_mb": current_mb,
            "max_mb": max_mb,
            # 存储上限（MB）
            "limit_enabled": max_mb > 0 and role != "admin",
            # 是否启用了存储限制：
            #   - 上限大于 0（有配额限制）
            #   - 不是 admin 角色（管理员不受限）
            "ok": ok,
            # 是否在限制范围内
        })

    except Exception as e:
        # 捕获所有异常
        # 静默失败，不阻塞前端
        return JSONResponse(content={"current_mb": 0, "max_mb": 0, "limit_enabled": False, "ok": True})


@router.get("/documents/file/{filename:path}")
# 注册 GET 请求路由，路径为 /api/documents/file/{filename:path}
# {filename:path} 表示 filename 可以包含路径分隔符（斜杠）

@auth_required
# 要求用户必须登录

async def download_document(request: Request, filename: str):
    # 异步函数，下载或预览用户上传过的文件
    # filename: 文件名（可包含路径）

    """返回当前用户上传过的原文件, 浏览器可直接打开 (PDF inline) 或下载。

    路径穿越防护: 解析后的真实路径必须在用户暂存目录下。
    """
    # - 实现了路径穿越防护，防止用户通过 ../ 等技巧访问目录外的文件

    username = request.state.user["username"]

    upload_root = Path(_user_upload_dir(username)).resolve()
    # .resolve() 解析为绝对路径

    try:
        target = (upload_root / filename).resolve()
        # 拼接路径：上传目录 + 文件名
        # .resolve() 解析真实路径（处理 ../ 等）
    except Exception:
        # 如果路径拼接或解析出错
        raise HTTPException(status_code=400, detail="invalid filename")

    # 必须在用户暂存目录里, 不能逃出
    try:
        target.relative_to(upload_root)
        # 检查 target 是否在 upload_root 目录内
        # 如果 target 不在 upload_root 下（比如用了 ../ 跳出去了），会抛出 ValueError
    except ValueError:
        # 如果路径逃出了用户目录
        raise HTTPException(status_code=403, detail="forbidden")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    # 根据文件扩展名猜测 MIME 类型
    # 例如：.pdf → "application/pdf"，.png → "image/png"
    # 如果无法识别，默认使用 "application/octet-stream"（通用二进制流）

    # inline: 浏览器能预览的类型 (PDF/图片/文本) 直接在新标签打开, 其它类型仍会自动下载
    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline",
        # content_disposition_type="inline" 表示浏览器尽可能在内部预览
    )


@router.get("/documents/image/{doc_stem}/{img_name:path}")
# 注册 GET 请求路由，路径为 /api/documents/image/{doc_stem}/{img_name:path}
# doc_stem: 文档名（不含扩展名）
# img_name: 图片文件名（可包含路径）

async def serve_mineru_image(
    request: Request,
    doc_stem: str,
    img_name: str,
    token: str = Query(None),
):
    # 异步函数，提供 MinerU 解析产出的图片
    # 这个接口没有 @auth_required 装饰器，因为它需要在 <img> 标签中被加载

    """提供 MinerU 解析产出的图片。支持 ?token= 参数供 <img> 标签加载。"""

    # 验证 token: header 优先, query param 兜底
    auth_token = token

    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        # 如果 Authorization 请求头存在，且以 "Bearer " 开头
        # Bearer Token 是 JWT 的常用传递方式
        auth_token = auth_header.split(" ", 1)[1]
        # 提取 "Bearer " 后面的令牌内容

    if auth_token:
        # 如果存在验证令牌
        try:
            payload = jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])
            # 使用 jwt 库解码令牌
            # auth_token.encode("utf-8") 将字符串转为字节
            # conf.jwt_secret_key 是 JWT 签名密钥
            # algorithms=["HS256"] 使用 HS256 算法验证签名

            request.state.user = payload
        except jwt.PyJWTError:
            # 如果令牌验证失败（过期、签名错误等）
            raise HTTPException(status_code=401, detail="invalid token")

    base_dir = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / doc_stem
    # 构造基础搜索路径
    # "*" 是通配符，代表任意用户名
    # 所以路径模式是：数据目录/uploads/*/chunk_out/文档名
    # 使用通配符是因为不确定图片属于哪个用户

    # 1) 精确匹配
    candidates = glob.glob(str(base_dir / img_name))
    # 使用 glob 模块搜索与 img_name 精确匹配的文件

    # 2) 前缀匹配 (hash 被截断)
    if not candidates:
        # 如果精确匹配没有找到
        candidates = sorted(glob.glob(str(base_dir / f"{img_name}*")))
        # 尝试前缀匹配：在 img_name 后面加 *，匹配所有以 img_name 开头的文件
        # sorted() 排序，保证结果有序

    # 3) 容错: LLM 可能在 doc_stem 后加了 .pdf 等扩展名
    if not candidates and "." in doc_stem:
        # 如果还没找到，且 doc_stem 中包含点号（表示可能有扩展名）
        stem_clean = doc_stem.rsplit(".", 1)[0]
        # 从右侧分割一次，去掉扩展名部分
        # 例如 "report.pdf" → "report"
        base_dir2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / stem_clean
        # 使用去掉扩展名后的文档名重新构造搜索路径
        candidates = sorted(glob.glob(str(base_dir2 / f"{img_name}*")))
        # 再次搜索

    # 4) 容错: 实际目录名比 doc_stem 多了下划线等后缀
    if not candidates:
        # 如果仍然没找到
        base_dir_fuzzy = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
        # 使用模糊匹配：在 doc_stem 后加 *，匹配以 doc_stem 开头的所有目录
        candidates = sorted(glob.glob(str(base_dir_fuzzy / img_name)))
        # 在匹配到的目录中找 img_name
        if not candidates:
            candidates = sorted(glob.glob(str(base_dir_fuzzy / f"{img_name}*")))
            # 如果还没找到，同时使用目录模糊 + 文件名前缀匹配

        # 容错: doc_stem 带扩展名时去掉扩展名再试
        if not candidates and "." in doc_stem:
            # 如果还没找到，且 doc_stem 可能带扩展名
            stem_clean = doc_stem.rsplit(".", 1)[0]
            # 去掉扩展名
            base_dir_fuzzy2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
            candidates = sorted(glob.glob(str(base_dir_fuzzy2 / img_name)))
            # 搜索精确文件名
            if not candidates:
                candidates = sorted(glob.glob(str(base_dir_fuzzy2 / f"{img_name}*")))

    # 5) 容错: 取 images/ 目录下第一张图 (hash 被编造)
    if not candidates and "/" in img_name:
        # 如果还没找到，且 img_name 包含斜杠（表示带子路径）
        prefix = img_name.rsplit("/", 1)[0]
        candidates = sorted(glob.glob(str(base_dir / prefix / "*")))
        # 在匹配的目录下搜索所有文件（取第一张图）
        if not candidates:
            # 结合目录模糊匹配
            base_dir_fuzzy = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
            candidates = sorted(glob.glob(str(base_dir_fuzzy / prefix / "*")))

        # 容错: doc_stem 带扩展名(如 .pdf)时去掉扩展名再试
        if not candidates and "." in doc_stem:
            # 如果还没找到，且 doc_stem 可能带扩展名
            stem_clean = doc_stem.rsplit(".", 1)[0]
            # 去掉扩展名
            base_dir_extless = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / stem_clean
            candidates = sorted(glob.glob(str(base_dir_extless / prefix / "*")))
            # 搜索所有文件
            if not candidates:
                base_dir_fuzzy2 = Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
                # 使用模糊匹配（去掉扩展名）
                candidates = sorted(glob.glob(str(base_dir_fuzzy2 / prefix / "*")))
                # 搜索所有文件

    if not candidates:
        # 经过所有匹配策略后还是没找到
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()
    # candidates[0] 是最符合条件的匹配结果

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")


@router.get("/documents/image/{img_name:path}")
# 注册 GET 请求路由，路径为 /api/documents/image/{img_name:path}

async def serve_mineru_image_global(
    request: Request,
    img_name: str,
    token: str = Query(None),
):
    # 异步函数，全局搜索 MinerU 图片
    # 会在所有用户的 chunk_out 目录中搜索

    """全局搜索 MinerU 图片。当前端无法提供正确的 doc_stem，仅有图片 hash 时使用。"""

    # 验证 token: header 优先, query param 兜底
    auth_token = token

    auth_header = request.headers.get("Authorization")

    if auth_header and auth_header.startswith("Bearer "):
        # 如果 Authorization 请求头存在且格式正确
        auth_token = auth_header.split(" ", 1)[1]
        # 提取令牌内容

    if auth_token:
        # 如果令牌存在
        try:
            payload = jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])
            request.state.user = payload
        except jwt.PyJWTError:
            # 令牌验证失败
            raise HTTPException(status_code=401, detail="invalid token")

    img_name = img_name.rstrip("/")
    # 去掉 img_name 末尾的斜杠，防止路径匹配问题

    # 如果 img_name 里面带了 "images/" 前缀，先去掉以便统一处理
    if img_name.startswith("images/"):
        img_name = img_name[7:]
        # 去掉前 7 个字符 "images/"，只保留文件名部分

    # 全局搜索该图片
    # pattern: uploads/*/chunk_out/*/images/{img_name}
    search_pattern = str(Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / img_name)
    # 构造全局搜索模式：
    # 数据目录/uploads/任意用户名/chunk_out/任意文档名/images/图片名
    # 两个 * 通配符分别匹配任意用户名和任意文档名

    candidates = sorted(glob.glob(search_pattern))
    # 使用 glob 搜索匹配的图片文件，并按字母顺序排序

    if not candidates:
        # 如果精确匹配未找到
        # 尝试去掉扩展名进行前缀匹配 (hash 可能被截断)
        name_without_ext = img_name.rsplit(".", 1)[0] if "." in img_name else img_name
        # 如果文件名包含点号（扩展名），去掉扩展名
        # 例如 "abc123.png" → "abc123"
        # 如果不含点号，保持原样

        search_pattern_fuzzy = str(Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / f"{name_without_ext}*")
        # 构造模糊匹配模式：在文件名后面加 *
        # 匹配所有以 name_without_ext 开头的文件
        candidates = sorted(glob.glob(search_pattern_fuzzy))
        # 搜索并排序

    if not candidates:
        # 如果仍然没找到
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    # 猜测 MIME 类型

    return FileResponse(path=str(target), media_type=media_type, filename=target.name, content_disposition_type="inline")


def _upload_sse_generator(username: str, session_id: str, files_data: list):
    # 定义一个生成器函数，用于 SSE（Server-Sent Events）流式返回处理进度
    #   username   - 用户名
    #   session_id - 会话 ID
    #   files_data - 文件数据列表，每个元素是 (文件名, 内容, 内容类型) 元组

    """SSE 生成器：上传处理各阶段状态事件。"""

    import json as _json

    from rag.vector_store import process_documents_from_dir
    # process_documents_from_dir 负责解析文件内容（如 PDF 解析）

    results = []

    filenames = []

    error_count = 0

    def _sse(data: dict) -> str:
        # 内部辅助函数，将字典格式的数据格式化为 SSE 事件字符串

        return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"
        # SSE 格式要求：
        # - 以 "data: " 开头
        # - 后面跟 JSON 格式的数据
        # - ensure_ascii=False 保留中文字符，不转义为 \uXXXX
        # - 以两个换行符结尾 (\n\n)

    saved_files = []  # [(filename, save_path, content_len, content_type)]
    for idx, (filename, content, _ct) in enumerate(files_data):
        save_path = f"{conf.data_dir}/uploads/{username.lower()}/{filename}"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        yield _sse({"status": "uploading", "text": "文档上传", "file": filename, "progress": f"{idx+1}/{len(files_data)}"})

        system.vector_store.delete_documents_by_sources([filename], partition=username)
        _purge_files(username, sources=[filename])

        with open(save_path, "wb") as f:
            f.write(content)
        saved_files.append((filename, save_path, len(content), _ct))

    # 阶段 2-3: 并发解析 + 向量化（最多 3 个并行）
    yield _sse({"status": "info", "text": f"开始并行处理 {len(saved_files)} 个文件..."})

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

    with ThreadPoolExecutor(max_workers=conf.parse_workers) as pool:
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

    # 所有文件处理完毕
    if filenames:
        system.data_store.insert_session_event(session_id, 'upload', filenames)

    # 发送最终状态
    if error_count > 0 and not results:
        # 如果所有文件都处理失败（错误数 > 0 且成功数为 0）
        yield _sse({"status": "done", "text": "所有文件均处理失败", "files": results})
        # 发送"全部失败"事件

    elif error_count > 0:
        # 如果有部分文件失败（有成功也有失败）
        yield _sse({"status": "done", "text": f"入库完成，{error_count} 个文件失败", "files": results})
        # 发送"部分失败"事件，告知失败数量

    else:
        # 所有文件都成功
        yield _sse({"status": "done", "text": "入库成功", "files": results})
        # 发送"全部成功"事件
