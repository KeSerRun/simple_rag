# ===== 文件开头：模块文档字符串 =====
# 这是 Python 模块的文档字符串，用三个双引号包裹，说明这个文件的功能是"管理后台 API - 用户管理"
"""管理后台 API - 用户管理"""

# ===== 导入依赖模块 =====
# 从当前包（admin 包）的 __init__.py 中导入 router 对象，router 是 APIRouter 实例，用于注册路由
from . import router
# 从上级目录的 deps.py 模块导入 admin_required（管理员权限校验装饰器）、auth_required（登录认证装饰器）、system（全局系统实例）
from ..deps import admin_required, auth_required, system
# 从 base.logger 模块导入 logger 对象，用于记录日志（方便排查问题）
from base.logger import logger
# 从 FastAPI 框架导入 HTTPException（HTTP 异常类）、Query（查询参数声明）、Request（请求对象）
from fastapi import HTTPException, Query, Request
# 从 FastAPI 的响应模块导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应
from fastapi.responses import JSONResponse


# ===== 获取用户列表接口 =====
# 使用 @router.get("/users") 注册一个 GET 请求的路由，路径为 /users，即访问 /api/admin/users 会触发此函数
@router.get("/users")
# 使用 @auth_required 装饰器，表示这个接口需要用户登录认证才能访问（未登录会返回 401）
@auth_required
# 使用 @admin_required 装饰器，表示这个接口需要管理员权限才能访问（非管理员会返回 403）
@admin_required
# 定义一个异步函数 list_users，用于列出所有用户（支持分页），参数 request 是 FastAPI 的 Request 对象，包含请求的所有信息
async def list_users(
    # request 参数：FastAPI 自动注入的 HTTP 请求对象，包含请求头、状态等信息
    request: Request,
    # page 参数：查询参数，默认值为 1，ge=1 表示最小值为 1（页数不能小于 1）
    page: int = Query(1, ge=1),
    # page_size 参数：查询参数，默认值为 20，ge=1 表示最小 1，le=100 表示最大 100（每页条数范围）
    page_size: int = Query(20, ge=1, le=100),
):
    # 函数的文档字符串：说明这个函数的功能是"列出所有用户（分页）"
    """列出所有用户（分页）"""
    # 使用 try 块捕获可能发生的异常，保证程序不会因为错误而崩溃
    try:
        # 调用 system.data_store.get_all_users() 方法从数据库获取所有用户数据，传入 page（当前页码）和 page_size（每页条数）
        result = system.data_store.get_all_users(page=page, page_size=page_size)
        # 从返回的结果字典中取出 "items" 键对应的值，即当前页的用户列表
        items = result["items"]
        # ===== 数据脱敏处理 =====
        # 遍历用户列表中的每一个用户（u 代表单个用户字典）
        for u in items:
            # 移除用户字典中的 "password" 字段（密码不能返回给前端，防止泄露）
            u.pop("password", None)
            # 移除用户字典中的 "id" 字段（数据库内部 ID 不需要暴露给前端）
            u.pop("id", None)
        # 返回一个 JSON 格式的成功响应，包含分页信息和用户列表
        return JSONResponse(content={
            # 用户总数，前端用于计算总页数
            "total": result["total"],
            # 当前页码，原样返回
            "page": page,
            # 每页条数，原样返回
            "page_size": page_size,
            # 当前页的用户列表（已脱敏，不包含密码和 ID）
            "items": items,
        })
    # 如果在 try 块中发生了任何异常，用 except 捕获异常对象 e
    except Exception as e:
        # 使用 logger.error() 记录错误日志，方便程序员排查问题
        logger.error(f"获取用户列表失败: {e}")
        # 抛出 HTTP 异常，状态码 500 表示服务器内部错误，detail 是给前端的错误描述
        raise HTTPException(status_code=500, detail=str(e))


