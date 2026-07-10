# ===== 管理后台 API - 配置管理模块 =====
# 这个文件定义了配置管理的 API 接口，让管理员可以通过 HTTP 请求读取和修改系统配置
"""管理后台 API - 配置管理"""

# ===== 导入依赖模块 =====

from . import router
from . import _get_config_dict, _write_config_ini
from ..deps import admin_required, auth_required
from base.logger import logger
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


# ===== 配置项 schema 定义 =====
# 新增配置项时只需在此列表加一行，前端会自动渲染
_CONFIG_SCHEMA = [
    # ── LLM / API ──
    {"key": "chat_model", "label": "Chat 模型", "group": "LLM / API", "type": "string"},
    {"key": "openai_base_url", "label": "Chat Base URL", "group": "LLM / API", "type": "string"},
    {"key": "openai_api_key", "label": "Chat API Key", "group": "LLM / API", "type": "password"},
    {"key": "chat_reasoning_effort", "label": "推理力度", "group": "LLM / API", "type": "select",
     "options": [{"label": "不指定", "value": None}, {"label": "low", "value": "low"}, {"label": "medium", "value": "medium"}, {"label": "high", "value": "high"}]},
    {"key": "openai_embedding_model", "label": "Embedding 模型", "group": "LLM / API", "type": "string"},
    {"key": "embedding_base_url", "label": "Embedding Base URL", "group": "LLM / API", "type": "string"},
    {"key": "embedding_api_key", "label": "Embedding API Key", "group": "LLM / API", "type": "password",
     "placeholder": "留空则复用 Chat API Key"},
    {"key": "openai_embedding_dim", "label": "Embedding 维度", "group": "LLM / API", "type": "int", "min": 64, "max": 4096},
    {"key": "openai_timeout", "label": "超时时间(秒)", "group": "LLM / API", "type": "int", "min": 5, "max": 300},
    {"key": "openai_max_retries", "label": "最大重试次数", "group": "LLM / API", "type": "int", "min": 0, "max": 10},

    # ── MinerU ──
    {"key": "mineru_base_url", "label": "API Base URL", "group": "MinerU PDF 解析", "type": "string"},
    {"key": "mineru_api_key", "label": "API Key", "group": "MinerU PDF 解析", "type": "password"},
    {"key": "mineru_token_name", "label": "Token 名称", "group": "MinerU PDF 解析", "type": "string"},
    {"key": "mineru_model_version", "label": "模型版本", "group": "MinerU PDF 解析", "type": "select",
     "options": [{"label": "vlm", "value": "vlm"}, {"label": "lite", "value": "lite"}]},
    {"key": "mineru_language", "label": "语言", "group": "MinerU PDF 解析", "type": "string"},

    # ── 检索 ──
    {"key": "retrieval_top_k", "label": "检索 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 100},
    {"key": "candidate_top_k", "label": "候选 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 50},
    {"key": "stop_words", "label": "文本停用词", "group": "检索配置", "type": "string", "textarea": True, "placeholder": "用逗号分隔"},

    # ── Agent ──
    {"key": "max_tool_iter", "label": "最大工具迭代次数", "group": "Agent 配置", "type": "int", "min": 1, "max": 30},
    {"key": "max_output_tokens", "label": "最大输出 Token", "group": "Agent 配置", "type": "int", "min": 512, "max": 65536},
    {"key": "parse_workers", "label": "PDF 解析并发数", "group": "Agent 配置", "type": "int", "min": 1, "max": 8},

    # ── 搜索 ──
    {"key": "search_backend", "label": "搜索后端", "group": "联网搜索配置", "type": "select",
     "options": [{"label": "DuckDuckGo", "value": "duckduckgo"}, {"label": "SearXNG", "value": "searxng"}, {"label": "博查 AI", "value": "bocha"}, {"label": "Bing", "value": "bing"}]},
    {"key": "searxng_url", "label": "SearXNG 地址", "group": "联网搜索配置", "type": "string", "placeholder": "仅后端=searxng 时使用"},
    {"key": "bocha_api_key", "label": "博查 API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "bing_api_key", "label": "Bing API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "search_timeout", "label": "搜索超时(秒)", "group": "联网搜索配置", "type": "int", "min": 5, "max": 60},

    # ── 对话历史 ──
    {"key": "max_history_length", "label": "最大保留轮次", "group": "对话历史配置", "type": "int", "min": 10, "max": 2000},
    {"key": "context_window_tokens", "label": "上下文窗口(Token)", "group": "对话历史配置", "type": "int", "min": 4096, "max": 524288},
    {"key": "consolidation_ratio", "label": "压缩触发比例", "group": "对话历史配置", "type": "float", "min": 0.1, "max": 0.9, "step": 0.05},

    # ── 日志 ──
    {"key": "app_log_level", "label": "应用日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "http_log_level", "label": "HTTP 日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "console_log_level", "label": "控制台日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "user_log_level", "label": "用户操作日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},

    # ── 上传 ──
    {"key": "max_user_storage_mb", "label": "用户存储上限(MB)", "group": "上传限制", "type": "int", "min": 0, "max": 10000},
]


# ===== API: 获取配置 schema =====
@router.get("/config/schema")
@auth_required
@admin_required
async def get_config_schema(request: Request):
    """返回配置项 schema，前端据此动态渲染表单"""
    return JSONResponse(content=_CONFIG_SCHEMA)


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
