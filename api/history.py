"""对话历史接口:查询与清除"""  # 模块文档字符串，说明本文件提供的功能

import json  # 引入 json 模块，用于解析请求体中的 JSON 数据以及处理 JSON 解析异常

# ===== FastAPI 相关导入 =====
from fastapi import APIRouter, HTTPException, Request  # APIRouter: 创建路由组; HTTPException: 返回 HTTP 错误; Request: 获取请求对象
from fastapi.responses import JSONResponse

# ===== 项目内部模块导入 =====
from base.logger import logger  # 从 base/logger.py 导入日志记录器，用于在控制台记录错误和调试信息

from .deps import auth_required, system  # 从同级的 deps.py 中导入: auth_required(认证装饰器), system(系统全局对象，用于访问数据存储)

router = APIRouter(prefix="/api", tags=["history"])  # 创建一个路由组，所有接口路径都以 /api 开头，在 Swagger 文档中归类到 "history" 标签下


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


@router.get("/history/{session_id}")  # 注册 GET 接口，路径为 /api/history/{session_id}，session_id 是路径参数
@auth_required  # 同样需要认证，未登录用户无法调用
async def get_history(request: Request, session_id: str):
    """获取会话历史记录(仅允许读取调用者自己的 session)"""
    try:
        username = request.state.user["username"]
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]
        if session_id not in owned:  # 判断要查询的 session_id 是否属于当前用户
            raise HTTPException(status_code=403, detail="Forbidden")
        history = system.data_store.get_session_history(session_id)
        return JSONResponse(content={"history": history})  # 将历史记录包装在 JSON 对象中返回给客户端，字段名为 "history"
    except HTTPException:  # 捕获自己主动抛出的 HTTPException
        raise  # 直接原样抛出，不做额外处理
    except Exception as e:  # 捕获其他所有未预料到的异常
        logger.error(f"获取历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
