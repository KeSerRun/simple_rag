# ===== 文件说明：认证相关接口（注册与登录） =====
# 本文件负责处理用户的注册和登录功能，是系统的身份认证模块
# 用户注册后将信息存入数据库，登录时验证身份并签发 JWT 令牌

# ===== 导入标准库 =====
# 导入 json 模块，用于解析和生成 JSON 格式的数据
# 在处理前端请求时，需要把请求体从 JSON 字符串解析成 Python 字典
import json

# ===== 导入第三方库 =====
# 导入 jwt 库，用于生成和验证 JSON Web Token（JWT）
# JWT 是一种轻量级的身份认证令牌，登录成功后颁发给前端使用
import jwt
# 从 fastapi 框架导入路由、HTTP 异常类和请求对象
# APIRouter：用于创建路由分组，把相关的接口组织在一起
# HTTPException：用于抛出 HTTP 错误响应（如 400、401、500 等）
# Request：表示客户端发来的 HTTP 请求，包含请求体、请求头等信息
from fastapi import APIRouter, HTTPException, Request
# 从 fastapi 导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应
# 与普通的 Response 不同，它会自动设置 Content-Type 为 application/json
from fastapi.responses import JSONResponse

# ===== 导入项目内部模块 =====
# 从 base.config 模块导入配置对象 conf
# conf 对象中包含了 JWT 密钥、超级管理员账号等全局配置项
from base.config import conf
# 从 base.logger 模块导入日志记录器 logger
# logger 用于在控制台或日志文件中记录程序运行信息、错误等
from base.logger import logger

# 从当前 API 包（同级目录）的 deps 模块导入 system 对象
# system 是一个全局对象，封装了数据存储、用户操作等核心功能
from .deps import system

# ===== 创建路由对象 =====
# 创建一个 APIRouter 实例，所有认证接口的 URL 都以 /api 开头
# tags=["auth"] 用于在 Swagger 文档中把这些接口归类到 "auth" 分组
router = APIRouter(prefix="/api", tags=["auth"])


# ===== 用户注册接口 =====
# 定义 POST /api/register 接口，浏览器或前端通过 POST 请求来注册新用户
@router.post("/register")
# 定义异步函数 register，参数是 FastAPI 的 Request 对象
# async 表示这是一个异步函数，内部可以使用 await 来等待 IO 操作（如读取请求体）
async def register(request: Request):
    # 这是函数的文档字符串，描述了函数的功能：处理用户注册
    """处理用户注册"""
    # 使用 try 块来捕获可能发生的异常，保证程序不会因为错误而崩溃
    try:
        # await request.json() 异步地读取请求体，把 JSON 字符串解析成 Python 字典
        # data 就是前端传过来的数据，例如 {"username": "admin", "password": "123456"}
        data = await request.json()
        # 从 data 字典中获取 "username" 字段的值
        # dict.get() 方法：如果键不存在则返回 None（而不是抛出异常）
        username = data.get("username")
        # 从 data 字典中获取 "password" 字段的值
        password = data.get("password")

        # 用户名统一转小写，避免因大小写造成的路径目录冲突
        if username:
            username = username.lower()

        # 判断用户名或密码是否为空
        # not 运算符把值转为布尔值：None、空字符串都会被当作 False
        # 如果用户名为空或者密码为空，就执行 if 内部的代码
        if not username or not password:
            # 抛出 HTTP 400 错误（客户端请求错误），并在 detail 中说明原因
            # 400 表示"客户端发来的请求有问题"，这里特指缺少必填字段
            raise HTTPException(status_code=400, detail="Missing username or password")
        # 调用 system.data_store.insert_user() 尝试将新用户插入数据库
        # insert_user 接收三个参数：用户名、密码、角色（角色默认为普通用户）
        # 如果用户名不存在，插入成功并返回 True
        # 如果用户名已存在，插入失败并返回 False
        if system.data_store.insert_user(username, password):
            # 如果注册成功，返回 200 OK 响应，返回 JSON 格式的成功消息
            # JSONResponse 会自动把 Python 字典转换成 JSON 字符串发给前端
            return JSONResponse(content={"message": "Registration successful"})
        # 如果 insert_user 返回 False，说明用户名已经被别人注册了
        # 抛出 400 错误，告诉前端"用户名已存在"
        raise HTTPException(status_code=400, detail="Username already exists")

    # 捕获 json 解析错误（当前端传的 JSON 格式不对时触发）
    # 例如前端传了 "{bad json}" 这样的字符串，json.loads 就会报这个错
    except json.JSONDecodeError:
        # 使用 logger 记录错误日志，方便开发者排查问题
        # "Invalid JSON format in register request" 意思是"注册请求中的 JSON 格式无效"
        logger.error("注册请求 JSON 格式无效")
        # 抛出 HTTP 400 错误，告诉前端"发来的数据不是合法的 JSON 格式"
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    # 捕获 HTTPException 类型的异常（我们自己用 raise 抛出的那些错误）
    except HTTPException:
        # 直接 re-raise（原样抛出），让 FastAPI 框架来统一处理响应
        # 不做任何额外处理，因为 HTTPException 本身就是合法的错误响应
        raise
    # 捕获所有其他未知类型的异常（兜底处理）
    # Exception 是 Python 所有异常的基类，能捕获任何意料之外的错误
    except Exception as e:
        # 将错误信息记录到日志中，str(e) 会把异常对象转换成可读的字符串
        logger.error(f"注册失败: {e}")
        # 抛出 HTTP 500 错误（服务器内部错误），并把异常信息传给前端
        # 注意：生产环境中通常不建议把具体错误信息直接暴露给用户
        raise HTTPException(status_code=500, detail=str(e))


