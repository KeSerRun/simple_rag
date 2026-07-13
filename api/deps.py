"""共享依赖:IntegratedSystem 单例 + auth_required 鉴权装饰器"""

from functools import wraps

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger
from agent import IntegratedSystem


system = IntegratedSystem()


def auth_required(func):
    """要求请求携带合法 JWT,不限制 role。payload 注入到 request.state.user

    用法:
        @router.post("/foo")
        @auth_required
        async def foo(request: Request):
            username = request.state.user["username"]
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token.encode('utf-8'), conf.jwt_secret_key, algorithms=['HS256'])
        except jwt.PyJWTError as e:
            logger.warning(f"JWT 校验失败: {e}")
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        if not payload.get("username"):
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        request.state.user = payload
        return await func(request, *args, **kwargs)
    return wrapper


def admin_required(func):
    """要求当前认证用户角色为 admin,需在 @auth_required 之后使用

    用法:
        @router.get("/api/admin/foo")
        @auth_required        # 先验证用户已登录
        @admin_required        # 再验证用户是管理员
        async def foo(request: Request):
            ...
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = getattr(request.state, "user", None)
        if not user:
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        if user.get("role") != "admin":
            return JSONResponse(content={"message": "Forbidden: admin required"}, status_code=403)
        return await func(request, *args, **kwargs)
    return wrapper


def check_user_storage_limit(username: str, role: str, additional_bytes: int = 0):
    """检查普通用户存储是否超限，admin 不受限制。
    统计用户上传的原始文档总大小（不含切块缓存）。

    返回 (ok: bool, current_mb: float, max_mb: float)
    """
    import os
    max_mb = conf.max_user_storage_mb
    if max_mb <= 0 or role == "admin":
        return True, 0, max_mb  # 不限制
    total_bytes = 0
    upload_dir = os.path.join(conf.data_dir, "uploads", username.lower())
    if os.path.isdir(upload_dir):
        for entry in os.scandir(upload_dir):
            if entry.is_file():  # 只统计顶级文件，忽略 chunk_out 目录
                total_bytes += entry.stat().st_size
    total_bytes += additional_bytes
    current_mb = total_bytes / (1024 * 1024)
    if current_mb >= max_mb:
        return False, round(current_mb, 2), max_mb
    return True, round(current_mb, 2), max_mb
