"""管理后台 API - 仪表盘"""
# 上面的双引号是 Python 的模块文档字符串，说明这个文件是"管理后台 API - 仪表盘"功能
# 简单说就是：这个文件专门处理管理后台"总览/仪表盘"页面的数据接口

# ===== 导入标准库 =====
import time
# 导入 Python 内置的 time 模块，后面用来计算系统运行时长（uptime）
# time.time() 可以获取当前时间戳（从 1970 年 1 月 1 日到现在的秒数）

# ===== 导入项目内部模块 =====
from . import router
# 从当前包（backend/api/admin/__init__.py）导入 router 对象
# router 是一个 FastAPI 的 APIRouter 实例，用来注册路由（URL 接口）
# 这样 /dashboard 接口就会挂载到 /api/admin/dashboard 这个路径下

from ..deps import admin_required, auth_required, system
# 从父包（backend/api/deps.py）导入三个依赖：
#   auth_required    - 登录认证装饰器，没登录的用户会被拦截
#   admin_required   - 管理员权限装饰器，普通用户会被拦截
#   system           - 系统核心对象，包含数据存储、向量库等全局实例

from base.logger import logger
# 从 base/logger.py 导入日志记录器 logger
# 用来记录错误日志，方便排查问题

from fastapi import HTTPException, Request
# 从 FastAPI 框架导入：
#   HTTPException   - 用于返回 HTTP 错误响应（比如 500 服务器错误）
#   Request         - 代表客户端发来的 HTTP 请求对象

from fastapi.responses import JSONResponse
# 从 FastAPI 导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应
# 前端拿到 JSON 数据后就能渲染仪表盘页面

from agent.tools import registry as tool_registry
# 全局工具注册表，用于获取各工具累计调用次数

# ===== 注册仪表盘接口 =====
@router.get("/dashboard")
# FastAPI 路由装饰器：当客户端发送 GET 请求到 /dashboard 路径时，执行下面的函数
# router 是 APIRouter 实例，最终这个接口路径会是 /api/admin/dashboard

@auth_required
# 认证装饰器：请求必须先通过登录验证
# 如果没有有效的 token 或 session，会返回 401 未授权错误

@admin_required
# 管理员权限装饰器：只有 role="admin" 的用户才能访问
# 普通用户访问会返回 403 禁止访问错误

