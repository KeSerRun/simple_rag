"""管理后台 API - 配置管理"""


from . import router, _get_config_dict, _write_config_ini
from ..deps import admin_required, auth_required
from base.logger import logger
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


_CONFIG_SCHEMA = [
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

    {"key": "mineru_base_url", "label": "API Base URL", "group": "MinerU PDF 解析", "type": "string"},
    {"key": "mineru_api_key", "label": "API Key", "group": "MinerU PDF 解析", "type": "password"},
    {"key": "mineru_token_name", "label": "Token 名称", "group": "MinerU PDF 解析", "type": "string"},
    {"key": "mineru_model_version", "label": "模型版本", "group": "MinerU PDF 解析", "type": "select",
     "options": [{"label": "vlm", "value": "vlm"}, {"label": "lite", "value": "lite"}]},
    {"key": "mineru_language", "label": "语言", "group": "MinerU PDF 解析", "type": "string"},
    {"key": "mineru_max_concurrency", "label": "MinerU 最大并发数", "group": "MinerU PDF 解析", "type": "int", "min": 1, "max": 10},


    {"key": "retrieval_top_k", "label": "检索 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 100},
    {"key": "candidate_top_k", "label": "候选 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 50},
    {"key": "stop_words", "label": "文本停用词", "group": "检索配置", "type": "string", "textarea": True, "placeholder": "用逗号分隔"},

    {"key": "max_tool_iter", "label": "最大工具迭代次数", "group": "Agent 配置", "type": "int", "min": 1, "max": 100},
    {"key": "max_output_chars", "label": "最大输出字符", "group": "Agent 配置", "type": "int", "min": 512, "max": 524288},
    {"key": "eval_max_workers", "label": "评估并发查询数", "group": "Agent 配置", "type": "int", "min": 1, "max": 10},


    {"key": "search_backend", "label": "搜索后端", "group": "联网搜索配置", "type": "select",
     "options": [{"label": "DuckDuckGo", "value": "duckduckgo"}, {"label": "SearXNG", "value": "searxng"}, {"label": "博查 AI", "value": "bocha"}, {"label": "Bing", "value": "bing"}]},
    {"key": "searxng_url", "label": "SearXNG 地址", "group": "联网搜索配置", "type": "string", "placeholder": "仅后端=searxng 时使用"},
    {"key": "bocha_api_key", "label": "博查 API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "bing_api_key", "label": "Bing API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "search_timeout", "label": "搜索超时(秒)", "group": "联网搜索配置", "type": "int", "min": 5, "max": 60},

    {"key": "max_history_length", "label": "最大历史轮数", "group": "上下文治理", "type": "int", "min": 10, "max": 5000},
    {"key": "context_window_chars", "label": "上下文窗口字符数", "group": "上下文治理", "type": "int", "min": 10000, "max": 1000000},


    {"key": "app_log_level", "label": "应用日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "http_log_level", "label": "HTTP 日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "console_log_level", "label": "控制台日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},
    {"key": "user_log_level", "label": "用户操作日志级别", "group": "日志配置", "type": "select",
     "options": [{"label": "DEBUG", "value": "DEBUG"}, {"label": "INFO", "value": "INFO"}, {"label": "WARNING", "value": "WARNING"}, {"label": "ERROR", "value": "ERROR"}]},


    {"key": "max_user_storage_mb", "label": "用户存储上限(MB)", "group": "上传限制", "type": "int", "min": 0, "max": 10000},
]

@router.get("/config/schema")
@auth_required
@admin_required
async def get_config_schema(request: Request):
    """返回配置项 schema,前端据此动态渲染表单。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 配置 schema 列表,每项含 key/label/group/type 等字段。
    """
    return JSONResponse(content=_CONFIG_SCHEMA)

@router.get("/config")

@auth_required
@admin_required
async def get_config(request: Request):
    """获取当前配置(敏感字段脱敏)。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 字典形式的配置,secret 字段已用 ``*`` 脱敏。
    """


    return JSONResponse(content=_get_config_dict(masked=True))



@router.put("/config")

@auth_required
@admin_required

async def update_config(request: Request):
    """更新配置并写回 config.ini。

    # ── 处理流程

    1. 解析请求 JSON
    2. 调用 ``_write_config_ini`` 执行行级替换
    3. 返回更新后的完整配置(脱敏)

    Args:
        request: FastAPI 请求对象,包含 JSON 体(键值对字典)。

    Returns:
        JSONResponse: ``{"message": str, "config": dict}``。

    Raises:
        HTTPException 400: 请求体非 JSON 对象。
        HTTPException 500: 写入失败。
    """
    try:


        data = await request.json()


        if not data or not isinstance(data, dict):


            raise HTTPException(status_code=400, detail="请求体必须为 JSON 对象")



        success = _write_config_ini(data)

        return JSONResponse(content={

            "message": "配置更新成功" if success else "未检测到变更",

            "config": _get_config_dict(masked=True),
        })


    except HTTPException:
        raise

    except Exception as e:

        logger.error(f"更新配置失败: {e}")

        raise HTTPException(status_code=500, detail=str(e))