# ===== 创建用户接口 =====
# 使用 @router.post("/users") 注册一个 POST 请求的路由，路径为 /users，用于创建新用户
@router.post("/users")
# 登录认证装饰器：未登录的用户不能访问此接口
@auth_required
# 管理员权限装饰器：只有管理员才能创建用户
@admin_required
# 定义一个异步函数 create_user，用于创建新用户（可以指定角色），参数 request 是前端发来的 HTTP 请求
async def create_user(request: Request):
    # 函数的文档字符串：说明功能是"创建用户（可指定角色）"
    """创建用户（可指定角色）"""
    # 使用 try 块捕获可能发生的异常
    try:
        # 从 HTTP 请求体中解析 JSON 数据，await 表示等待异步操作完成，返回一个字典
        data = await request.json()
        # 从 JSON 数据中获取 "username" 字段，默认值为空字符串，并去掉首尾空格
        username = data.get("username", "").strip()
        # 从 JSON 数据中获取 "password" 字段，默认值为空字符串，并去掉首尾空格
        password = data.get("password", "").strip()
        # 从 JSON 数据中获取 "role" 字段，默认值为 "user"（普通用户），并去掉首尾空格
        role = data.get("role", "user").strip()
        # 检查用户名或密码是否为空（Python 中空字符串的布尔值为 False）
        if not username or not password:
            # 如果为空，抛出 HTTP 异常，状态码 400 表示客户端请求错误，并给出提示信息
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        # 检查角色是否合法（只能是 "user" 普通用户 或 "admin" 管理员）
        if role not in ("user", "admin"):
            # 如果角色不是这两个值之一，抛出 400 异常
            raise HTTPException(status_code=400, detail="角色必须为 user 或 admin")
        # 检查用户名长度是否小于 3 个字符
        if len(username) < 3:
            # 如果小于 3，抛出 400 异常，提示用户名太短
            raise HTTPException(status_code=400, detail="用户名长度至少 3 位")
        # 检查密码长度是否小于 6 个字符
        if len(password) < 6:
            # 如果小于 6，抛出 400 异常，提示密码太短
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        # 调用 system.data_store.insert_user() 方法将用户插入数据库，返回布尔值表示是否成功
        success = system.data_store.insert_user(username, password, role=role)
        # 如果 insert_user 返回 False，表示用户名已存在（数据库有唯一约束）
        if not success:
            # 抛出 409 异常（Conflict 冲突），提示用户名已存在
            raise HTTPException(status_code=409, detail="用户名已存在")
        # 使用 logger.info() 记录一条信息级别的日志，记录管理员创建了哪个用户
        logger.info(f"管理员创建用户: username={username}, role={role}")
        # 返回 JSON 响应，状态码 201 表示资源创建成功，message 是给前端看的成功提示
        return JSONResponse(content={"message": f"用户 '{username}' 创建成功"}, status_code=201)
    # 捕获 HTTPException 类型的异常（这是上面手动抛出的已知异常）
    except HTTPException:
        # 直接重新抛出，不做额外处理（让 FastAPI 框架来处理这些已知异常）
        raise
    # 捕获其他所有未知类型的异常（比如数据库连接失败等）
    except Exception as e:
        # 记录错误日志
        logger.error(f"创建用户失败: {e}")
        # 抛出 500 服务器内部错误，并附带错误详情
        raise HTTPException(status_code=500, detail=str(e))


# ===== 删除用户接口 =====
# 使用 @router.delete("/users/{username}") 注册一个 DELETE 请求的路由，路径中的 {username} 是路径参数，表示要删除的用户名
@router.delete("/users/{username}")
# 登录认证装饰器
@auth_required
# 管理员权限装饰器
@admin_required
# 定义异步函数 delete_user，用于删除指定用户，参数 request 是请求对象，username 是从 URL 路径中提取的用户名
async def delete_user(request: Request, username: str):
    # 文档字符串：说明功能是"删除用户（禁止删除自身）"
    """删除用户（禁止删除自身）"""
    # 使用 try 块捕获异常
    try:
        # 从 request.state.user 获取当前登录用户的信息（字典），取出 "username" 字段，默认空字符串
        current_user = request.state.user.get("username", "")
        # 判断要删除的用户名是否等于当前登录的用户名（防止管理员删除自己的账户）
        if username == current_user:
            # 如果是自己删自己，抛出 400 异常，提示不能删除当前登录账户
            raise HTTPException(status_code=400, detail="不能删除当前登录账户")
        # 调用 system.data_store.delete_user() 方法从数据库删除该用户，返回布尔值表示是否成功
        success = system.data_store.delete_user(username)
        # 如果删除失败（返回 False），说明用户不存在
        if not success:
            # 抛出 404 异常（Not Found），提示用户不存在
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        # 记录日志：管理员删除了哪个用户
        logger.info(f"管理员删除用户: {username}")
        # 返回 JSON 响应，提示删除成功
        return JSONResponse(content={"message": f"用户 '{username}' 已删除"})
    # 重新抛出已知的 HTTP 异常
    except HTTPException:
        raise
    # 捕获其他未知异常
    except Exception as e:
        # 记录错误日志
        logger.error(f"删除用户失败: {e}")
        # 抛出 500 服务器内部错误
        raise HTTPException(status_code=500, detail=str(e))


