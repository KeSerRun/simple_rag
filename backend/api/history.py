# ============================================================
# 对话历史接口模块
# 功能：提供对话历史的查询和清除功能
# 每个接口都做了权限校验，用户只能操作自己的 session
# ============================================================

"""对话历史接口:查询与清除"""  # 模块文档字符串，说明本文件提供的功能

import json  # 引入 json 模块，用于解析请求体中的 JSON 数据以及处理 JSON 解析异常

# ===== FastAPI 相关导入 =====
from fastapi import APIRouter, HTTPException, Request  # APIRouter: 创建路由组; HTTPException: 返回 HTTP 错误; Request: 获取请求对象
from fastapi.responses import JSONResponse  # JSONResponse: 返回 JSON 格式的响应数据

# ===== 项目内部模块导入 =====
from base.logger import logger  # 从 base/logger.py 导入日志记录器，用于在控制台记录错误和调试信息

from .deps import auth_required, system  # 从同级的 deps.py 中导入: auth_required(认证装饰器), system(系统全局对象，用于访问数据存储)

# ===== 创建路由对象 =====
router = APIRouter(prefix="/api", tags=["history"])  # 创建一个路由组，所有接口路径都以 /api 开头，在 Swagger 文档中归类到 "history" 标签下


# ============================================================
# 清除对话历史接口：POST /api/clear_history
# 用户只能清除自己的 session 历史记录，不能动别人的
# ============================================================
@router.post("/clear_history")  # 注册 POST 接口，路径为 /api/clear_history
@auth_required  # 应用认证装饰器：请求必须携带有效 token，否则直接返回 401 未授权
async def clear_history(request: Request):
    """清除会话历史记录(仅允许操作调用者自己的 session)"""  # 函数文档：说明该接口的作用是清除历史，并且做了权限控制
    try:  # 进入 try 块，捕获可能出现的任何异常
        data = await request.json()  # 异步读取请求体并解析为 JSON 字典（await 是因为 request.json() 是个异步方法）
        session_id = data.get("session_id")  # 从解析后的 JSON 数据中取出 "session_id" 字段的值
        if not session_id:  # 如果 session_id 为空、None 或不存在
            raise HTTPException(status_code=400, detail="No session_id provided")  # 抛出 400 错误，提示客户端必须提供 session_id
        username = request.state.user["username"]  # 从请求的状态对象中获取当前登录用户的用户名（auth_required 中间件已经注入）
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]  # 查询当前用户拥有的所有 session ID 列表（如果返回 None 则用空列表代替）
        if session_id not in owned:  # 判断要清除的 session_id 是否属于当前用户
            raise HTTPException(status_code=403, detail="Forbidden")  # 如果不属于，抛出 403 禁止访问错误，防止越权操作
        system.data_store.delete_session_history(session_id)  # 调用数据存储的删除方法，清除该 session 的历史记录
        return JSONResponse(content={"message": "Session history cleared successfully"})  # 返回 JSON 格式的成功响应，告知客户端清除完成
    except json.JSONDecodeError:  # 捕获 JSON 解析错误：请求体不是合法的 JSON 格式
        logger.error("Invalid JSON format in clear_history request")  # 在日志中记录错误信息，方便排查问题
        raise HTTPException(status_code=400, detail="Invalid JSON format")  # 向客户端返回 400 错误，提示 JSON 格式不正确
    except HTTPException:  # 捕获自己主动抛出的 HTTPException（比如 400/403）
        raise  # 直接原样抛出，不做额外处理（让 FastAPI 的异常处理器来处理）
    except Exception as e:  # 捕获其他所有未预料到的异常
        logger.error(f"Error in clear_history: {str(e)}")  # 在日志中记录异常的具体信息
        raise HTTPException(status_code=500, detail=str(e))  # 向客户端返回 500 服务器内部错误，并把异常信息作为详情返回


# ============================================================
# 获取对话历史接口：GET /api/history/{session_id}
# 用户只能读取自己的 session 历史记录，不能看别人的
# ============================================================
@router.get("/history/{session_id}")  # 注册 GET 接口，路径为 /api/history/{session_id}，session_id 是路径参数
@auth_required  # 同样需要认证，未登录用户无法调用
async def get_history(request: Request, session_id: str):
    """获取会话历史记录(仅允许读取调用者自己的 session)"""  # 函数文档：说明该接口的作用是获取历史，并且做了权限控制
    try:  # 进入 try 块，捕获可能出现的任何异常
        username = request.state.user["username"]  # 从请求的状态对象中获取当前登录用户的用户名
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]  # 查询当前用户拥有的所有 session ID 列表
        if session_id not in owned:  # 判断要查询的 session_id 是否属于当前用户
            raise HTTPException(status_code=403, detail="Forbidden")  # 如果不属于，抛出 403 禁止访问错误
        history = system.data_store.get_session_history(session_id)  # 调用数据存储的查询方法，获取该 session 的历史对话记录
        return JSONResponse(content={"history": history})  # 将历史记录包装在 JSON 对象中返回给客户端，字段名为 "history"
    except HTTPException:  # 捕获自己主动抛出的 HTTPException
        raise  # 直接原样抛出，不做额外处理
    except Exception as e:  # 捕获其他所有未预料到的异常
        logger.error(f"Error in get_history: {str(e)}")  # 在日志中记录异常的具体信息
        raise HTTPException(status_code=500, detail=str(e))  # 向客户端返回 500 服务器内部错误