# ===== 用户登录接口 =====
# 定义 POST /api/login 接口，前端通过 POST 请求来登录已有账户
@router.post("/login")
# 定义异步函数 login，接收 FastAPI 的 Request 对象
async def login(request: Request):
    # 函数的文档字符串：处理用户登录，验证成功后向下发 JWT 令牌
    # JWT 令牌是一个加密的字符串，后续请求可以用它来证明身份
    """处理用户登录,验证成功后下发 JWT"""
    # try 块包裹主要逻辑，用于统一捕获和处理异常
    try:
        # 异步读取 HTTP 请求的 body，把 JSON 字符串解析为 Python 字典
        # 例如前端传 {"username": "admin", "password": "123456"}
        data = await request.json()
        # 从解析后的字典中获取用户名
        username = data.get("username")
        # 从解析后的字典中获取密码（明文密码）
        password = data.get("password")

        # 用户名统一转小写，与注册时一致
        if username:
            username = username.lower()

        # 检查用户名或密码是否为空（为 None 或空字符串都会触发）
        if not username or not password:
            # 如果缺少用户名或密码，返回 HTTP 400 错误
            raise HTTPException(status_code=400, detail="Missing username or password")

        # 调用 system.data_store.check_user_credentials() 验证用户名和密码
        # 这个函数会查询数据库，比对用户名和密码是否匹配
        # 如果匹配，返回该用户的信息字典（包含 username、role 等字段）
        # 如果不匹配，返回 None（或 False 等假值）
        # 这里的 ":=" 是海象运算符（walrus operator），
        # 既把 check_user_credentials 的返回值赋给 result，又判断它是否为真
        if result := system.data_store.check_user_credentials(username, password):
            # 如果验证通过，使用 jwt.encode() 生成一个 JWT 令牌
            # jwt.encode 接收三个关键参数：
            # 第一个参数是 payload（载荷），存放要携带的用户信息
            # 第二个参数是密钥（secret），用于签名令牌，防止被篡改
            # 第三个参数是算法，这里使用 HS256（HMAC-SHA256 对称加密）
            token = jwt.encode(
                # payload：在令牌中存用户名和角色，后续接口通过解析令牌获取用户身份
                {"username": result["username"], "role": result["role"]},
                # 使用配置文件中定义的 JWT 密钥来签名令牌
                conf.jwt_secret_key,
                # 指定加密算法为 HS256，这是最常用的 JWT 签名算法之一
                algorithm="HS256",
            )
            # 登录成功，返回 200 OK 响应，包含三部分内容：
            # message：成功提示信息
            # user：用户信息（用户名和角色），前端可以用来显示当前用户
            # token：JWT 令牌字符串，前端需在后续请求的 Authorization 头中携带
            return JSONResponse(content={
                "message": "Login successful",
                "user": {"username": result["username"], "role": result["role"]},
                "token": token,
            })
        # 如果 check_user_credentials 返回假值（用户名或密码错误）
        # 抛出 HTTP 401 错误（未授权/认证失败）
        # 401 专门用于"身份验证失败"的场景，与 400 不同
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 捕获 JSON 格式解析错误
    except json.JSONDecodeError:
        # 记录错误日志：登录请求中的 JSON 格式无效
        logger.error("登录请求 JSON 格式无效")
        # 返回 HTTP 400 错误给前端
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    # 捕获我们自己抛出的 HTTPException（如 400、401 等）
    except HTTPException:
        # 不做额外处理，直接原样抛出，交给 FastAPI 中间件处理
        raise
    # 捕获其他所有未预料到的异常
    except Exception as e:
        # 将异常信息记录到日志，方便调试
        logger.error(f"登录失败: {e}")
        # 返回 HTTP 500 服务器内部错误
        raise HTTPException(status_code=500, detail=str(e))


# ===== 超级管理员创建函数 =====
# 该函数在系统启动时自动调用，用于初始化超级管理员账户
def create_superusers():
    # 文档字符串：遍历配置文件中的超级管理员列表，逐个创建账户
    # 如果用户已经存在则跳过（不会重复创建或覆盖）
    """启动时根据配置中的超级管理员用户名/密码创建账户(若已存在则跳过)"""
    # 使用 zip() 同时遍历两个列表：超级管理员用户名列表和密码列表
    # zip 会把两个列表中对应位置的元素配对，组成 (username, password) 元组
    # conf.superuser_usernames 例如：["admin", "root"]
    # conf.superuser_passwords 例如：["admin123", "root123"]
    # zip 后变成：("admin", "admin123"), ("root", "root123")
    for username, password in zip(conf.superuser_usernames, conf.superuser_passwords):
        # try 块用于捕获单个用户创建时的错误，避免一个失败影响其他用户的创建
        try:
            # 调用 insert_user 方法插入超级管理员
            # 第三个参数 role="admin" 指定该用户的角色为"admin"（管理员）
            # 普通用户注册时 role 默认为空或 "user"
            system.data_store.insert_user(username, password, role="admin")
            # 记录日志：超级管理员创建成功，方便运维人员检查
            logger.debug(f"Superuser '{username}' created successfully.")
        # 捕获任何类型的异常（比如用户名已存在引起的数据库错误）
        except Exception as e:
          
            logger.error(f"Error creating superuser '{username}': {str(e)}")
