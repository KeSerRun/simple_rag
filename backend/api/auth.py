# 用户注册后将信息存入数据库，登录时验证身份并签发 JWT 令牌

import json

import jwt
from fastapi import APIRouter, HTTPException, Request
# 从 fastapi 导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger

from .deps import system

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register")
# async 表示这是一个异步函数，内部可以使用 await 来等待 IO 操作（如读取请求体）
async def register(request: Request):
    """处理用户注册"""
    # 使用 try 块来捕获可能发生的异常，保证程序不会因为错误而崩溃
    try:
        # await request.json() 异步地读取请求体，把 JSON 字符串解析成 Python 字典
        # data 就是前端传过来的数据，例如 {"username": "admin", "password": "123456"}
        data = await request.json()
        username = data.get("username")
        password = data.get("password")

        # 用户名统一转小写，避免因大小写造成的路径目录冲突
        if username:
            username = username.lower()

        # 判断用户名或密码是否为空
        # not 运算符把值转为布尔值：None、空字符串都会被当作 False
        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")
        # 调用 system.data_store.insert_user() 尝试将新用户插入数据库
        if system.data_store.insert_user(username, password):
            # JSONResponse 会自动把 Python 字典转换成 JSON 字符串发给前端
            return JSONResponse(content={"message": "Registration successful"})
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
    # Exception 是 Python 所有异常的基类，能捕获任何意料之外的错误
    except Exception as e:
        # 将错误信息记录到日志中，str(e) 会把异常对象转换成可读的字符串
        logger.error(f"注册失败: {e}")
        # 抛出 HTTP 500 错误（服务器内部错误），并把异常信息传给前端
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
async def login(request: Request):
    # 函数的文档字符串：处理用户登录，验证成功后向下发 JWT 令牌
    """处理用户登录,验证成功后下发 JWT"""
    try:
        # 异步读取 HTTP 请求的 body，把 JSON 字符串解析为 Python 字典
        # 例如前端传 {"username": "admin", "password": "123456"}
        data = await request.json()
        username = data.get("username")
        password = data.get("password")

        # 用户名统一转小写，与注册时一致
        if username:
            username = username.lower()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        # 调用 system.data_store.check_user_credentials() 验证用户名和密码
        # 既把 check_user_credentials 的返回值赋给 result，又判断它是否为真
        if result := system.data_store.check_user_credentials(username, password):
            token = jwt.encode(
                {"username": result["username"], "role": result["role"]},
                conf.jwt_secret_key,
                algorithm="HS256",
            )
            # message：成功提示信息
            # user：用户信息（用户名和角色），前端可以用来显示当前用户
            # token：JWT 令牌字符串，前端需在后续请求的 Authorization 头中携带
            return JSONResponse(content={
                "message": "Login successful",
                "user": {"username": result["username"], "role": result["role"]},
                "token": token,
            })
        # 抛出 HTTP 401 错误（未授权/认证失败）
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 捕获 JSON 格式解析错误
    except json.JSONDecodeError:
        # 记录错误日志：登录请求中的 JSON 格式无效
        logger.error("登录请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    # 捕获我们自己抛出的 HTTPException（如 400、401 等）
    except HTTPException:
        # 不做额外处理，直接原样抛出，交给 FastAPI 中间件处理
        raise
    except Exception as e:
        # 将异常信息记录到日志，方便调试
        logger.error(f"登录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def create_superusers():
    # 文档字符串：遍历配置文件中的超级管理员列表，逐个创建账户
    """启动时根据配置中的超级管理员用户名/密码创建账户(若已存在则跳过)"""
    # 使用 zip() 同时遍历两个列表：超级管理员用户名列表和密码列表
    # zip 会把两个列表中对应位置的元素配对，组成 (username, password) 元组
    # conf.superuser_usernames 例如：["admin", "root"]
    # conf.superuser_passwords 例如：["admin123", "root123"]
    # zip 后变成：("admin", "admin123"), ("root", "root123")
    for username, password in zip(conf.superuser_usernames, conf.superuser_passwords):
        try:
            # 调用 insert_user 方法插入超级管理员
            # 普通用户注册时 role 默认为空或 "user"
            system.data_store.insert_user(username, password, role="admin")
            # 记录日志：超级管理员创建成功，方便运维人员检查
            logger.debug(f"Superuser '{username}' created successfully.")
        # 捕获任何类型的异常（比如用户名已存在引起的数据库错误）
        except Exception as e:
          
            logger.error(f"Error creating superuser '{username}': {str(e)}")
