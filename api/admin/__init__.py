# ===== 管理后台 API 入口模块 =====
# 这个文件是管理后台所有 API 路由的入口，负责注册仪表盘、配置、用户管理、日志、数据库管理等功能的路由
"""管理后台 API:仪表盘 / 配置 / 用户管理 / 日志 / 数据库"""

# ===== 导入 Python 标准库模块 =====

# 导入 glob 模块，用于文件路径模式匹配（例如查找所有 .txt 文件）
import glob
# 导入 json 模块，用于处理 JSON 数据的序列化和反序列化
import json
# 导入 os 模块，提供与操作系统交互的功能（文件路径、环境变量等）
import os
# 导入 time 模块，提供时间相关的函数（如时间戳、休眠等）
import time
# 导入 uuid 模块并重命名为 _uuid，用于生成唯一标识符（避免与变量名冲突）
import uuid as _uuid
# 从 datetime 模块中导入 datetime 类，用于处理日期和时间
from datetime import datetime
# 从 pathlib 模块中导入 Path 类，用于以面向对象的方式操作文件路径
from pathlib import Path

# ===== 导入第三方框架模块 =====

# 从 fastapi 中导入 APIRouter（创建路由分组）、File（文件上传参数）、HTTPException（HTTP 错误异常）、Query（查询参数）、Request（请求对象）、UploadFile（上传文件对象）
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
# 从 fastapi.responses 中导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应
from fastapi.responses import JSONResponse

# ===== 导入项目内部模块 =====

# 从 base.config 模块中导入 conf，这是项目的全局配置实例，包含所有配置项
from base.config import conf
# 从 base.logger 模块中导入 logger，这是项目的全局日志记录器实例
from base.logger import logger

# 从上级目录的 deps 模块（依赖模块）中导入 admin_required（管理员权限校验依赖）、auth_required（登录认证依赖）、system（系统服务依赖）
from ..deps import admin_required, auth_required, system

# ===== 创建 API 路由对象 =====
# 创建一个 APIRouter 实例，所有管理后台接口的前缀都是 /api/admin，在 API 文档中分组名为 "admin"
router = APIRouter(prefix="/api/admin", tags=["admin"])

# ===== 定义系统级常量 =====
# 系统级数据分区名，标记那些对所有用户都可见的公共数据（不是某个用户的私有数据）
# 所有用户都可以访问这个分区下的数据
SYSTEM_PARTITION = "__system__"

# ===== 全局变量（由外部注入） =====
# 请求统计引用变量，初始为 None，会在 app.py（应用入口）初始化时被注入实际的统计对象
# 用于记录和统计所有 API 请求的访问情况
request_stats = None

# ===== 系统数据上传任务状态追踪 =====
# 定义一个字典，用于追踪系统数据上传任务的状态
# 键是 task_id（任务ID），值是一个字典，包含文件名列表、状态（processing/finished）、总数、成功数、失败数
_upload_tasks: dict[str, dict] = {}  # {task_id: {"filenames": [...], "status": "processing"|"finished", "total": N, "success": N, "fail": N}}


# ===== 工具函数 =====
# 这里定义了一些辅助函数，供本模块内部使用

def _mask_secret(value: str, keep_front: int = 4) -> str:
    """脱敏: 保留前 keep_front 字符, 其余替换为 *"""
    # 如果 value 为空字符串，或者 value 的长度不超过 keep_front + 4，说明字符串太短
    if not value or len(value) <= keep_front + 4:
        # 对于短字符串，保留前 keep_front 位，后面加 *** 来脱敏
        return value[:keep_front] + "***" if value else ""
    # 对于长字符串，保留前 keep_front 位，后面的每个字符都替换为 *
    return value[:keep_front] + "*" * (len(value) - keep_front)


def _get_config_dict(masked: bool = True) -> dict:
    """将 Config 实例转为可序列化的字典, 可选脱敏 secret 字段。"""
    # 创建一个空字典，用来存放配置项
    d = {}
    # 遍历 conf 对象的所有属性名（包括方法、内置属性等）
    for key in dir(conf):
        # 跳过以下划线开头的私有属性和内置属性（如 __class__、__dict__ 等）
        if key.startswith("_"):
            continue
        # 获取当前 key 对应的属性值
        val = getattr(conf, key)
        # 如果这个属性是可调用的（比如方法、函数），跳过它，我们只保留数据
        if callable(val):
            continue
        # 只保留基本类型：字符串、整数、浮点数、布尔值、列表，排除复杂对象
        if isinstance(val, (str, int, float, bool, list)):
            # 将符合条件的配置项存入字典，key 是属性名，val 是属性值
            d[key] = val
    # 如果需要脱敏（masked=True），则对敏感字段进行处理
    if masked:
        # 遍历所有需要脱敏的敏感字段名称列表
        for secret_key in ("openai_api_key", "embedding_api_key", "mineru_api_key",
                           "jwt_secret_key", "superuser_usernames", "superuser_passwords",
                           "bocha_api_key", "bing_api_key"):
            # 如果这个敏感字段存在于字典中
            if secret_key in d:
                # 如果是字符串类型，用 _mask_secret 函数进行脱敏处理
                if isinstance(d[secret_key], str):
                    d[secret_key] = _mask_secret(d[secret_key])
                # 如果是列表类型（如 superuser_usernames），对列表中的每个元素分别脱敏
                elif isinstance(d[secret_key], list):
                    d[secret_key] = [f"{_mask_secret(s)}" for s in d[secret_key]]
    # 返回处理后的配置字典
    return d


def _write_config_ini(updates: dict) -> bool:
    """将部分更新写入 config.ini 文件（行级替换，保留注释）。"""
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

        # 找到 section 并替换 option 所在行（行级替换保留注释）
        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                sec_name = stripped[1:-1].strip()
                in_section = (sec_name == section)
                continue
            if in_section and stripped.startswith(option + ' ') or stripped.startswith(option + '='):
                # 替换值部分，保留等号后的空格/注释（如果有）
                eq_pos = stripped.find('=')
                if eq_pos >= 0:
                    prefix = stripped[:eq_pos + 1]
                    indent = line[:len(line) - len(line.lstrip())]
                    lines[i] = f"{indent}{option} = {val}\n"
                    changed = True
                break

        # 同步内存中的 conf 实例
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


# ===== 导入子模块（注册子路由） =====
# 从当前包（admin）中导入各个子模块，这些子模块中定义了具体的 API 路由
# 导入时会执行子模块中的代码，从而将子路由注册到 router 上
from . import config, dashboard, database, logs, users, eval
