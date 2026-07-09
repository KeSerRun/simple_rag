# ===== 文件说明 =====
# 这个文件是 FastAPI 的"依赖层"，负责提供整个后端所需的共享依赖
# 主要提供两样东西：IntegratedSystem 的单例实例，和用于接口鉴权的装饰器
"""共享依赖:IntegratedSystem 单例 + auth_required 鉴权装饰器"""

# ===== 导入标准库 =====
# 从 functools 模块导入 wraps 工具
# wraps 的作用是：当我们写装饰器时，它能保留被装饰函数的原始名称和文档字符串，避免调试时函数名丢失
from functools import wraps

# ===== 导入第三方库 =====
# 导入 jwt 库（PyJWT），用于创建和验证 JSON Web Token
# JWT 是一种在前后端之间安全传递用户身份信息的标准令牌格式
import jwt
# 从 FastAPI 框架导入 Request 类。Request 代表客户端发来的 HTTP 请求
# FastAPI 会自动把请求数据封装成 Request 对象传给我们的函数
from fastapi import Request
# 导入 FastAPI 的 JSONResponse，用于直接返回 JSON 格式的 HTTP 响应
# 当鉴权失败时，我们用它返回错误消息给前端
from fastapi.responses import JSONResponse

# ===== 导入项目内部模块 =====
# 从 base.config 模块导入 conf 配置对象
# conf 是全局唯一的配置实例，包含了 jwt_secret_key、vector_store_dir 等所有程序配置
from base.config import conf
# 从 base.logger 导入日志记录器 logger
# logger 用于输出运行日志，方便在服务端排查问题
from base.logger import logger
# 从 agent 模块导入 IntegratedSystem 类
# IntegratedSystem 是整个后端的"核心引擎"，集成了 RAG 检索、文档处理、向量存储等所有功能
from agent import IntegratedSystem


# ===== 创建全局单例 =====
# 模块级单例:首次 import 触发初始化(与原 app.py 顶层创建行为一致)
# 这行代码在模块被导入时就会执行，创建整个程序唯一的一个 IntegratedSystem 实例
# 所有路由处理函数都共用这一个实例，避免重复初始化浪费资源
system = IntegratedSystem()


# ===== 用户认证装饰器（auth_required） =====
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
    # 这样 FastAPI 的路由系统才能正确识别接口信息
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        # ---- 第一步：从 HTTP 请求头中提取 Authorization 字段 ----
        # request.headers 是一个字典，包含了客户端发送的所有 HTTP 头
        # .get("Authorization") 获取 Authorization 头的值，如果没有则返回 None
        auth_header = request.headers.get("Authorization")

        # ---- 第二步：检查 Authorization 头是否存在且格式正确 ----
        # JWT 令牌的标准格式是 "Bearer <token_string>"
        # 如果 auth_header 为空，或者不以 "Bearer " 开头，说明请求没有携带有效令牌
        if not auth_header or not auth_header.startswith("Bearer "):
            # 返回 401 Unauthorized 状态码，表示用户未认证
            # JSONResponse 会返回一个 JSON 格式的响应体给前端
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # ---- 第三步：从 "Bearer <token>" 中提取出纯令牌字符串 ----
        # split(" ", 1) 按空格分割成 ["Bearer", "<token>"] 两部分
        # [1] 获取第二部分，也就是真正的 JWT 令牌字符串
        token = auth_header.split(" ", 1)[1]

        # ---- 第四步：解码并验证 JWT 令牌 ----
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
            # 在服务器日志中记录详细的错误信息，便于排错
            logger.warning(f"JWT 校验失败: {e}")
            # 向前端返回 401，不透露具体错误原因（安全考虑）
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # ---- 第五步：验证令牌中是否包含用户名 ----
        # payload 是解码后的 JWT 数据部分，是一个字典
        # 例如：{"username": "张三", "role": "admin", "exp": 1700000000}
        # 如果 payload 中没有 "username" 字段，说明令牌格式不对，拒绝访问
        if not payload.get("username"):
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # ---- 第六步：将用户信息注入到请求状态中 ----
        # request.state 是 FastAPI 提供的"请求状态存储区"
        # 我们在这里保存解码后的用户信息，后续的路由处理函数可以直接通过
        # request.state.user 获取当前登录用户的信息
        request.state.user = payload

        # ---- 第七步：调用原始的路由处理函数 ----
        # await func(request, *args, **kwargs) 调用被装饰的原始函数
        # 并将 request 和所有其他参数传递过去
        # 注意这里使用了 await，因为路由函数是异步的（async def）
        return await func(request, *args, **kwargs)

    # 返回装饰后的 wrapper 函数
    # 此后 FastAPI 路由注册的实际上是这个 wrapper，而不是原始的 func
    return wrapper


