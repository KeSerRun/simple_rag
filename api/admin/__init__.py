"""管理后台 API:仪表盘 / 配置 / 用户管理 / 日志 / 数据库"""


import glob
import json
import os
import time
import uuid as _uuid
from datetime import datetime
from pathlib import Path


from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse


from base.config import conf
from base.logger import logger

from ..deps import admin_required, auth_required, system

router = APIRouter(prefix="/api/admin", tags=["admin"])

SYSTEM_PARTITION = "__system__"

request_stats = None

_upload_tasks: dict[str, dict] = {}



def _mask_secret(value: str, keep_front: int = 4) -> str:
    """脱敏: 保留前 keep_front 字符, 其余替换为 *。

    Args:
        value: 原始字符串(如 API Key)。
        keep_front: 保留前 N 个明文字符,默认 4。

    Returns:
        str: 脱敏后的字符串。
    """
    if not value or len(value) <= keep_front + 4:
        return value[:keep_front] + "***" if value else ""
    return value[:keep_front] + "*" * (len(value) - keep_front)


def _get_config_dict(masked: bool = True) -> dict:
    """将 Config 实例转为可序列化的字典, 可选脱敏 secret 字段。

    # ── 脱敏字段

    openai_api_key, embedding_api_key, mineru_api_key, jwt_secret_key,
    superuser_usernames, superuser_passwords, bocha_api_key, bing_api_key。

    Args:
        masked: 是否对 secret 字段脱敏,默认 True。

    Returns:
        dict: 配置键值对(仅含 str/int/float/bool/list 类型)。
    """
    d = {}
    for key in dir(conf):
        if key.startswith("_"):
            continue
        val = getattr(conf, key)
        if callable(val):
            continue
        if isinstance(val, (str, int, float, bool, list)):
            d[key] = val
    if masked:
        for secret_key in ("openai_api_key", "embedding_api_key", "mineru_api_key",
                           "jwt_secret_key", "superuser_usernames", "superuser_passwords",
                           "bocha_api_key", "bing_api_key"):
            if secret_key in d:
                if isinstance(d[secret_key], str):
                    d[secret_key] = _mask_secret(d[secret_key])
                elif isinstance(d[secret_key], list):
                    d[secret_key] = [f"{_mask_secret(s)}" for s in d[secret_key]]
    return d


def _write_config_ini(updates: dict) -> bool:
    """将部分更新写入 config.ini 文件(行级替换, 保留注释)。

    # ── 工作方式

    1. 逐行扫描,找到对应 section 下的 option,替换等号后的值
    2. 同时更新内存中的 ``conf`` 属性
    3. 特殊处理: stop_words 字符串→列表, consolidation_ratio 百分数→小数

    Args:
        updates: 配置更新字典,key 为属性名,value 为新值。

    Returns:
        bool: 是否有变更被写入。

    Note:
        config.ini 路径来自 ``conf._config_file``,回退到项目根目录下的 config.ini。
    """
    config_path = getattr(conf, '_config_file',
                          os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.ini'))

    with open(config_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    mapping = {
        "data_dir": ("storage", "data_dir"),
        "vector_store_dir": ("storage", "vector_store_dir"),
        "retrieval_top_k": ("retrieval", "retrieval_top_k"),
        "candidate_top_k": ("retrieval", "candidate_top_k"),
        "min_chunk_length": ("retrieval", "min_chunk_length"),
        "stop_words": ("retrieval", "stop_words"),
        "openai_api_key": ("api", "chat_api_key"),
        "openai_base_url": ("api", "chat_base_url"),
        "chat_model": ("api", "chat_model"),
        "chat_reasoning_effort": ("api", "chat_reasoning_effort"),
        "embedding_api_key": ("api", "embedding_api_key"),
        "embedding_base_url": ("api", "embedding_base_url"),
        "openai_embedding_model": ("api", "embedding_model"),
        "openai_embedding_dim": ("api", "embedding_dim"),
        "openai_timeout": ("api", "timeout"),
        "openai_max_retries": ("api", "max_retries"),
        "mineru_base_url": ("api", "mineru_base_url"),
        "mineru_api_key": ("api", "mineru_api_key"),
        "mineru_token_name": ("api", "mineru_token_name"),
        "mineru_model_version": ("api", "mineru_model_version"),
        "mineru_language": ("api", "mineru_language"),
        "mineru_max_concurrency": ("api", "mineru_max_concurrency"),
        "max_tool_iter": ("agent", "max_tool_iter"),
        "max_output_chars": ("agent", "max_output_chars"),
        "eval_max_workers": ("agent", "eval_max_workers"),
        "search_backend": ("search", "backend"),
        "searxng_url": ("search", "searxng_url"),
        "bocha_api_key": ("search", "bocha_api_key"),
        "bing_api_key": ("search", "bing_api_key"),
        "search_timeout": ("search", "timeout"),
        "max_history_length": ("conversation_history", "max_history_length"),
        "context_window_chars": ("conversation_history", "context_window_chars"),
        "consolidation_ratio": ("conversation_history", "consolidation_ratio"),
        "log_path": ("logger", "log_path"),
        "app_log_level": ("logger", "app_log_level"),
        "http_log_level": ("logger", "http_log_level"),
        "console_log_level": ("logger", "console_log_level"),
        "max_user_storage_mb": ("upload", "max_user_storage_mb"),
    }

    changed = False
    for key, val in updates.items():
        if key not in mapping:
            continue
        section, option = mapping[key]

        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                sec_name = stripped[1:-1].strip()
                in_section = (sec_name == section)
                continue
            if in_section and stripped.startswith(option + ' ') or stripped.startswith(option + '='):
                eq_pos = stripped.find('=')
                if eq_pos >= 0:
                    prefix = stripped[:eq_pos + 1]
                    indent = line[:len(line) - len(line.lstrip())]
                    lines[i] = f"{indent}{option} = {val}\n"
                    changed = True
                break

        if hasattr(conf, key):
            if key == 'stop_words' and isinstance(val, str):
                setattr(conf, key, [w.strip() for w in val.split(',') if w.strip()])
            elif key == 'consolidation_ratio' and isinstance(val, (int, float)) and val > 1:
                setattr(conf, key, val / 100.0)
            else:
                setattr(conf, key, val)

    if not changed:
        return False

    with open(config_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    logger.info(f"配置已更新: {config_path}")
    conf._update_config_hash()
    return True


from . import config, dashboard, database, logs, users, eval
