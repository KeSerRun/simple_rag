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
    """清除会话历史记录(仅允许操作调用者自己的 session)。

    # ── 权限校验

    从 token 获取 username,与服务端记录的 session 所有者比对,
    仅当 session_id 属于当前用户时才执行删除。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"session_id": str}``。

    Returns:
        JSONResponse: ``{"message": "Session history cleared successfully"}``。

    Raises:
        HTTPException 400: 缺少 session_id 或 JSON 格式无效。
        HTTPException 403: session 不属于当前用户。
        HTTPException 500: 删除失败。
    """
    try:
        data = await request.json()
        session_id = data.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="No session_id provided")
        username = request.state.user["username"]
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]
        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")
        system.data_store.delete_session_history(session_id)
        return JSONResponse(content={"message": "Session history cleared successfully"})
    except json.JSONDecodeError:
        logger.error("清除历史请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
@auth_required
async def get_history(request: Request, session_id: str):
    """获取会话历史记录(仅允许读取调用者自己的 session)。

    # ── 权限校验

    从 token 获取 username,与服务端记录的 session 所有者比对,
    仅当 session_id 属于当前用户时才返回数据。

    Args:
        request: FastAPI 请求对象,从中获取认证用户信息。
        session_id: URL 路径参数,要查询的会话 ID。

    Returns:
        JSONResponse: ``{"history": [...]}``,历史消息列表。

    Raises:
        HTTPException 403: session 不属于当前用户。
        HTTPException 500: 读取失败。
    """
    try:
        username = request.state.user["username"]
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]
        if session_id not in owned:
            raise HTTPException(status_code=403, detail="Forbidden")
        history = system.data_store.get_session_history(session_id)
        return JSONResponse(content={"history": history})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
