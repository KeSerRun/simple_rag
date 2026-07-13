
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request  # APIRouter: 创建路由分组; HTTPException: 返回 HTTP 错误响应; Request: 获取请求对象
from fastapi.responses import JSONResponse  # JSONResponse: 返回 JSON 格式的 HTTP 响应

from base.logger import logger  # 导入项目的日志记录器，用于在出错时写日志
from base.config import conf

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/create_session")  # 注册 POST 请求的路由，路径为 /api/create_session
@auth_required  # 装饰器：要求请求必须携带有效的登录 token，否则直接返回 401
async def create_session(request: Request):
    """
    创建用户会话。
    请求体需要传 session_id，username 始终从 token 中获取（防止伪造他人身份建会话）。
    参数:
        request: FastAPI 请求对象，包含请求体和用户认证信息
    返回:
        成功: {"message": "Session created successfully"}
        失败: HTTP 400 或 500 错误
    """
    try:  # 开始异常捕获，防止未处理的错误导致程序崩溃
        data = await request.json()
        session_id = data.get("session_id")

        username = request.state.user["username"]

        if not session_id:
            raise HTTPException(status_code=400, detail="Missing session_id")

        if system.data_store.insert_session(session_id, username):
            return JSONResponse(content={"message": "Session created successfully"})

        raise HTTPException(status_code=400, detail="Failed to create session")

    except json.JSONDecodeError:  # 捕获 JSON 解析错误（请求体不是合法的 JSON 格式时触发）
        logger.error("创建会话请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{username}")  # 注册 GET 请求的路由，路径为 /api/sessions/{username}，{username} 是路径参数
@auth_required  # 要求请求必须携带有效的登录 token
async def get_sessions(request: Request, username: str):
    """
    获取当前登录用户的所有会话 ID 列表。
    虽然路径上有 username 参数，但实际查询时使用 token 中的 username（安全性考虑）。
    参数:
        request: FastAPI 请求对象，从中获取认证用户信息
        username: URL 路径中的用户名参数（仅用于路由兼容，实际不用它查询）
    返回:
        {"sessions": [会话ID列表]}  -  返回该用户的所有会话
        失败: HTTP 500 错误
    """
    try:  # 开始异常捕获
        token_username = request.state.user["username"]

        sessions = system.data_store.fetch_sessions_by_username(token_username)

        return JSONResponse(content={"sessions": sessions})

    except Exception as e:  # 捕获所有未预料到的异常
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")  # 注册 DELETE 请求的路由，路径为 /api/sessions/{session_id}，{session_id} 指定要删除的会话
@auth_required  # 要求请求必须携带有效的登录 token
async def delete_session(request: Request, session_id: str):
    """
    删除指定会话及其关联的历史记录。
    仅允许操作调用者自己的 session，禁止删除其他人的会话。
    参数:
        request: FastAPI 请求对象，从中获取认证用户信息
        session_id: URL 路径参数，要删除的会话 ID
    返回:
        成功: {"message": "Session and related data deleted successfully"}
        权限不足: HTTP 403
        其他错误: HTTP 500
    """
    try:  # 开始异常捕获
        username = request.state.user["username"]

        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]

        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")

        system.data_store.delete_session(session_id)
        system.data_store.delete_session_history(session_id)
        system.data_store.delete_session_tasks(session_id)
        system.data_store.delete_session_archives(session_id)

        tool_dir = Path(conf.data_dir) / "json_store" / "tool_results" / session_id
        if tool_dir.exists():
            shutil.rmtree(tool_dir)
            logger.debug(f"已清理工具结果文件: {tool_dir}")

        archive_base = Path(conf.data_dir) / "json_store" / "archives"
        if archive_base.exists():
            removed = 0
            for f in archive_base.iterdir():
                if f.suffix == ".json" and f.stem.startswith(f"arch_{session_id[:16]}"):
                    f.unlink()
                    removed += 1
            if removed:
                logger.debug(f"已清理 {removed} 个归档文件 session={session_id[:8]}")

        return JSONResponse(content={"message": "Session and related data deleted successfully"})

    except HTTPException:  # 捕获我们自己抛出的 HTTPException（如 403）
        raise  # 直接重新抛出，不做额外处理
    except Exception as e:  # 捕获所有其他未预料到的异常
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
