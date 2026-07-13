"""管理后台 API - 仪表盘"""

from . import router, request_stats
from ..deps import auth_required, admin_required, system
from base.logger import logger
from agent.tools import registry as tool_registry
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time

@router.get("/dashboard")

@auth_required
@admin_required

async def get_dashboard(request: Request):


    """系统总览: 健康状态 / 用户数 / 会话数 / 文档数 / 切块数 / 请求统计"""
    # 包括：系统是否健康、用户数量、会话数量、文档数量、文本切块数量、请求统计

    try:


        users_data = system.data_store.get_all_users(page=1, page_size=999999)


        users_list = users_data.get("items", [])


        user_count = users_data.get("total", 0)

        session_count = 0

        admin_count = sum(1 for u in users_list if u.get("role") == "admin")


        vs = system.vector_store
        # VS = VectorStore 的缩写

        total_chunks = len(vs.metadata) if vs and vs.metadata else 0
        # 计算向量库中的总切块数（chunks）
        # 文档被切成小段（chunk），每段会被向量化存入向量库


        total_docs = 0

        if total_chunks > 0:

            sources = set(m.get("source", "") for m in vs.metadata if m.get("source"))


            total_docs = len(sources)

        partitions = {}
        # 初始化空字典，用来存储每个分区的统计信息
        # 分区（partition）是向量库中的一种分类方式
        # 不同来源的文档可以分到不同分区，方便隔离和查询

        if total_chunks > 0:

            for m in vs.metadata:

                p = m.get("partition", "default")

                partitions.setdefault(p, {"chunks": 0, "sources": set()})

                #   chunks  - 切块数量（整数）
                #   sources - 来源文档集合（set，自动去重）

                partitions[p]["chunks"] += 1
                # 遍历一遍所有切块，每个切块都给自己所属的分区贡献 1 个计数

                if m.get("source"):
                    # 就把它加入分区的 sources 集合

                    partitions[p]["sources"].add(m["source"])
                    # 使用 set.add() 添加来源，自动去重

        partitions_summary = {
            # 因为 partitions 中的 sources 是 set 类型，JSON 不支持 set
            # 所以需要把 set 转换成整数（数量）

            p: {"chunks": v["chunks"], "sources": len(v["sources"])}
            # 遍历每个分区，把 sources 集合的长度（文档数量）取出来

            for p, v in partitions.items()
            # 遍历 partitions 字典的键值对
            # p 是分区名，v 是 {"chunks": ..., "sources": set(...)}
        }


        if request_stats:

            rs = request_stats
            # 将 request_stats 赋值给短变量 rs，方便后面引用
            # rs 对象包含 total_requests、total_errors 等属性

            stats = {
                "total_requests": rs.total_requests,
                # 总请求次数：从启动到现在一共收到了多少次 HTTP 请求

                "total_errors": rs.total_errors,
                # 总错误次数：其中发生了多少次服务器错误（5xx）

                "by_method": dict(rs.by_method),
                # 按 HTTP 方法（GET/POST/PUT/DELETE 等）统计的请求数量
                # dict(...) 把 Counter 或字典转成普通字典，确保 JSON 可序列化

                "start_time": rs.start_time,

                "uptime_seconds": int(time.time() - rs.start_time),
                # 系统运行时长（秒）：当前时间减去启动时间
                # int() 取整，去掉小数部分
            }
        else:

            stats = {
                "total_requests": 0, "total_errors": 0,
                # 总请求次数和总错误次数都默认为 0

                "by_method": {}, "by_path": [],
                # by_method 空字典，by_path 空列表（按路径统计，当前未实现）

                "start_time": time.time(), "uptime_seconds": 0,
                # start_time 设为当前时间，uptime_seconds 设为 0
            }

        return JSONResponse(content={


            "healthy": True,

            "user_count": user_count,
            # 用户总数（包括管理员和普通用户）

            "admin_count": admin_count,

            "session_count": session_count,

            "document_count": total_docs,
            # 文档总数（不重复的文档来源数量）

            "chunk_count": total_chunks,
            # 文档切块总数（所有文档被切成的片段数量）

            "partitions": partitions_summary,
            # 各分区的统计信息（每个分区包含多少切块和多少文档）

            "request_stats": stats,

            "tool_call_counts": dict(tool_registry.call_counts),


            "embedding_dim": vs.dimension if vs else None,
            # 向量维度：嵌入模型把文本转成向量的维度数

            "embedding_model": vs.embedding_model if vs else None,
            # 嵌入模型名称：比如 "text-embedding-3-small" 或 "bge-small-zh-v1.5"

        })

    except Exception as e:

        # Exception 是所有 Python 异常的基类

        logger.error(f"获取仪表盘数据失败: {e}")
        # 使用 logger 记录错误日志，方便开发者定位问题
        # 日志会包含错误信息 e（异常的字符串描述）

        raise HTTPException(status_code=500, detail=str(e))

