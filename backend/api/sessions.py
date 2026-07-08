# =====================================================================
# 会话管理 API 路由 - 创建 / 列出 / 删除会话
# 所有接口都需要登录认证（通过 @auth_required 装饰器）
# =====================================================================

# ===== 标准库导入 =====
import json  # 导入 json 模块，用于解析请求体中的 JSON 数据和捕获 JSON 格式错误

# ===== FastAPI 相关导入 =====
from fastapi import APIRouter, HTTPException, Request  # APIRouter: 创建路由分组; HTTPException: 返回 HTTP 错误响应; Request: 获取请求对象
from fastapi.responses import JSONResponse  # JSONResponse: 返回 JSON 格式的 HTTP 响应

# ===== 项目内部模块导入 =====
from base.logger import logger  # 导入项目的日志记录器，用于在出错时写日志

# 导入依赖：auth_required 是登录认证装饰器（验证 token），system 是全局系统对象（提供 data_store 等能力）
from .deps import auth_required, system

# ===== 创建路由对象 =====
# 创建一个 APIRouter 实例，所有路由的前缀都是 /api，在 API 文档中归类到 "sessions" 标签下
router = APIRouter(prefix="/api", tags=["sessions"])


# =====================================================================
# POST /api/create_session  -  创建新会话
# 任意已登录用户都可以调用，会话绑定到 token 中的 username
# =====================================================================
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
        # 从请求体中解析 JSON 数据，await 表示这是一个异步操作
        data = await request.json()
        # 从解析后的 JSON 字典中获取 "session_id" 字段的值
        session_id = data.get("session_id")

        # 重要安全设计：不从请求体中取 username，而是从 token 中取
        # request.state.user 是由 auth_required 认证中间件注入的用户信息
        # username 始终取自 token，忽略 body 传入的 username，防止冒名建会话
        username = request.state.user["username"]

        # 检查 session_id 是否存在且不为空
        if not session_id:
            # 如果 session_id 为空 / 缺失，抛出 400 错误，告诉客户端缺少必要参数
            raise HTTPException(status_code=400, detail="Missing session_id")

        # 调用 system.data_store.insert_session 尝试将会话插入数据库
        # insert_session 返回 True 表示插入成功，返回 False 表示失败（如 session_id 已存在）
        if system.data_store.insert_session(session_id, username):
            # 插入成功：返回 200，携带成功的提示消息
            return JSONResponse(content={"message": "Session created successfully"})

        # 插入失败（例如 session_id 重复或数据库写入失败），抛出 400 错误
        raise HTTPException(status_code=400, detail="Failed to create session")

    # ===== 异常处理区域 =====
    except json.JSONDecodeError:  # 捕获 JSON 解析错误（请求体不是合法的 JSON 格式时触发）
        # 使用日志记录器记录错误信息，方便排查问题
        logger.error("创建会话请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# GET /api/sessions/{username}  -  获取某用户的所有会话列表
# 路径中的 username 仅用于路由兼容，实际以 token 中的用户名为准
# =====================================================================
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
        # 从 token 中获取真实的用户名，忽略 URL 路径中的 username
        # 这样即使 URL 里传的是别人的用户名，也只能查到自己名下的会话
        token_username = request.state.user["username"]

        # 调用 data_store.fetch_sessions_by_username 从数据库查询该用户的所有会话
        # 返回结果是会话对象的列表（每个对象包含 id、username 等字段）
        sessions = system.data_store.fetch_sessions_by_username(token_username)

        # 将会话列表包装成 JSON 格式返回给客户端
        return JSONResponse(content={"sessions": sessions})

    except Exception as e:  # 捕获所有未预料到的异常
        # 记录错误日志
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# DELETE /api/sessions/{session_id}  -  删除指定会话
# 只能删除自己名下的会话（通过 token 中的 username 校验）
# =====================================================================
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
        # 从 token 中获取当前登录用户的用户名
        username = request.state.user["username"]

        # 查询当前用户拥有的所有会话 ID 列表
        # fetch_sessions_by_username 返回 [{id: "...", ...}] 列表，or [] 防止返回 None
        # 用列表推导式取出每个会话的 "id" 字段，组装成 owned 列表
        owned = [s['id'] for s in (system.data_store.fetch_sessions_by_username(username) or [])]

        # 检查要删除的 session_id 是否在当前用户拥有的会话列表中
        if session_id not in owned:
            # 如果 session_id 不属于当前用户，抛出 403 Forbidden（禁止访问）
            # 不使用 404（资源不存在）是为了不泄露 session 的存在信息
            raise HTTPException(status_code=403, detail="Forbidden")

        # 权限校验通过，开始删除操作
        # 先删除会话本身（从 sessions 表中删除该记录）
        system.data_store.delete_session(session_id)
        # 再删除该会话关联的所有历史聊天记录（从 history 表中删除）
        system.data_store.delete_session_history(session_id)

        # 删除成功，返回 200 和成功提示消息
        return JSONResponse(content={"message": "Session and related data deleted successfully"})

    except HTTPException:  # 捕获我们自己抛出的 HTTPException（如 403）
        raise  # 直接重新抛出，不做额外处理
    except Exception as e:  # 捕获所有其他未预料到的异常
        # 记录错误日志
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