async def get_dashboard(request: Request):
    # 定义异步函数 get_dashboard，接收一个 Request 参数
    # async 表示这是一个异步函数，FastAPI 可以同时处理多个请求而不阻塞
    # request: Request - FastAPI 自动注入的 HTTP 请求对象，包含请求头、参数等信息

    """系统总览: 健康状态 / 用户数 / 会话数 / 文档数 / 切块数 / 请求统计"""
    # 函数的文档字符串，描述这个接口返回哪些数据
    # 包括：系统是否健康、用户数量、会话数量、文档数量、文本切块数量、请求统计

    try:
        # try 块：包裹可能出错的代码，如果出错了就跳到 except 块处理
        # 防止因为某个数据获取失败导致整个接口崩溃

        # ===== 1. 用户与会话统计 =====
        users_data = system.data_store.get_all_users(page=1, page_size=999999)
        # 调用系统数据存储的 get_all_users 方法获取全部用户数据
        # system.data_store 是全局的 JSON 数据存储对象
        # page=1 表示第一页，page_size=999999 表示一页拉取 999999 条，相当于获取所有用户
        # 返回的 users_data 是一个字典，包含 items（用户列表）和 total（总数）

        users_list = users_data.get("items", [])
        # 从返回数据中取出 items 字段，也就是用户列表
        # .get("items", []) 意思是：如果有 items 字段就用它，没有就用空列表 []
        # 这样即使数据格式不对也不会报错

        user_count = users_data.get("total", 0)
        # 从返回数据中取出 total 字段，也就是用户总数
        # 如果没有 total 字段，默认返回 0

        session_count = 0
        # 初始化会话数量为 0
        # 注意：这里 session_count 一直为 0，目前没有实际的会话统计逻辑
        # 后续可以接入 Redis 或数据库来统计在线会话数

        admin_count = sum(1 for u in users_list if u.get("role") == "admin")
        # 统计管理员数量：遍历用户列表，对每个用户检查 role 字段是否等于 "admin"
        # sum(1 for ...) 是 Python 的生成器表达式，每找到一个管理员就加 1
        # 最终得到管理员的总人数

        # ===== 2. 向量库统计 =====
        vs = system.vector_store
        # 获取系统向量存储对象（VectorStore），用来保存文档的向量化数据
        # system.vector_store 是全局的向量数据库实例（例如 FAISS 或 Chroma）
        # VS = VectorStore 的缩写

        total_chunks = len(vs.metadata) if vs and vs.metadata else 0
        # 计算向量库中的总切块数（chunks）
        # 文档被切成小段（chunk），每段会被向量化存入向量库
        # vs.metadata 是存储所有切块元数据的列表
        # 条件判断：如果 vs 存在且 vs.metadata 有值，就取它的长度，否则为 0

        total_docs = 0
        # 初始化文档总数为 0

        if total_chunks > 0:
            # 如果总切块数大于 0，才进行文档统计
            # 这样可以避免在空向量库上做无意义的计算

            sources = set(m.get("source", "") for m in vs.metadata if m.get("source"))
            # 从所有切块的元数据中提取 source 字段（来源文档路径/名称）
            # set(...) 用集合去重，同一个文档的多个切块有相同的 source
            # m.get("source", "") - 如果某个切块没有 source 字段，就跳过（空字符串会被 if 过滤）
            # 最终 sources 是一个集合，包含所有不重复的文档来源

            total_docs = len(sources)
            # 集合的长度就是不重复的文档数量

        # ===== 3. 分区统计 =====
        partitions = {}
        # 初始化空字典，用来存储每个分区的统计信息
        # 分区（partition）是向量库中的一种分类方式
        # 不同来源的文档可以分到不同分区，方便隔离和查询

        if total_chunks > 0:
            # 同样，只有向量库中有数据才进行统计

            for m in vs.metadata:
                # 遍历向量库中每一个切块的元数据
                # m 是每个切块的元数据字典

                p = m.get("partition", "default")
                # 从元数据中获取分区名称，如果没有设置分区就用 "default"（默认分区）
                # 这样所有没有指定分区的切块都会被归到 "default" 下

                partitions.setdefault(p, {"chunks": 0, "sources": set()})
                # setdefault 是字典的方法：如果 p 这个分区还不存在于 partitions 中，就初始化它
                # 每个分区记录两个字段：
                #   chunks  - 切块数量（整数）
                #   sources - 来源文档集合（set，自动去重）
                # 如果分区已存在，就不做任何操作

                partitions[p]["chunks"] += 1
                # 当前分区的切块数加 1
                # 遍历一遍所有切块，每个切块都给自己所属的分区贡献 1 个计数

                if m.get("source"):
                    # 如果当前切块有 source 字段（来源文档路径/名称）
                    # 就把它加入分区的 sources 集合

                    partitions[p]["sources"].add(m["source"])
                    # 使用 set.add() 添加来源，自动去重
                    # 同一个文档的多个切块只会计入一次

        partitions_summary = {
            # 构建分区摘要字典，准备返回给前端
            # 因为 partitions 中的 sources 是 set 类型，JSON 不支持 set
            # 所以需要把 set 转换成整数（数量）

            p: {"chunks": v["chunks"], "sources": len(v["sources"])}
            # 遍历每个分区，把 sources 集合的长度（文档数量）取出来
            # 最终每个分区返回：chunks（切块数），sources（文档数）

            for p, v in partitions.items()
            # 遍历 partitions 字典的键值对
            # p 是分区名，v 是 {"chunks": ..., "sources": set(...)}
        }

        # ===== 4. 请求统计 =====
        from . import request_stats
        # 从当前包（backend/api/admin/__init__.py）导入 request_stats 对象
        # request_stats 是一个统计模块，由 app.py 在启动时注入
        # 注意这个 import 放在函数内部，是延迟导入，避免循环依赖

        if request_stats:
            # 如果 request_stats 存在（非 None/非空），就从中读取统计数据
            # 如果应用启动时没有正确注入，request_stats 可能为 None

            rs = request_stats
            # 将 request_stats 赋值给短变量 rs，方便后面引用
            # rs 对象包含 total_requests、total_errors 等属性

            stats = {
                # 构建请求统计字典
                "total_requests": rs.total_requests,
                # 总请求次数：从启动到现在一共收到了多少次 HTTP 请求

                "total_errors": rs.total_errors,
                # 总错误次数：其中发生了多少次服务器错误（5xx）

                "by_method": dict(rs.by_method),
                # 按 HTTP 方法（GET/POST/PUT/DELETE 等）统计的请求数量
                # dict(...) 把 Counter 或字典转成普通字典，确保 JSON 可序列化

                "start_time": rs.start_time,
                # 系统启动时间戳（epoc秒），即系统从什么时候开始运行

                "uptime_seconds": int(time.time() - rs.start_time),
                # 系统运行时长（秒）：当前时间减去启动时间
                # int() 取整，去掉小数部分
            }
        else:
            # 如果 request_stats 不存在，就返回空数据
            # 这种情况发生在 request_stats 模块未初始化时

            stats = {
                # 返回默认的空统计数据，避免前端拿到 None 报错
                "total_requests": 0, "total_errors": 0,
                # 总请求次数和总错误次数都默认为 0

                "by_method": {}, "by_path": [],
                # by_method 空字典，by_path 空列表（按路径统计，当前未实现）

                "start_time": time.time(), "uptime_seconds": 0,
                # start_time 设为当前时间，uptime_seconds 设为 0
            }

        # ===== 5. 组装最终响应 =====
        return JSONResponse(content={
            # 返回 JSON 格式的 HTTP 响应，content 字典会自动转成 JSON 字符串
            # 前端 JavaScript 可以直接解析使用

            "healthy": True,
            # 系统健康状态：True 表示正常运行
            # 走到这里说明没抛异常，所以是健康的

            "user_count": user_count,
            # 用户总数（包括管理员和普通用户）

            "admin_count": admin_count,
            # 管理员总数

            "session_count": session_count,
            # 会话数量（当前为 0，因为还没有实际的会话追踪逻辑）

            "document_count": total_docs,
            # 文档总数（不重复的文档来源数量）

            "chunk_count": total_chunks,
            # 文档切块总数（所有文档被切成的片段数量）

            "partitions": partitions_summary,
            # 各分区的统计信息（每个分区包含多少切块和多少文档）

            "request_stats": stats,
            # 请求统计数据（总请求数、错误数、按方法统计等）

            "tool_call_counts": dict(tool_registry.call_counts),
            # 各工具累计调用次数（从启动开始统计）
            # 数据格式: {"search_knowledge_base": 12, "web_search": 3, ...}

            "embedding_dim": vs.dimension if vs else None,
            # 向量维度：嵌入模型把文本转成向量的维度数
            # 如果 vs 不存在就返回 None

            "embedding_model": vs.embedding_model if vs else None,
            # 嵌入模型名称：比如 "text-embedding-3-small" 或 "bge-small-zh-v1.5"
            # 如果 vs 不存在就返回 None

        })

    except Exception as e:
        # 捕获 try 块中发生的任何异常
        # Exception 是所有 Python 异常的基类
        # 只要 try 里任何一行代码出错，就会跳到这里

        logger.error(f"获取仪表盘数据失败: {e}")
        # 使用 logger 记录错误日志，方便开发者定位问题
        # 日志会包含错误信息 e（异常的字符串描述）

        raise HTTPException(status_code=500, detail=str(e))
        # 抛出 FastAPI 的 HTTP 异常，返回 500 Internal Server Error
        # status_code=500 表示服务器内部错误
        # detail=str(e) 把异常信息传给前端，方便调试
        # 前端会收到 {"detail": "具体的错误信息"} 这样的 JSON 响应
