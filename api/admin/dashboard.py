"""管理后台 API - 仪表盘"""

import time

from . import router, request_stats
from ..deps import auth_required, admin_required, system
from base.logger import logger
from agent.tools import registry as tool_registry
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


@router.get("/dashboard")

@auth_required
@admin_required

async def get_dashboard(request: Request):
    """系统总览: 健康状态 / 用户数 / 会话数 / 文档数 / 切块数 / 请求统计。

    # ── 统计项

    - user_count / admin_count: 用户及管理员数量
    - document_count / chunk_count: 文档及切块数量(按 source 去重)
    - partitions: 各分区切块和来源统计
    - request_stats: HTTP 请求统计(总量/错误/方法分布/运行时长)
    - tool_call_counts: 工具调用计数
    - embedding_model / embedding_dim: 向量嵌入模型信息

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 包含上述统计数据的字典。

    Raises:
        HTTPException 500: 获取数据失败。
    """
    try:


        users_data = system.data_store.get_all_users(page=1, page_size=999999)


        users_list = users_data.get("items", [])


        user_count = users_data.get("total", 0)

        session_count = 0

        admin_count = sum(1 for u in users_list if u.get("role") == "admin")


        vs = system.vector_store

        total_chunks = len(vs.metadata) if vs and vs.metadata else 0


        total_docs = 0

        if total_chunks > 0:

            sources = set(m.get("source", "") for m in vs.metadata if m.get("source"))


            total_docs = len(sources)

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

            "tool_call_counts": dict(tool_registry.call_counts),



            "embedding_dim": vs.dimension if vs else None,

            "embedding_model": vs.embedding_model if vs else None,

        })

    except Exception as e:


        logger.error(f"获取仪表盘数据失败: {e}")

        raise HTTPException(status_code=500, detail=str(e))