# ===== 变更用户角色接口 =====
# 使用 @router.put("/users/{username}/role") 注册一个 PUT 请求的路由，用于修改指定用户的角色
@router.put("/users/{username}/role")
# 登录认证装饰器
@auth_required
# 管理员权限装饰器
@admin_required
# 定义异步函数 change_user_role，用于变更用户的角色（普通用户 <-> 管理员）
async def change_user_role(request: Request, username: str):
    # 文档字符串：说明功能是"变更用户角色"
    """变更用户角色"""
    # 使用 try 块捕获异常
    try:
        # 从请求体中解析 JSON 数据
        data = await request.json()
        # 从 JSON 中获取 "role" 字段，默认空字符串，去掉首尾空格，得到新角色
        new_role = data.get("role", "").strip()
        # 检查新角色是否合法（只能是 "user" 或 "admin"）
        if new_role not in ("user", "admin"):
            # 如果不合法，抛出 400 异常
            raise HTTPException(status_code=400, detail="角色必须为 user 或 admin")
        # 调用 system.data_store.update_user_role() 方法更新用户的角色，返回布尔值表示成功与否
        success = system.data_store.update_user_role(username, new_role)
        # 如果更新失败（用户不存在），返回 False
        if not success:
            # 抛出 404 异常，提示用户不存在
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        # 记录日志：谁的角色被改成了什么
        logger.info(f"用户角色变更: {username} -> {new_role}")
        # 返回 JSON 响应，包含成功消息和更新后的用户信息
        return JSONResponse(content={
            # 成功提示消息
            "message": f"用户 '{username}' 角色已更新为 {new_role}",
            # 返回更新后的用户信息（用户名和新角色）
            "user": {"username": username, "role": new_role},
        })
    # 重新抛出已知的 HTTP 异常
    except HTTPException:
        raise
    # 捕获其他未知异常
    except Exception as e:
        # 记录错误日志
        logger.error(f"变更用户角色失败: {e}")
        # 抛出 500 服务器内部错误
        raise HTTPException(status_code=500, detail=str(e))


# ===== 重置用户密码接口 =====
# 使用 @router.put("/users/{username}/password") 注册一个 PUT 请求的路由，用于重置指定用户的密码
@router.put("/users/{username}/password")
# 登录认证装饰器
@auth_required
# 管理员权限装饰器
@admin_required
# 定义异步函数 reset_password，用于管理员重置用户的密码
async def reset_password(request: Request, username: str):
    # 文档字符串：说明功能是"重置用户密码"
    """重置用户密码"""
    # 使用 try 块捕获异常
    try:
        # 从请求体中解析 JSON 数据
        data = await request.json()
        # 从 JSON 中获取 "password" 字段（新密码），默认空字符串，去掉首尾空格
        new_password = data.get("password", "").strip()
        # 检查新密码是否为空，或者长度是否小于 6 位
        if not new_password or len(new_password) < 6:
            # 如果不满足条件，抛出 400 异常，提示密码至少需要 6 位
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        # 调用 system.data_store.update_user_password() 方法更新密码，返回布尔值表示是否成功
        success = system.data_store.update_user_password(username, new_password)
        # 如果更新失败（用户不存在），返回 False
        if not success:
            # 抛出 404 异常，提示用户不存在
            raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
        # 记录日志：管理员重置了哪个用户的密码
        logger.info(f"管理员重置用户密码: {username}")
        # 返回 JSON 响应，提示密码重置成功
        return JSONResponse(content={
            # 成功消息
            "message": f"用户 '{username}' 密码已重置",
        })
    # 重新抛出已知的 HTTP 异常
    except HTTPException:
        raise
    # 捕获其他未知异常
    except Exception as e:
        # 记录错误日志
        logger.error(f"重置密码失败: {e}")
        # 抛出 500 服务器内部错误
        raise HTTPException(status_code=500, detail=str(e))
