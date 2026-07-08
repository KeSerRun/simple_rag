"""管理后台 API - 日志查看"""
# ===== 上面是模块文档字符串 =====
# 这个字符串说明了本文件的作用：管理后台的API，专门用来查看和下载日志文件

# ===== 导入Python内置模块 =====
import os  # 导入os模块，用于处理文件路径、判断文件是否存在、获取文件信息等操作系统相关操作
from datetime import datetime  # 从datetime模块导入datetime类，用于把时间戳转换成可读的日期时间格式

# ===== 导入项目内部模块 =====
from . import router  # 从当前包（admin包）的__init__.py中导入router对象，这个router用于注册管理后台的路由
from ..deps import admin_required, auth_required  # 从父级目录的deps模块导入两个依赖函数：auth_required(需要登录)和admin_required(需要管理员权限)
from base.config import conf  # 从base包的config模块导入conf对象，conf是项目的配置对象，里面包含日志路径等配置项
from base.logger import logger  # 从base包的logger模块导入logger对象，用于记录日志信息（方便开发者排查问题）

# ===== 导入第三方框架FastAPI相关类 =====
from fastapi import HTTPException, Query, Request  # 从fastapi导入：HTTPException(用于返回HTTP错误响应)、Query(用于声明查询参数)、Request(代表HTTP请求对象)
from fastapi.responses import JSONResponse  # 从fastapi.responses导入JSONResponse，用于返回JSON格式的HTTP响应


