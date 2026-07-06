"""管理后台 API:仪表盘 / 配置 / 用户管理 / 日志 / 数据库"""

import glob
import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from base.config import conf
from base.logger import logger

from .deps import admin_required, auth_required, system

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 系统级数据分区名（对所有用户可见）
SYSTEM_PARTITION = "__system__"

# 请求统计引用（由 app.py 在初始化时注入）
request_stats = None

# 系统数据上传任务状态追踪
_upload_tasks: dict[str, dict] = {}  # {task_id: {"filenames": [...], "status": "processing"|"finished", "total": N, "success": N, "fail": N}}
import uuid as _uuid


# ─── 工具函数 ──────────────────────────────────────────────────

def _mask_secret(value: str, keep_front: int = 4) -> str:
    """脱敏: 保留前 keep_front 字符, 其余替换为 *"""
    if not value or len(value) <= keep_front + 4:
        return value[:keep_front] + "***" if value else ""
    return value[:keep_front] + "*" * (len(value) - keep_front)


def _get_config_dict(masked: bool = True) -> dict:
    """将 Config 实例转为可序列化的字典, 可选脱敏 secret 字段。"""
    d = {}
    for key in dir(conf):
        if key.startswith("_"):
            continue
        val = getattr(conf, key)
        if callable(val):
            continue
        # 只保留基本类型
        if isinstance(val, (str, int, float, bool, list)):
            d[key] = val
    # 对敏感字段脱敏
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
    """将部分更新写入 config.ini 文件。仅支持更新已有 key。"""
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(conf._config_file if hasattr(conf, '_config_file') else 'config.ini', encoding='utf-8')

    # 将 updates 平铺键映射到 configparser section/key
    # conf 属性名 → (section, key) 映射
    mapping = {
        # storage
        "data_dir": ("storage", "data_dir"),
        "vector_store_dir": ("storage", "vector_store_dir"),
        # retrieval
        "parent_chunk_size": ("retrieval", "parent_chunk_size"),
        "child_chunk_size": ("retrieval", "child_chunk_size"),
        "chunk_overlap": ("retrieval", "chunk_overlap"),
        "retrieval_top_k": ("retrieval", "retrieval_top_k"),
        "candidate_top_k": ("retrieval", "candidate_top_k"),
        "enable_llm_rerank": ("retrieval", "enable_llm_rerank"),
        # api
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
        # agent
        "max_tool_iter": ("agent", "max_tool_iter"),
        "max_calls_per_tool": ("agent", "max_calls_per_tool"),
        "max_output_tokens": ("agent", "max_output_tokens"),
        "reflection_mode": ("agent", "reflection_mode"),
        # search
        "search_backend": ("search", "backend"),
        "searxng_url": ("search", "searxng_url"),
        "bocha_api_key": ("search", "bocha_api_key"),
        "bing_api_key": ("search", "bing_api_key"),
        "search_timeout": ("search", "timeout"),
        # conversation_history
        "max_history_length": ("conversation_history", "max_history_length"),
        "max_history_chars": ("conversation_history", "max_history_chars"),
        # logger
        "log_path": ("logger", "log_path"),
        "app_log_level": ("logger", "app_log_level"),
        "http_log_level": ("logger", "http_log_level"),
        "user_log_level": ("logger", "user_log_level"),
        "console_log_level": ("logger", "console_log_level"),
        # upload
        "max_user_storage_mb": ("upload", "max_user_storage_mb"),
    }

    changed = False
    for key, val in updates.items():
        if key not in mapping:
            continue
        section, option = mapping[key]
        if not cfg.has_section(section):
            cfg.add_section(section)
        # 将 Python 类型转换为字符串
        cfg.set(section, option, str(val))
        changed = True
        # 同步更新当前内存中的 conf 实例
        if hasattr(conf, key):
            setattr(conf, key, val)

    if not changed:
        return False

    config_path = getattr(conf, '_config_file',
                          os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.ini'))
    with open(config_path, 'w', encoding='utf-8') as f:
        cfg.write(f, space_around_delimiters=True)
    logger.info(f"配置已更新: {config_path}")
    return True


# ─── 仪表盘 ─────────────────────────────────────────────────────

@router.get("/dashboard")
@auth_required
@admin_required
async def get_dashboard(request: Request):
    """系统总览: 健康状态 / 用户数 / 会话数 / 文档数 / 切块数 / 请求统计"""
    try:
        # 用户与会话统计
        users = system.data_store._read_json(system.data_store._users_file)
        sessions = system.data_store._read_json(system.data_store._sessions_file)
        user_count = len(users)
        session_count = len(sessions)
        admin_count = sum(1 for u in users if u.get("role") == "admin")

        # 向量库统计
        vs = system.vector_store
        total_chunks = len(vs.metadata) if vs and vs.metadata else 0
        total_docs = 0
        if total_chunks > 0:
            sources = set(m.get("source", "") for m in vs.metadata if m.get("source"))
            total_docs = len(sources)

        # 分区统计
        partitions = {}
        if total_chunks > 0:
            for m in vs.metadata:
                p = m.get("partition", "default")
                partitions.setdefault(p, {"chunks": 0, "sources": set()})
                partitions[p]["chunks"] += 1
                if m.get("source"):
                    partitions[p]["sources"].add(m["source"])
        partitions_summary = {
            p: {"chunks": v["chunks"], "sources": len(v["sources"])}
            for p, v in partitions.items()
        }

        # 请求统计（由 app.py 注入到 api.admin.request_stats）
        if request_stats:
            rs = request_stats
            stats = {
                "total_requests": rs.total_requests,
                "total_errors": rs.total_errors,
                "by_method": dict(rs.by_method),
                "start_time": rs.start_time,
                "uptime_seconds": int(time.time() - rs.start_time),
            }
        else:
            stats = {
                "total_requests": 0, "total_errors": 0,
                "by_method": {}, "by_path": [],
                "start_time": time.time(), "uptime_seconds": 0,
            }

        return JSONResponse(content={
            "healthy": True,
            "user_count": user_count,
            "admin_count": admin_count,
            "session_count": session_count,
            "document_count": total_docs,
            "chunk_count": total_chunks,
            "partitions": partitions_summary,
            "request_stats": stats,
            "embedding_dim": vs.dimension if vs else None,
            "embedding_model": vs.embedding_model if vs else None,
        })
    except Exception as e:
        logger.error(f"获取仪表盘数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── 配置管理 ───────────────────────────────────────────────────

@router.get("/config")
@auth_required
@admin_required
async def get_config(request: Request):
    """获取当前配置（敏感字段脱敏）"""
    return JSONResponse(content=_get_config_dict(masked=True))


@router.put("/config")
@auth_required
@admin_required
async def update_config(request: Request):
    """更新配置并写回 config.ini"""
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


# ─── 用户管理 ───────────────────────────────────────────────────

@router.get("/users")
@auth_required
@admin_required
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出所有用户（分页）"""
    try:
        users = system.data_store._read_json(system.data_store._users_file)
        total = len(users)
        start = (page - 1) * page_size
        end = start + page_size
        items = users[start:end]
        # 脱敏密码
        for u in items:
            u.pop("password", None)
            u.pop("id", None)
        return JSONResponse(content={
            "total": total,
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
    """创建用户（可指定角色）"""
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
    """删除用户（禁止删除自身）"""
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
    """变更用户角色"""
    try:
        data = await request.json()
        new_role = data.get("role", "").strip()
        if new_role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="角色必须为 user 或 admin")
        users = system.data_store._read_json(system.data_store._users_file)
        for u in users:
            if u["username"] == username:
                old_role = u.get("role", "user")
                u["role"] = new_role
                system.data_store._write_json(system.data_store._users_file, users)
                logger.info(f"用户角色变更: {username}: {old_role} -> {new_role}")
                return JSONResponse(content={
                    "message": f"用户 '{username}' 角色已更新为 {new_role}",
                    "user": {"username": username, "role": new_role},
                })
        raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"变更用户角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{username}/password")
@auth_required
@admin_required
async def reset_password(request: Request, username: str):
    """重置用户密码"""
    try:
        data = await request.json()
        new_password = data.get("password", "").strip()
        if not new_password or len(new_password) < 6:
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        users = system.data_store._read_json(system.data_store._users_file)
        for u in users:
            if u["username"] == username:
                u["password"] = new_password
                system.data_store._write_json(system.data_store._users_file, users)
                logger.info(f"管理员重置用户密码: {username}")
                return JSONResponse(content={
                    "message": f"用户 '{username}' 密码已重置",
                })
        raise HTTPException(status_code=404, detail=f"用户 '{username}' 不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置密码失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── 日志查看 ───────────────────────────────────────────────────

@router.get("/logs")
@auth_required
@admin_required
async def list_logs(request: Request):
    """列出 log 目录下所有日志文件"""
    try:
        log_dir = conf.log_path
        if not os.path.isdir(log_dir):
            return JSONResponse(content={"files": [], "log_path": log_dir})
        files = []
        for fname in os.listdir(log_dir):
            fpath = os.path.join(log_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
        return JSONResponse(content={"files": files, "log_path": log_dir})
    except Exception as e:
        logger.error(f"获取日志列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{log_file:path}/download")
@auth_required
@admin_required
async def download_log(request: Request, log_file: str):
    """下载完整的日志文件"""
    try:
        log_dir = conf.log_path
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")

        from fastapi.responses import FileResponse

        filename = os.path.basename(safe_path)
        return FileResponse(
            safe_path,
            media_type="text/plain",
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{log_file:path}")
@auth_required
@admin_required
async def read_log(
    request: Request,
    log_file: str,
    lines: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """读取日志文件内容

    - lines:   返回行数(默认 200, 最大 5000)
    - offset:  跳过行数(默认 0)
    - 支持 ?reverse=1 从尾部读取
    """
    try:
        log_dir = conf.log_path
        # 安全校验: 防止路径穿越
        safe_path = os.path.normpath(os.path.join(log_dir, log_file))
        if not safe_path.startswith(os.path.normpath(log_dir)):
            raise HTTPException(status_code=403, detail="禁止访问该路径")
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="日志文件不存在")
        if safe_path.endswith(".npy"):
            raise HTTPException(status_code=403, detail="禁止读取二进制文件")

        reverse = request.query_params.get("reverse", "0") == "1"

        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total = len(all_lines)
        if reverse:
            start = max(0, total - offset - lines)
            end = total - offset
            if end <= 0:
                return JSONResponse(content={"lines": [], "total": total, "file": log_file})
            chunk = all_lines[start:end]
        else:
            start = offset
            end = offset + lines
            chunk = all_lines[start:end]

        # 去除换行符
        content = [line.rstrip("\n\r") for line in chunk]

        return JSONResponse(content={
            "file": log_file,
            "total": total,
            "start": start,
            "end": min(end, total),
            "lines": content,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── 数据库（向量存储）统计 ─────────────────────────────────────

@router.get("/database")
@auth_required
@admin_required
async def get_database_stats(request: Request):
    """向量库统计: 总切块数、按分区/来源分布、嵌入维度"""
    try:
        vs = system.vector_store
        if not vs:
            return JSONResponse(content={
                "available": False,
                "message": "向量存储未初始化",
            })

        metadata = vs.metadata or []
        dense_vectors = vs.dense_vectors or []

        # 总体统计
        total_chunks = len(metadata)
        total_vectors = len(dense_vectors)

        # 按分区统计
        by_partition = {}
        for m in metadata:
            p = m.get("partition", "default")
            by_partition.setdefault(p, {"chunks": 0, "sources": set()})
            by_partition[p]["chunks"] += 1
            if m.get("source"):
                by_partition[p]["sources"].add(m["source"])
        by_partition_summary = {
            p: {"chunks": v["chunks"], "sources": sorted(v["sources"])}
            for p, v in by_partition.items()
        }

        # 按来源统计
        by_source = {}
        for m in metadata:
            s = m.get("source", "unknown")
            by_source.setdefault(s, {"chunks": 0, "partitions": set()})
            by_source[s]["chunks"] += 1
            if m.get("partition"):
                by_source[s]["partitions"].add(m["partition"])

        # 将 set 转为 list 以支持 JSON 序列化
        for v in by_source.values():
            v["partitions"] = sorted(v["partitions"])
        for v in by_partition.values():
            if isinstance(v.get("sources"), set):
                v["sources"] = sorted(v["sources"])

        return JSONResponse(content={
            "available": True,
            "embedding_model": vs.embedding_model if vs else None,
            "embedding_dimension": vs.dimension if vs else None,
            "total_chunks": total_chunks,
            "total_vectors": total_vectors,
            "partitions_count": len(by_partition),
            "sources_count": len(by_source),
            "chunk_types": sorted({m.get("chunk_type", "") for m in metadata if m.get("chunk_type")}),
            "by_partition": by_partition_summary,
            "by_source": by_source,
        })
    except Exception as e:
        logger.error(f"获取数据库统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database/chunks")
@auth_required
@admin_required
async def get_chunks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    partition: str = Query(None),
    source: str = Query(None),
    chunk_type: str = Query(None),
    parent_id: str = Query(None),
    query_text: str = Query(None),
):
    """切块详情列表（分页, 可过滤 partition/source/chunk_type/parent_id）"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={"total": 0, "items": [], "page": page, "page_size": page_size})

        metadata = vs.metadata

        # 过滤
        filtered = metadata
        if partition:
            filtered = [m for m in filtered if m.get("partition") == partition]
        if source:
            filtered = [m for m in filtered if m.get("source") == source]
        if chunk_type:
            filtered = [m for m in filtered if m.get("chunk_type") == chunk_type]
        if parent_id:
            filtered = [m for m in filtered if m.get("parent_id") == parent_id]
        if query_text:
            q = query_text.lower()
            filtered = [m for m in filtered if q in (m.get("text") or "").lower()]

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]

        # 简化返回数据
        simplified = []
        for m in items:
            text = (m.get("text") or "")[:200]
            simplified.append({
                "id": m.get("id", ""),
                "parent_id": m.get("parent_id", ""),
                "text": text,
                "source": m.get("source", ""),
                "partition": m.get("partition", ""),
                "chunk_type": m.get("chunk_type", ""),
                "page": m.get("page"),
                "parent_chunk_size": len(m.get("parent_text", "")),
            })

        return JSONResponse(content={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": simplified,
        })
    except Exception as e:
        logger.error(f"获取切块详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database/partitions")
@auth_required
@admin_required
async def get_partitions(request: Request):
    """列出所有分区及每个分区的文档/切块数"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={"partitions": []})

        partitions = {}
        for m in vs.metadata:
            p = m.get("partition", "default")
            partitions.setdefault(p, {"partition": p, "chunks": 0, "sources": set()})
            partitions[p]["chunks"] += 1
            if m.get("source"):
                partitions[p]["sources"].add(m["source"])

        result = [
            {"partition": k, "chunks": v["chunks"], "sources": sorted(v["sources"])}
            for k, v in partitions.items()
        ]
        result.sort(key=lambda x: -x["chunks"])

        return JSONResponse(content={"partitions": result})
    except Exception as e:
        logger.error(f"获取分区列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database/check_integrity")
@auth_required
@admin_required
async def check_integrity(request: Request):
    """检查文档完整性：验证元数据中的文件/图片是否真实存在于磁盘。"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={
                "available": False,
                "message": "向量存储未初始化或无数据",
            })

        metadata = vs.metadata
        uploads_base = Path(conf.vector_store_dir) / "uploads"

        # 按 (partition, source) 分组统计
        docs: dict[tuple[str, str], dict] = {}
        for m in metadata:
            key = (m.get("partition", "") or "", m.get("source", "") or "")
            if not key[1]:  # 跳过无 source 的条目
                continue
            if key not in docs:
                docs[key] = {"chunks": 0, "images": 0, "image_records": [], "text_chunks": 0}
            docs[key]["chunks"] += 1
            ct = (m.get("chunk_type") or "").strip()
            ip = (m.get("img_path") or "").strip()
            if ct in ("image", "chart") and ip:
                docs[key]["images"] += 1
                docs[key]["image_records"].append(ip)
            else:
                docs[key]["text_chunks"] += 1

        total_images = 0
        healthy_images = 0
        missing_images = 0
        issues = []
        healthy_docs = 0

        for (partition, source), info in docs.items():
            stem = Path(source).stem
            doc_issues = []

            # ① 原文件是否存在
            source_file = uploads_base / partition / source
            source_exists = source_file.exists()
            if not source_exists:
                doc_issues.append(f"原文件缺失")

            # ② chunk_out 目录是否存在
            chunk_dir = uploads_base / partition / "chunk_out" / stem
            chunk_exists = chunk_dir.is_dir()
            if not chunk_exists:
                # 尝试用 glob 模糊匹配（目录名可能多了 _ 等后缀）
                fuzzy_dirs = sorted(glob.glob(str(uploads_base / partition / "chunk_out" / f"{stem}*")))
                if fuzzy_dirs:
                    chunk_dir = Path(fuzzy_dirs[0])
                    chunk_exists = True
                    doc_issues.append(f"chunk_out 目录名不精确 (实际: {chunk_dir.name})")
                else:
                    doc_issues.append(f"chunk_out 目录缺失")

            # ③ 图片文件完整性
            img_missing_count = 0
            img_hash_mismatch = 0
            for img_path in info["image_records"]:
                total_images += 1
                if not chunk_exists:
                    missing_images += 1
                    continue

                expected = chunk_dir / img_path
                # 精确匹配
                candidates = glob.glob(str(expected))
                # 前缀匹配
                if not candidates:
                    candidates = sorted(glob.glob(str(expected) + "*"))
                if candidates:
                    healthy_images += 1
                    # 检查文件名是否完全匹配
                    if Path(candidates[0]).name != Path(img_path).name:
                        img_hash_mismatch += 1
                else:
                    # 彻底不存在
                    missing_images += 1
                    img_missing_count += 1

            # 严重级别
            severity = "healthy"
            if doc_issues:
                has_critical = any("缺失" in i and "不精确" not in i for i in doc_issues)
                severity = "critical" if has_critical else "warning"

            if doc_issues:
                issues.append({
                    "source": source,
                    "partition": partition,
                    "chunks": info["chunks"],
                    "text_chunks": info["text_chunks"],
                    "image_count": info["images"],
                    "severity": severity,
                    "source_exists": source_exists,
                    "chunk_exists": chunk_exists,
                    "img_missing_count": img_missing_count,
                    "img_hash_mismatch": img_hash_mismatch,
                    "issues": doc_issues,
                })
            else:
                healthy_docs += 1

        return JSONResponse(content={
            "available": True,
            "total_documents": len(docs),
            "healthy": healthy_docs,
            "problematic": len(issues),
            "total_chunks": len(metadata),
            "total_images": total_images,
            "healthy_images": healthy_images,
            "missing_images": missing_images,
            "issues": issues,
        })
    except Exception as e:
        logger.error(f"完整性检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── 系统数据上传 ─────────────────────────────────────────────

@router.get("/database/system_docs")
@auth_required
@admin_required
async def list_system_docs(request: Request):
    """列出所有系统级文档"""
    try:
        docs = system.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        # 获取每个文档的 chunk 数
        doc_chunks = {}
        if system.vector_store.metadata:
            for m in system.vector_store.metadata:
                src = m.get("source", "")
                if m.get("partition") == SYSTEM_PARTITION and src:
                    doc_chunks[src] = doc_chunks.get(src, 0) + 1
        items = []
        for d in sorted(docs):
            items.append({"name": d, "chunks": doc_chunks.get(d, 0)})
        return JSONResponse(content={"documents": items})
    except Exception as e:
        logger.error(f"获取系统文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/database/upload")
@auth_required
@admin_required
async def upload_system_data(request: Request, files: list[UploadFile] = File(...)):
    """上传系统级数据文档（后台处理，不阻塞）"""
    from rag.core.document_process import process_documents_from_dir

    if not files:
        raise HTTPException(status_code=400, detail="未提供文件")

    import threading as _threading
    task_id = "upload_" + _uuid.uuid4().hex[:8]
    total = len(files)
    tasks = []

    for file in files:
        content = await file.read()
        if not content:
            continue
        # 丢弃目录层级，只保留基础文件名
        filename = os.path.basename(file.filename)
        save_dir = f"{conf.vector_store_dir}/uploads/{SYSTEM_PARTITION}"
        save_path = os.path.normpath(os.path.join(save_dir, filename))
        if not save_path.startswith(os.path.normpath(save_dir)):
            logger.warning(f"非法文件路径: {filename}")
            continue

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(content)

        tasks.append((filename, save_path))

    # 注册任务
    _upload_tasks[task_id] = {
        "filenames": [t[0] for t in tasks],
        "status": "processing",
        "total": len(tasks),
        "success": 0,
        "fail": 0,
    }

    # 后台逐文件向量化
    def _worker():
        task = _upload_tasks[task_id]
        for fname, fpath in tasks:
            try:
                system.vector_store.delete_documents_by_sources([fname], partition=SYSTEM_PARTITION)
                system.vector_store.store_documents_from_dir(fpath, partition=SYSTEM_PARTITION)
                task["success"] += 1
                logger.info(f"系统数据上传成功: {fname}")
            except Exception as e:
                task["fail"] += 1
                logger.error(f"系统数据上传失败 ({fname}): {e}")
        task["status"] = "finished"

    _threading.Thread(target=_worker, daemon=True).start()

    return JSONResponse(content={
        "task_id": task_id,
        "message": f"已接收 {total} 个文件，后台向量化处理中",
        "files": tasks,
    })


@router.get("/database/upload/status")
@auth_required
@admin_required
async def get_upload_status(request: Request):
    """查询最近的上传任务状态"""
    # 返回最近一个未完成的或刚完成的任务
    active = {k: v for k, v in _upload_tasks.items() if v["status"] == "processing"}
    if active:
        tid, task = list(active.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "processing", "task": task})
    # 找最近完成的
    finished = {k: v for k, v in _upload_tasks.items() if v["status"] == "finished"}
    if finished:
        tid, task = list(finished.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "finished", "task": task})
    return JSONResponse(content={"status": "idle"})


@router.delete("/database/delete")
@auth_required
@admin_required
async def delete_document(request: Request, source: str = Query(...), partition: str = Query(...)):
    """删除指定分区中的指定文档（系统数据或用户数据）"""
    try:
        if not source or not partition:
            raise HTTPException(status_code=400, detail="缺少参数 source 或 partition")

        # 从向量库删除
        system.vector_store.delete_documents_by_sources([source], partition=partition)

        # 清理源文件和缓存
        upload_dir = f"{conf.vector_store_dir}/uploads/{partition}"
        from pathlib import Path
        file_path = os.path.join(upload_dir, source)
        if os.path.isfile(file_path):
            os.remove(file_path)
        # 清理 MinerU 产物
        chunk_out = os.path.join(upload_dir, "chunk_out", Path(source).stem)
        if os.path.isdir(chunk_out):
            import shutil
            shutil.rmtree(chunk_out)

        logger.info(f"管理员删除文档: source={source}, partition={partition}")
        return JSONResponse(content={"message": f"文档 '{source}' 已从 {partition} 删除"})
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
