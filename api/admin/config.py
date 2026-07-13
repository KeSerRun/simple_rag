# ===== 管理后台 API - 配置管理模块 =====

"""管理后台 API - 配置管理"""


from . import router, _get_config_dict, _write_config_ini
from ..deps import admin_required, auth_required
from base.logger import logger
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


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
    {"key": "mineru_max_concurrency", "label": "MinerU 最大并发数", "group": "MinerU PDF 解析", "type": "int", "min": 1, "max": 10},


    {"key": "retrieval_top_k", "label": "检索 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 100},
    {"key": "candidate_top_k", "label": "候选 Top-K", "group": "检索配置", "type": "int", "min": 1, "max": 50},
    {"key": "stop_words", "label": "文本停用词", "group": "检索配置", "type": "string", "textarea": True, "placeholder": "用逗号分隔"},

    # ── Agent ──
    {"key": "max_tool_iter", "label": "最大工具迭代次数", "group": "Agent 配置", "type": "int", "min": 1, "max": 100},
    {"key": "max_output_chars", "label": "最大输出字符", "group": "Agent 配置", "type": "int", "min": 512, "max": 524288},
    {"key": "eval_max_workers", "label": "评估并发查询数", "group": "Agent 配置", "type": "int", "min": 1, "max": 10},


    {"key": "search_backend", "label": "搜索后端", "group": "联网搜索配置", "type": "select",
     "options": [{"label": "DuckDuckGo", "value": "duckduckgo"}, {"label": "SearXNG", "value": "searxng"}, {"label": "博查 AI", "value": "bocha"}, {"label": "Bing", "value": "bing"}]},
    {"key": "searxng_url", "label": "SearXNG 地址", "group": "联网搜索配置", "type": "string", "placeholder": "仅后端=searxng 时使用"},
    {"key": "bocha_api_key", "label": "博查 API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "bing_api_key", "label": "Bing API Key", "group": "联网搜索配置", "type": "password"},
    {"key": "search_timeout", "label": "搜索超时(秒)", "group": "联网搜索配置", "type": "int", "min": 5, "max": 60},

    # ── 对话历史 ──
    {"key": "max_history_length", "label": "最大保留轮次", "group": "对话历史配置", "type": "int", "min": 10, "max": 2000},
    {"key": "context_window_chars", "label": "上下文窗口(字符)", "group": "对话历史配置", "type": "int", "min": 4096, "max": 524288},
    {"key": "consolidation_ratio", "label": "压缩触发比例", "group": "对话历史配置", "type": "float", "min": 0.1, "max": 0.9, "step": 0.05},


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
    """返回配置项 schema，前端据此动态渲染表单"""
    return JSONResponse(content=_CONFIG_SCHEMA)

@router.get("/config")

@auth_required
@admin_required
async def get_config(request: Request):
    """获取当前配置（敏感字段脱敏）"""


    return JSONResponse(content=_get_config_dict(masked=True))


# ===== 更新配置的 API 接口 =====

@router.put("/config")

@auth_required
@admin_required

async def update_config(request: Request):
    """更新配置并写回 config.ini"""

    try:


        data = await request.json()
        # if not data 判断 data 是否为空（None、空字典等都会被认为是空）


        if not data or not isinstance(data, dict):


            raise HTTPException(status_code=400, detail="请求体必须为 JSON 对象")


        success = _write_config_ini(data)

        # "message" 是操作结果的提示信息
        return JSONResponse(content={

            # 这是一种 Python 的条件表达式：值1 if 条件 else 值2
            "message": "配置更新成功" if success else "未检测到变更",

            "config": _get_config_dict(masked=True),
        })
    # 拦截 HTTPException 类型的异常


    except HTTPException:
        raise
    # 拦截其他所有类型的异常（Exception 是所有异常的基类）

    except Exception as e:
        # 使用 logger.error 把错误信息记录到日志文件中

        logger.error(f"更新配置失败: {e}")

        raise HTTPException(status_code=500, detail=str(e))
