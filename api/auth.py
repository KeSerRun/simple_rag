import json
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger

from .deps import system

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register")
async def register(request: Request):
    """处理用户注册。

    # ── 处理流程

    1. 从请求体中解析 username / password
    2. 用户名自动转小写
    3. 调用 ``system.data_store.insert_user`` 创建账户
    4. 重复用户名返回 400

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"username": str, "password": str}``。

    Returns:
        JSONResponse: ``{"message": "Registration successful"}`` (201 语义)。

    Raises:
        HTTPException 400: 缺少用户名/密码、用户名已存在或 JSON 格式无效。
        HTTPException 500: 其他内部错误。
    """
    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")
        if username:
            username = username.lower()
        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")
        if system.data_store.insert_user(username, password):
            return JSONResponse(content={"message": "Registration successful"})
        raise HTTPException(status_code=400, detail="Username already exists")

    except json.JSONDecodeError:
        logger.error("注册请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
async def login(request: Request):
    """处理用户登录,验证成功后下发 JWT。

    # ── 处理流程

    1. 从请求体中解析 username / password
    2. 用户名自动转小写
    3. 调用 ``system.data_store.check_user_credentials`` 校验
    4. 成功后签发 HS256 JWT (payload 含 username, role)

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"username": str, "password": str}``。

    Returns:
        JSONResponse: 包含 message、user 信息和 token。

    Raises:
        HTTPException 400: 缺少用户名/密码或 JSON 格式无效。
        HTTPException 401: 用户名或密码错误。
        HTTPException 500: 其他内部错误。
    """
    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")
        if username:
            username = username.lower()
        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")
        if result := system.data_store.check_user_credentials(username, password):
            token = jwt.encode(
                {"username": result["username"], "role": result["role"]},
                conf.jwt_secret_key,
                algorithm="HS256",
            )
            return JSONResponse(content={
                "message": "Login successful",
                "user": {"username": result["username"], "role": result["role"]},
                "token": token,
            })
        raise HTTPException(status_code=401, detail="Invalid credentials")

    except json.JSONDecodeError:
        logger.error("登录请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def create_superusers():
    """启动时根据配置中的超级管理员用户名/密码创建账户(若已存在则跳过)。

    # ── 数据来源

    从 ``conf.superuser_usernames`` / ``conf.superuser_passwords`` 列表中逐对读取,
    调用 ``system.data_store.insert_user`` 以 admin 角色创建。
    已存在的账户静默跳过（insert_user 返回 False 不视为异常）。
    """
    for username, password in zip(conf.superuser_usernames, conf.superuser_passwords):
        try:
            system.data_store.insert_user(username, password, role="admin")
            logger.debug(f"Superuser '{username}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating superuser '{username}': {str(e)}")


@router.post("/auto-login")
async def auto_login(request: Request):
    """桌面端自动登录——仅限 localhost，返回 admin 角色 JWT。

    前端 Login.vue 挂载时自动调用此接口：
    - 成功（localhost 桌面端）→ 直接进入系统，跳过登录页
    - 失败（远程访问部署的服务器）→ 显示常规登录表单
    """
    if request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Not available from remote")

    token = jwt.encode(
        {"username": "admin", "role": "admin"},
        conf.jwt_secret_key,
        algorithm="HS256",
    )
    logger.debug("Desktop auto-login succeeded")
    return JSONResponse(content={
        "message": "Auto login successful",
        "user": {"username": "admin", "role": "admin"},
        "token": token,
    })
