"""对话历史接口:查询与清除"""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["history"])


@router.post("/clear_history")
@auth_required
async def clear_history(request: Request):
    """清除会话历史记录(仅允许操作调用者自己的 session)"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="No session_id provided")
        username = request.state.user["username"]
        owned = system.data_store.fetch_sessions_by_username(username) or []
        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")
        system.data_store.delete_session_history(session_id)
        return JSONResponse(content={"message": "Session history cleared successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in clear_history request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clear_history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
@auth_required
async def get_history(request: Request, session_id: str):
    """获取会话历史记录(仅允许读取调用者自己的 session)"""
    try:
        username = request.state.user["username"]
        owned = system.data_store.fetch_sessions_by_username(username) or []
        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")
        history = system.data_store.get_session_history(session_id)
        return JSONResponse(content={"history": history})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
