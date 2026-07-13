import json
# ---- JWT 认证接口 ----
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger

from .deps import system

# ---- JWT 认证 ----
router = APIRouter(prefix="/api", tags=["auth"])


# ---- 用户注册 ----
@router.post("/register")
async def register(request: Request):
    """处理用户注册"""
    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")
        # ---- 注册 ----
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


# ---- 用户登录 ----
@router.post("/login")
async def login(request: Request):
    """处理用户登录,验证成功后下发 JWT"""
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


# ---- create_superusers ----
def create_superusers():
    """启动时根据配置中的超级管理员用户名/密码创建账户(若已存在则跳过)"""
    for username, password in zip(conf.superuser_usernames, conf.superuser_passwords):
        try:
            system.data_store.insert_user(username, password, role="admin")
            logger.debug(f"Superuser '{username}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating superuser '{username}': {str(e)}")
