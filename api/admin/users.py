"""管理后台 API - 用户管理"""
from . import router
from ..deps import admin_required, auth_required, system
from base.logger import logger
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

@router.get("/users")
@auth_required
@admin_required
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出所有用户(分页)。

    # ── 安全

    返回时移除 password 和 id 字段。

    Args:
        request: FastAPI 请求对象。
        page: 页码,从 1 开始。
        page_size: 每页条数,默认 20,最大 100。

    Returns:
        JSONResponse: ``{"total": int, "page": int, "page_size": int, "items": [...]}``。

    Raises:
        HTTPException 500: 查询失败。
    """
    try:
        result = system.data_store.get_all_users(page=page, page_size=page_size)
        items = result["items"]
        for u in items:
            u.pop("password", None)
            u.pop("id", None)
        return JSONResponse(content={
            "total": result["total"],
            "page": page,
            "page_size": page_size,
            "items": items,
        })
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users")
@auth_required
@admin_required
async def create_user(request: Request):
    """创建用户(可指定角色)。

    Args:
        request: FastAPI 请求对象,包含 JSON 体:
            ``{"username": str, "password": str, "role": "user"|"admin"}``。

    Returns:
        JSONResponse: ``{"message": "用户 'xxx' 创建成功"}``,状态码 201。

    Raises:
        HTTPException 400: 用户名/密码为空/长度不足,或角色非法。
        HTTPException 409: 用户名已存在。
        HTTPException 500: 创建失败。
    """
    try:
        data = await request.json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        role = data.get("role", "user").strip()
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        if role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="角色必须为 user 或 admin")
        if len(username) < 3:
            raise HTTPException(status_code=400, detail="用户名长度至少 3 位")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        success = system.data_store.insert_user(username, password, role=role)
        if not success:
            raise HTTPException(status_code=409, detail="用户名已存在")
        logger.info(f"管理员创建用户: username={username}, role={role}")
        return JSONResponse(content={"message": f"用户 '{username}' 创建成功"}, status_code=201)
    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"创建用户失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/users/{username}")
@auth_required
@admin_required
async def delete_user(request: Request, username: str):
    """删除用户(禁止删除自身)。

    Args:
        request: FastAPI 请求对象,从中获取当前登录用户信息。
        username: 要删除的用户名。

    Returns:
        JSONResponse: ``{"message": "用户 'xxx' 已删除"}``。

    Raises:
        HTTPException 400: 试图删除当前登录账户。
        HTTPException 404: 用户不存在。
        HTTPException 500: 删除失败。
    """
    try:
        current_user = request.state.user.get("username", "")
        if username == current_user:
            raise HTTPException(status_code=400, detail="不能删除当前登录账户")
        success = system.data_store.delete_user(username)
        if not success:
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        logger.info(f"管理员删除用户: {username}")
        return JSONResponse(content={"message": f"用户 '{username}' 已删除"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除用户失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{username}/role")
@auth_required
@admin_required
async def change_user_role(request: Request, username: str):
    """变更用户角色。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"role": "user"|"admin"}``。
        username: 目标用户名。

    Returns:
        JSONResponse: ``{"message": str, "user": {"username": str, "role": str}}``。

    Raises:
        HTTPException 400: 角色值非法。
        HTTPException 404: 用户不存在。
        HTTPException 500: 变更失败。
    """
    try:
        data = await request.json()
        new_role = data.get("role", "").strip()
        if new_role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="角色必须为 user 或 admin")
        success = system.data_store.update_user_role(username, new_role)
        if not success:
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        logger.info(f"用户角色变更: {username} -> {new_role}")
        return JSONResponse(content={
            "message": f"用户 '{username}' 角色已更新为 {new_role}",
            "user": {"username": username, "role": new_role},
        })
    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"变更用户角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{username}/password")
@auth_required
@admin_required
async def reset_password(request: Request, username: str):
    """重置用户密码。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"password": str}``。
        username: 目标用户名。

    Returns:
        JSONResponse: ``{"message": "用户 'xxx' 密码已重置"}``。

    Raises:
        HTTPException 400: 密码长度不足 6 位。
        HTTPException 404: 用户不存在。
        HTTPException 500: 重置失败。
    """
    try:
        data = await request.json()
        new_password = data.get("password", "").strip()
        if not new_password or len(new_password) < 6:
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        success = system.data_store.update_user_password(username, new_password)
        if not success:
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        logger.info(f"管理员重置用户密码: {username}")
        return JSONResponse(content={
            "message": f"用户 '{username}' 密码已重置",
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置密码失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