# ===== 管理员权限装饰器（admin_required） =====
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
        # ---- 第一步：从请求状态中获取用户信息 ----
        # getattr(request.state, "user", None) 尝试获取 request.state 的 user 属性
        # 如果之前没有执行过 @auth_required，user 属性就不存在，返回 None
        # 因此 @admin_required 必须放在 @auth_required 下面使用
        user = getattr(request.state, "user", None)

        # ---- 第二步：检查用户是否已登录 ----
        # 如果 user 为 None，说明没有经过 auth_required 认证，直接拒绝
        if not user:
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)

        # ---- 第三步：检查用户角色是否为管理员 ----
        # user.get("role") 从用户信息字典中获取角色字段
        # 只有 role 为 "admin" 的用户才能访问管理后台接口
        # 其他角色（如普通用户 "user"）返回 403 Forbidden
        if user.get("role") != "admin":
            return JSONResponse(content={"message": "Forbidden: admin required"}, status_code=403)

        # ---- 第四步：权限验证通过，调用原始处理函数 ----
        return await func(request, *args, **kwargs)

    # 返回装饰后的 wrapper 函数
    return wrapper


# ===== 用户存储空间限制检查函数 =====
def check_user_storage_limit(username: str, role: str, additional_bytes: int = 0):
    """检查普通用户存储是否超限，admin 不受限制。
    统计用户上传的原始文档总大小（不含切块缓存）。

    返回 (ok: bool, current_mb: float, max_mb: float)
    """
    # ---- 导入操作系统模块 ----
    # 在函数内部导入 os，用于文件和路径操作
    # 放在函数内部可以避免模块级别的导入开销（只有调用此函数时才导入）
    import os

    # ---- 第一步：获取配置中允许的最大存储空间 ----
    # 从配置 conf 中读取每个用户允许的最大存储空间（单位：MB）
    # 例如 max_user_storage_mb = 500 表示每个用户最多存 500MB 的文档
    max_mb = conf.max_user_storage_mb

    # ---- 第二步：判断是否需要限制 ----
    # 如果 max_mb <= 0，表示"不限容量"，直接返回通过
    # 如果用户角色是 "admin"，管理员不受存储限制，也直接返回通过
    if max_mb <= 0 or role == "admin":
        # 返回三个值：(是否通过, 当前用量MB, 最大限制MB)
        # 当前用量返回 0，因为不需要统计
        return True, 0, max_mb  # 不限制

    # ---- 第三步：遍历用户上传的文件，计算总大小 ----
    # 初始化总字节数为 0
    total_bytes = 0
    # 拼接用户的上传目录路径
    # conf.vector_store_dir 是向量存储的根目录
    # "uploads" 是存放用户上传文件的子目录
    # username 是当前用户名
    # 最终路径类似：/data/vector_store/uploads/张三/
    upload_dir = os.path.join(conf.vector_store_dir, "uploads", username)

    # ---- 第四步：检查目录是否存在并遍历文件 ----
    # os.path.isdir() 判断路径是否是一个已存在的目录
    # 如果用户从未上传过文件，目录可能还不存在，跳过遍历
    if os.path.isdir(upload_dir):
        # os.scandir() 遍历目录中的所有条目（文件和子目录）
        # 每次迭代返回一个 DirEntry 对象
        for entry in os.scandir(upload_dir):
            # entry.is_file() 判断当前条目是否是文件（而非子目录）
            # 我们只统计直接放在上传目录下的文件，忽略子目录（如 chunk_out 切块缓存目录）
            if entry.is_file():  # 只统计顶级文件，忽略 chunk_out 目录
                # entry.stat().st_size 获取文件的大小，单位是字节
                # 累加到 total_bytes 中
                total_bytes += entry.stat().st_size

    # ---- 第五步：加上本次新上传的文件大小 ----
    # additional_bytes 是额外要添加的字节数（即当前请求要上传的文件大小）
    # 这样可以在上传前就预判是否会超限，而不是上传后才检查
    total_bytes += additional_bytes

    # ---- 第六步：将字节数转换为 MB（兆字节） ----
    # 1 MB = 1024 KB = 1024 * 1024 字节
    # 将 total_bytes 除以 1024*1024 得到兆字节数
    current_mb = total_bytes / (1024 * 1024)

    # ---- 第七步：判断是否超过限制 ----
    # 如果当前用量 >= 最大限制，返回 False 表示超限
    # round(current_mb, 2) 将兆字节数保留两位小数，便于显示
    if current_mb >= max_mb:
        return False, round(current_mb, 2), max_mb

    # ---- 第八步：未超限，返回通过 ----
    # 返回 True 表示存储空间足够，可以继续上传
    return True, round(current_mb, 2), max_mb
