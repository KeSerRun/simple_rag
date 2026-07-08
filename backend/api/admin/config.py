# ===== 管理后台 API - 配置管理模块 =====
# 这个文件定义了配置管理的 API 接口，让管理员可以通过 HTTP 请求读取和修改系统配置
"""管理后台 API - 配置管理"""

# ===== 导入依赖模块 =====

# 从当前包的 __init__.py 中导入 router 对象，这个 router 是 APIRouter 的实例
# 用于注册路由（URL 路径和处理函数的映射关系）
from . import router

# 从当前包的 __init__.py 中导入两个工具函数：
# _get_config_dict：把 config.ini 文件读取出来，返回一个字典（Python 的键值对结构）
# _write_config_ini：把前端传过来的配置数据写回到 config.ini 文件中
from . import _get_config_dict, _write_config_ini

# 从上级目录的 deps.py 文件中导入两个装饰器函数
# admin_required：检查当前登录用户是不是管理员，不是就拒绝访问
# auth_required：检查当前请求有没有登录认证，没登录就拒绝访问
from ..deps import admin_required, auth_required

# 从 base/logger.py 中导入日志记录器 logger，用于在控制台或日志文件中记录程序运行信息
from base.logger import logger

# 从 FastAPI 框架中导入 HTTPException 和 Request 两个类
# HTTPException：用于主动抛出 HTTP 错误响应（比如 400 参数错误、500 服务器错误）
# Request：代表客户端发来的 HTTP 请求，可以从中获取请求体、请求头等信息
from fastapi import HTTPException, Request

# 从 FastAPI 的响应模块中导入 JSONResponse，用于返回标准的 JSON 格式响应给前端
from fastapi.responses import JSONResponse


# ===== 获取配置的 API 接口 =====

# @router.get("/config") 表示：当客户端发送 GET 请求到 /config 这个网址时，就执行下面这个函数
@router.get("/config")
# @auth_required 是一个装饰器，在真正执行函数之前先检查用户是否已登录
# 如果没登录，直接返回 401 未授权错误，不会执行下面的函数
@auth_required
# @admin_required 是第二个装饰器，在已登录的前提下再检查用户是否是管理员
# 如果不是管理员，直接返回 403 禁止访问错误，不会执行下面的函数
@admin_required
# 定义异步函数 get_config，参数 request 是 FastAPI 自动传入的 HTTP 请求对象
# async 表示这是一个异步函数，运行过程中可以让出 CPU 给其他任务，提高并发处理能力
async def get_config(request: Request):
    """获取当前配置（敏感字段脱敏）"""
    # 调用 _get_config_dict 函数读取配置文件，masked=True 表示对敏感字段（如密码）做脱敏处理
    # 脱敏就是把密码等敏感信息替换成 ****，防止泄露
    # JSONResponse 把返回的字典转换成 JSON 格式的 HTTP 响应发送给前端
    return JSONResponse(content=_get_config_dict(masked=True))


# ===== 更新配置的 API 接口 =====

# @router.put("/config") 表示：当客户端发送 PUT 请求到 /config 这个网址时，就执行下面这个函数
# PUT 方法通常用于更新资源（这里是更新系统配置）
@router.put("/config")
# 同样需要先检查用户是否已登录
@auth_required
# 再检查用户是否是管理员
@admin_required
# 定义异步函数 update_config，用于处理配置更新请求
# 前端会把新的配置数据放在 HTTP 请求的 body（请求体）中发送过来
async def update_config(request: Request):
    """更新配置并写回 config.ini"""
    # 使用 try 块来捕获可能发生的异常，防止程序因为错误而崩溃
    try:
        # await request.json() 异步地从 HTTP 请求体中解析出 JSON 数据
        # request.json() 返回的是 Python 字典类型的数据
        # async/await 是 Python 异步编程的写法，await 表示等待这个操作完成
        data = await request.json()
        # if not data 判断 data 是否为空（None、空字典等都会被认为是空）
        # isinstance(data, dict) 判断 data 是不是一个字典类型
        # 如果 data 为空或者不是字典类型，说明前端传的数据格式不对
        if not data or not isinstance(data, dict):
            # 主动抛出 HTTP 异常，状态码 400 表示"请求参数有误"
            # detail 参数是给前端看的错误提示信息，告诉用户需要传一个 JSON 对象
            raise HTTPException(status_code=400, detail="请求体必须为 JSON 对象")
        # 调用 _write_config_ini 函数，把前端传过来的配置数据写入 config.ini 文件
        # 函数返回 True 表示写入成功且有实际变更，返回 False 表示数据和原来一样没有变更
        success = _write_config_ini(data)
        # 构造一个字典作为响应内容，JSONResponse 会把它转换成 JSON 格式返回给前端
        # "message" 是操作结果的提示信息
        # "config" 是更新后的完整配置（敏感字段已脱敏），方便前端刷新显示
        return JSONResponse(content={
            # 如果 success 为 True 显示"配置更新成功"，否则显示"未检测到变更"
            # 这是一种 Python 的条件表达式：值1 if 条件 else 值2
            "message": "配置更新成功" if success else "未检测到变更",
            # 再次调用 _get_config_dict 获取最新的配置，保证返回给前端的是最新的数据
            "config": _get_config_dict(masked=True),
        })
    # 拦截 HTTPException 类型的异常
    # except HTTPException: raise 表示如果是我们自己主动抛出的 HTTP 错误，就直接原样继续抛出
    # 让 FastAPI 框架来处理它，返回对应的错误响应给前端
    except HTTPException:
        raise
    # 拦截其他所有类型的异常（Exception 是所有异常的基类）
    # as e 把捕获到的异常对象赋值给变量 e，方便在日志中记录异常信息
    except Exception as e:
        # 使用 logger.error 把错误信息记录到日志文件中
        # 这是一种负责任的错误处理方式：既记录了日志方便排查问题，又给前端返回了友好的错误提示
        logger.error(f"更新配置失败: {e}")
        # 抛出 HTTP 异常，状态码 500 表示"服务器内部错误"
        # detail 参数把异常对象的字符串形式返回给前端，方便前端知道出了什么问题
        raise HTTPException(status_code=500, detail=str(e))
