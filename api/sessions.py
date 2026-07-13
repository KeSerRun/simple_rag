"""会话管理接口:创建 / 查询 / 删除"""

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from base.logger import logger
from base.config import conf

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/create_session")
@auth_required
async def create_session(request: Request):
    """创建用户会话。

    # ── 安全

    请求体需要传 session_id,username 始终从 token 中获取(防止伪造他人身份建会话)。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"session_id": str}``。

    Returns:
        JSONResponse: ``{"message": "Session created successfully"}``。

    Raises:
        HTTPException 400: 缺少 session_id 或 JSON 格式无效。
        HTTPException 500: 创建失败。
    """
    try:
        data = await request.json()
        session_id = data.get("session_id")

        username = request.state.user["username"]

        if not session_id:
            raise HTTPException(status_code=400, detail="Missing session_id")

        if system.data_store.insert_session(session_id, username):
            return JSONResponse(content={"message": "Session created successfully"})

        raise HTTPException(status_code=400, detail="Failed to create session")

    except json.JSONDecodeError:
        logger.error("创建会话请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{username}")
@auth_required
async def get_sessions(request: Request, username: str):
    """获取当前登录用户的所有会话 ID 列表。

    # ── 安全

    虽然路径上有 username 参数,但实际查询时使用 token 中的 username(安全性考虑)。

    Args:
        request: FastAPI 请求对象,从中获取认证用户信息。
        username: URL 路径中的用户名参数(仅用于路由兼容,实际不用它查询)。

    Returns:
        JSONResponse: ``{"sessions": [...]}``,返回该用户的所有会话。

    Raises:
        HTTPException 500: 查询失败。
    """
    try:
        token_username = request.state.user["username"]

        sessions = system.data_store.fetch_sessions_by_username(token_username)

        return JSONResponse(content={"sessions": sessions})

    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
@auth_required
async def delete_session(request: Request, session_id: str):
    """删除指定会话及其关联的历史记录。

    # ── 权限

    仅允许操作调用者自己的 session,禁止删除其他人的会话。

    # ── 清理范围

    - session 记录 (data_store.delete_session)
    - 对话历史 (delete_session_history)
    - 任务记录 (delete_session_tasks)
    - 归档记录 (delete_session_archives)
    - 工具结果文件 (json_store/tool_results/<session_id>)
    - 归档 JSON 文件 (json_store/archives/arch_<session_prefix>*)

    Args:
        request: FastAPI 请求对象,从中获取认证用户信息。
        session_id: URL 路径参数,要删除的会话 ID。

    Returns:
        JSONResponse: ``{"message": "Session and related data deleted successfully"}``。

    Raises:
        HTTPException 403: session 不属于当前用户。
        HTTPException 500: 删除失败。
    """
    try:
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
