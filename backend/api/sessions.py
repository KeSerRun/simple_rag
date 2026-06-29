"""会话管理接口:创建/列出/删除会话"""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/create_session")
@auth_required
async def create_session(request: Request):
    """创建用户会话(任意已登录用户均可,绑定到 token 中的 username)"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        # username 始终取自 token,忽略 body 传入的 username,防止冒名建会话
        username = request.state.user["username"]

        if not session_id:
            raise HTTPException(status_code=400, detail="Missing session_id")

        if system.data_store.insert_session(session_id, username):
            return JSONResponse(content={"message": "Session created successfully"})
        raise HTTPException(status_code=400, detail="Failed to create session")

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in create_session request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{username}")
@auth_required
async def get_sessions(request: Request, username: str):
    """获取当前用户的会话 ID 列表(路径参数 username 仅用于路由兼容,以 token 为准)"""
    try:
        token_username = request.state.user["username"]
        sessions = system.data_store.fetch_sessions_by_username(token_username)
        return JSONResponse(content={"sessions": sessions})
    except Exception as e:
        logger.error(f"Error in get_sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
@auth_required
async def delete_session(request: Request, session_id: str):
    """删除会话及相关数据(仅允许操作调用者自己的 session)"""
    try:
        username = request.state.user["username"]
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]
        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")
        system.data_store.delete_session(session_id)
        system.data_store.delete_session_history(session_id)
        return JSONResponse(content={"message": "Session and related data deleted successfully"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