# ===== 接口1: 获取日志文件列表 =====
@router.get("/logs")  # 使用装饰器注册一个GET请求的路由，路径是/logs，也就是说用户访问/logs就会触发这个函数
@auth_required  # 使用装饰器要求用户必须登录，未登录的请求会被拦截并返回401错误
@admin_required  # 使用装饰器要求用户必须是管理员，非管理员访问会被拦截并返回403错误
async def list_logs(request: Request):  # 定义一个异步函数list_logs，它接收一个Request类型的参数request，代表用户的HTTP请求
    """列出 log 目录下所有日志文件"""  # 函数的文档字符串，说明这个函数的作用：列出日志目录下的所有日志文件
    try:  # 使用try-except捕获可能发生的异常，避免程序崩溃
        log_dir = conf.log_path  # 从配置对象conf中获取日志目录的路径，赋值给log_dir变量
        if not os.path.isdir(log_dir):  # 判断log_dir这个路径是否是一个有效的目录
            return JSONResponse(content={"files": [], "log_path": log_dir})  # 如果不是目录，直接返回一个空的文件列表和日志路径给前端
        files = []  # 初始化一个空列表files，用来存放每个日志文件的信息
        for fname in os.listdir(log_dir):  # 使用os.listdir()遍历日志目录下的所有文件和子文件夹，fname是文件名
            fpath = os.path.join(log_dir, fname)  # 把目录路径和文件名拼接成完整的文件路径，赋值给fpath
            if os.path.isfile(fpath):  # 判断fpath是否是一个文件（而不是文件夹）
                stat = os.stat(fpath)  # 如果是文件，使用os.stat()获取文件的详细信息（大小、修改时间等），存储在stat对象中
                files.append({  # 把文件信息以字典形式添加到files列表中
                    "name": fname,  # 文件的名称（如"app.log"）
                    "size": stat.st_size,  # 文件的大小（字节数），来自stat对象的st_size属性
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),  # 文件的最后修改时间：先把时间戳转为datetime对象，再转成ISO格式的字符串
                })  # 字典结束
        files.sort(key=lambda x: x["modified"], reverse=True)  # 对文件列表按修改时间倒序排序，最新的文件排在最前面
        return JSONResponse(content={"files": files, "log_path": log_dir})  # 返回JSON格式的响应，包含文件列表和日志目录路径
    except Exception as e:  # 如果在try代码块中发生了任何异常，将异常对象赋值给变量e
        logger.error(f"获取日志列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出一个HTTP 500错误（服务器内部错误），并将错误详情作为detail返回给前端


# ===== 接口2: 下载日志文件 =====
@router.get("/logs/{log_file:path}/download")  # 注册GET请求的路由，路径模式如/logs/some.log/download，{log_file:path}表示捕获URL中的路径部分作为变量log_file
@auth_required  # 要求用户必须登录
@admin_required  # 要求用户必须是管理员
async def download_log(request: Request, log_file: str):  # 定义异步函数download_log，接收请求对象request和URL中捕获的log_file路径参数
    """下载完整的日志文件"""  # 函数说明：下载完整的日志文件供用户保存到本地
    try:  # 异常捕获开始
        log_dir = conf.log_path  # 从配置获取日志目录路径
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))  # 把日志目录和文件名拼接成完整路径，再用normpath规范化路径格式（处理../等特殊符号，防止路径穿越攻击）
        if not safe_path.startswith(os.path.normpath(log_dir)):  # 检查规范化后的完整路径是否以规范化后的日志目录开头——这确保用户无法通过../跳出日志目录去下载其他文件
            raise HTTPException(status_code=403, detail="禁止访问该路径")  # 如果路径不在日志目录下，抛出403禁止访问错误
        if not os.path.isfile(safe_path):  # 判断规范化后的路径是否是一个真实存在的文件
            raise HTTPException(status_code=404, detail="日志文件不存在")  # 如果文件不存在，抛出404错误，提示日志文件不存在

        from fastapi.responses import FileResponse  # 在函数内部导入FileResponse，它是FastAPI提供的用于返回文件的响应类（延迟导入，节省资源）

        filename = os.path.basename(safe_path)  # 使用os.path.basename从完整路径中提取出文件名（例如从/var/log/app.log提取出app.log）
        return FileResponse(  # 返回一个FileResponse对象，让浏览器下载文件
            safe_path,  # 第一个参数：要返回的文件的完整路径
            media_type="text/plain",  # 设置媒体类型为纯文本，告诉浏览器这是一个文本文件
            filename=filename,  # 设置下载时显示的文件名
            headers={  # 自定义HTTP响应头
                "Content-Disposition": f'attachment; filename="{filename}"',  # Content-Disposition设为attachment表示触发下载，filename指定下载保存的文件名
            },  # 响应头字典结束
        )  # FileResponse调用结束
    except HTTPException:  # 如果捕获到的是HTTPException类型的异常
        raise  # 直接重新抛出，不做额外处理（因为HTTPException本身就是正常的错误响应）
    except Exception as e:  # 如果捕获到其他类型的异常
        logger.error(f"下载日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出500服务器内部错误


# ===== 接口3: 读取日志文件内容（分页查看） =====
@router.get("/logs/{log_file:path}")  # 注册GET请求的路由，路径模式如/logs/some.log，注意这个路由和上面的/download路由不同，它没有/download后缀
@auth_required  # 要求用户必须登录
@admin_required  # 要求用户必须是管理员
async def read_log(  # 定义异步函数read_log，用于读取日志文件的指定行数内容
    request: Request,  # 接收HTTP请求对象
    log_file: str,  # 从URL路径中捕获的日志文件名
    lines: int = Query(200, ge=1, le=5000),  # 查询参数lines（默认200，最小1，最大5000），表示要返回多少行日志
    offset: int = Query(0, ge=0),  # 查询参数offset（默认0，最小0），表示跳过文件开头多少行
):
    """读取日志文件内容

    - lines:   返回行数(默认 200, 最大 5000)
    - offset:  跳过行数(默认 0)
    - 支持 ?reverse=1 从尾部读取
    """
    # 上面是文档字符串，说明参数含义：
    # lines参数控制返回多少行，默认200行，最多5000行
    # offset参数控制跳过多少行，默认不跳过
    # 如果加上?reverse=1参数，则从文件末尾开始读取
    try:  # 异常捕获开始
        log_dir = conf.log_path  # 从配置中获取日志目录路径
        # 安全校验: 防止路径穿越
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))  # 拼接并规范化路径，防止用户通过../来读取日志目录以外的文件
        if not safe_path.startswith(os.path.normpath(log_dir)):  # 检查最终路径是否仍在日志目录下
            raise HTTPException(status_code=403, detail="禁止访问该路径")  # 如果不在，抛出403禁止访问错误
        if not os.path.isfile(safe_path):  # 判断文件是否存在
            raise HTTPException(status_code=404, detail="日志文件不存在")  # 如果不存在，抛出404错误
        if safe_path.endswith(".npy"):  # 检查文件后缀是否是.npy（NumPy的二进制文件格式）
            raise HTTPException(status_code=403, detail="禁止读取二进制文件")  # 如果是二进制文件，禁止读取，防止乱码或安全问题

        reverse = request.query_params.get("reverse", "0") == "1"  # 从请求的查询参数中获取reverse的值，如果传了reverse=1表示从文件尾部开始读，否则从文件开头读

        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:  # 以只读模式打开日志文件，指定UTF-8编码，errors="replace"表示遇到无法解码的字符时用替代字符替换而不是报错
            all_lines = f.readlines()  # 读取文件的所有行，返回一个列表，列表中的每个元素是一行字符串

        total = len(all_lines)  # 计算文件总行数，赋值给total变量，后面会返回给前端用于分页展示
        if reverse:  # 如果启用了反向读取（从文件尾部读取）
            start = max(0, total - offset - lines)  # 计算起始行号：从总行数减去offset再减去lines，但不能小于0
            end = total - offset  # 计算结束行号：总行数减去offset
            if end <= 0:  # 如果结束行号小于等于0，说明读取范围完全超出了文件范围
                return JSONResponse(content={"lines": [], "total": total, "file": log_file})  # 返回空行列表、总行数和文件名
            chunk = all_lines[start:end]  # 从all_lines列表中切取起始行到结束行之间的内容，得到要返回的行片段
        else:  # 如果是从文件头部读取（默认方式）
            start = offset  # 起始行号就是offset的值
            end = offset + lines  # 结束行号是offset加上lines
            chunk = all_lines[start:end]  # 从all_lines中按[start:end]范围切片，取出对应行

        # 去除换行符
        content = [line.rstrip("\n\r") for line in chunk]  # 用列表推导式遍历每一行，使用rstrip去掉行尾的换行符\n和回车符\r，得到纯文本内容

        return JSONResponse(content={  # 返回JSON格式的响应，包含以下字段：
            "file": log_file,  # 日志文件名
            "total": total,  # 日志文件总行数，前端可以用这个做分页
            "start": start,  # 本次返回的起始行号
            "end": min(end, total),  # 本次返回的结束行号（不能超过总行数）
            "lines": content,  # 本次返回的具体行内容列表
        })  # JSONResponse结束
    except HTTPException:  # 如果捕获到HTTPException异常
        raise  # 直接重新抛出，不做额外封装
    except Exception as e:  # 如果捕获到其他异常
        logger.error(f"读取日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出500服务器内部错误
