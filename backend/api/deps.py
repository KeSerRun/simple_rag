# 主要提供两样东西：IntegratedSystem 的单例实例，和用于接口鉴权的装饰器
"""共享依赖:IntegratedSystem 单例 + auth_required 鉴权装饰器"""

# wraps 的作用是：当我们写装饰器时，它能保留被装饰函数的原始名称和文档字符串，避免调试时函数名丢失
from functools import wraps

# JWT 是一种在前后端之间安全传递用户身份信息的标准令牌格式
import jwt
# FastAPI 会自动把请求数据封装成 Request 对象传给我们的函数
from fastapi import Request
from fastapi.responses import JSONResponse

# conf 是全局唯一的配置实例，包含了 jwt_secret_key、vector_store_dir 等所有程序配置
from base.config import conf
from base.logger import logger
# IntegratedSystem 是整个后端的"核心引擎"，集成了 RAG 检索、文档处理、向量存储等所有功能
from agent import IntegratedSystem


# 模块级单例:首次 import 触发初始化(与原 app.py 顶层创建行为一致)
system = IntegratedSystem()


def auth_required(func):
    """要求请求携带合法 JWT,不限制 role。payload 注入到 request.state.user

    用法:
        @router.post("/foo")
        @auth_required
        async def foo(request: Request):
            username = request.state.user["username"]
    """
    # @wraps 是 Python 标准库提供的装饰器工具
    # 它的作用是让 wrapper 函数"伪装"成原来的 func 函数，保留 func 的名字和文档
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        # .get("Authorization") 获取 Authorization 头的值，如果没有则返回 None
        auth_header = request.headers.get("Authorization")

        # JWT 令牌的标准格式是 "Bearer <token_string>"
        # 如果 auth_header 为空，或者不以 "Bearer " 开头，说明请求没有携带有效令牌
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # split(" ", 1) 按空格分割成 ["Bearer", "<token>"] 两部分
        token = auth_header.split(" ", 1)[1]

        try:
            # jwt.decode() 负责解码和验证 JWT 令牌
            # token.encode('utf-8') 把字符串转成字节串，因为 PyJWT 要求字节输入
            # conf.jwt_secret_key 是服务器保存的密钥，只有持有此密钥才能验证令牌真伪
            # algorithms=['HS256'] 指定使用 HS256（HMAC-SHA256）算法验证签名
            # 如果令牌被篡改、过期或密钥不匹配，会抛出异常
            payload = jwt.decode(token.encode('utf-8'), conf.jwt_secret_key, algorithms=['HS256'])
        except jwt.PyJWTError as e:
            # PyJWTError 是 PyJWT 库所有错误的基类
            # 包括：令牌过期、签名无效、格式错误等
            logger.warning(f"JWT 校验失败: {e}")
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # 例如：{"username": "张三", "role": "admin", "exp": 1700000000}
        # 如果 payload 中没有 "username" 字段，说明令牌格式不对，拒绝访问
        if not payload.get("username"):
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # request.state 是 FastAPI 提供的"请求状态存储区"
        request.state.user = payload

        # await func(request, *args, **kwargs) 调用被装饰的原始函数
        return await func(request, *args, **kwargs)

    # 此后 FastAPI 路由注册的实际上是这个 wrapper，而不是原始的 func
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
    # 同样使用 @wraps 保留原始函数信息
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        # getattr(request.state, "user", None) 尝试获取 request.state 的 user 属性
        # 如果之前没有执行过 @auth_required，user 属性就不存在，返回 None
        # 因此 @admin_required 必须放在 @auth_required 下面使用
        user = getattr(request.state, "user", None)

        # 如果 user 为 None，说明没有经过 auth_required 认证，直接拒绝
        if not user:
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # 只有 role 为 "admin" 的用户才能访问管理后台接口
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

    # 从配置 conf 中读取每个用户允许的最大存储空间（单位：MB）
    # 例如 max_user_storage_mb = 500 表示每个用户最多存 500MB 的文档
    max_mb = conf.max_user_storage_mb

    if max_mb <= 0 or role == "admin":
        return True, 0, max_mb  # 不限制

    total_bytes = 0
    # conf.vector_store_dir 是向量存储的根目录
    # "uploads" 是存放用户上传文件的子目录
    # username 是当前用户名
    # 最终路径类似：/data/vector_store/uploads/张三/
    upload_dir = os.path.join(conf.data_dir, "uploads", username.lower())

    if os.path.isdir(upload_dir):
        # os.scandir() 遍历目录中的所有条目（文件和子目录）
        for entry in os.scandir(upload_dir):
            # entry.is_file() 判断当前条目是否是文件（而非子目录）
            # 我们只统计直接放在上传目录下的文件，忽略子目录（如 chunk_out 切块缓存目录）
            if entry.is_file():  # 只统计顶级文件，忽略 chunk_out 目录
                # 累加到 total_bytes 中
                total_bytes += entry.stat().st_size

    # additional_bytes 是额外要添加的字节数（即当前请求要上传的文件大小）
    total_bytes += additional_bytes

    # 1 MB = 1024 KB = 1024 * 1024 字节
    # 将 total_bytes 除以 1024*1024 得到兆字节数
    current_mb = total_bytes / (1024 * 1024)

    # round(current_mb, 2) 将兆字节数保留两位小数，便于显示
    if current_mb >= max_mb:
        return False, round(current_mb, 2), max_mb

    return True, round(current_mb, 2), max_mb
