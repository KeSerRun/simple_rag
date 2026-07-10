# ===== 模块文档字符串（模块说明） =====
"""管理后台 API - RAG 检索质量评估（精确率）"""
# 这个模块提供了管理后台的评估 API，用于测试 RAG（检索增强生成）系统的检索精确率
# 精确率 = 相关片段数 / 总检索片段数，用来衡量检索质量好不好

# ===== 导入 Python 标准库模块 =====
import json
import os
import threading  # 导入 threading 模块，用于创建后台线程（让任务在后台运行，不阻塞主程序）
import uuid as _uuid  # 导入 uuid 模块并重命名为 _uuid，用于生成唯一的任务 ID
import time  # 导入 time 模块，用于记录任务开始和结束的时间戳

# ===== 导入类型提示相关 =====
from typing import List  # 从 typing 模块导入 List 类型，用于给变量做类型注解（提高代码可读性）

# ===== 导入项目内部模块 =====
from . import router  # 从当前包（admin 目录）导入 router 对象，用于注册 API 路由（URL 地址映射）
from ..deps import admin_required, auth_required  # 从父级目录的 deps 模块导入依赖函数：admin_required 表示需要管理员权限，auth_required 表示需要登录认证
from base.config import conf  # 从 base.config 模块导入 conf 对象，conf 保存了项目的所有配置信息（如 API 密钥、数据库地址等）
from base.logger import logger  # 从 base.logger 模块导入 logger 对象，用于在控制台或日志文件中输出日志信息
from fastapi import HTTPException, Query, Request  # 从 fastapi 导入 HTTPException（HTTP 错误响应）、Query（查询参数）、Request（HTTP 请求对象）
from fastapi.responses import JSONResponse  # 从 fastapi.responses 导入 JSONResponse，用于返回 JSON 格式的 HTTP 响应

# ===== 导入 RAG 评估相关模块 =====
from rag.eval_rag import test_precision, load_test_queries, save_test_queries, EvalResult  # 从 rag.eval_rag 模块导入评估函数和数据类型
# test_precision: 测试精确率的函数（虽然本文件中没有直接用到）
# load_test_queries: 加载测试查询列表（从文件中读取）
# save_test_queries: 保存测试查询列表（写入文件）
# EvalResult: 评估结果的数据类，包含 query（查询）、retrieved_count（检索数量）、relevant_count（相关数量）、avg_score（平均分）、scores（分数列表）等字段

# ===== 导入 LLM 客户端 =====
from base.llm_client import OpenAIClient  # 用于调用大语言模型 API

# ===== 全局变量：评估任务状态追踪 =====
# 评估任务状态追踪（这是一个全局字典，用来记录所有评估任务的执行状态）
_eval_tasks: dict[str, dict] = {}
_EVAL_RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "eval_results.json",
)


def _save_results_to_disk():
    """持久化最近一次评估结果到 JSON 文件。"""
    try:
        finished = [v for v in _eval_tasks.values() if v["status"] == "finished"]
        if not finished:
            return
        latest = max(finished, key=lambda v: v.get("finished_at") or 0)
        data = {
            "report": latest.get("report"),
            "results": latest.get("results"),
            "finished_at": latest.get("finished_at"),
        }
        os.makedirs(os.path.dirname(_EVAL_RESULTS_FILE), exist_ok=True)
        with open(_EVAL_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"评估结果持久化失败: {e}")


def _load_results_from_disk() -> dict | None:
    """从磁盘加载最近一次评估结果。"""
    try:
        if os.path.exists(_EVAL_RESULTS_FILE):
            with open(_EVAL_RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"评估结果加载失败: {e}")
    return None
# 任务详情结构：{"status": "running"|"finished"|"failed", "progress": {...}, "results": [...]}
# status: 任务状态，可选值有 running（运行中）、finished（已完成）、failed（失败）
# progress: 进度信息，包含 total（总数）、completed（已完成数）、current（当前正在处理的查询）
# results: 评估结果列表
# report: 汇总报告（平均精确率等）
# error: 错误信息（如果任务失败）
# started_at: 任务开始时间（时间戳）
# finished_at: 任务结束时间（时间戳）


# ===== API 端点：启动评估 =====
@router.post("/eval/run")  # 注册 POST 请求的路由，URL 路径是 /eval/run（前端通过这个地址启动评估）
@auth_required  # 装饰器：要求用户必须先登录（未登录会返回 401 错误）
@admin_required  # 装饰器：要求用户必须是管理员（普通用户无权执行评估）
async def run_eval(request: Request):
    """启动精确率评估（后台运行，不阻塞）"""
    # 该函数会创建一个后台线程来执行评估任务，然后立即返回，不会一直等着评估结束
    # 前端可以通过 task_id 轮询评估进度

    # 生成一个唯一的任务 ID
    task_id = "eval_" + _uuid.uuid4().hex[:8]  # 用 uuid 生成随机字符串，取前 8 位，前面加上 "eval_" 前缀
    # 示例结果："eval_a1b2c3d4"

    # ===== 注册任务（初始化任务状态） =====
    queries = load_test_queries()  # 调用加载函数，从文件中读取测试查询列表（返回一个字符串列表）
    _eval_tasks[task_id] = {  # 在全局字典 _eval_tasks 中注册这个新任务
        "status": "running",  # 初始状态设为 "running"（运行中）
        "progress": {  # 进度信息
            "total": len(queries),  # 总共需要评估的查询数量
            "completed": 0,  # 已经完成的查询数量（初始为 0）
            "current": "",  # 当前正在处理的查询内容（初始为空字符串）
        },
        "results": None,  # 评估结果列表，初始为 None，评估完成后会替换为实际结果
        "report": None,  # 汇总报告，初始为 None，评估完成后会生成
        "error": None,  # 错误信息，初始为 None，如果评估出错会记录在这里
        "paused": threading.Event(),  # 暂停/继续控制
        "started_at": time.time(),
        "finished_at": None,  # 任务结束时间，初始为 None，任务完成后会记录
    }

    # ===== 定义后台工作函数（在线程中运行） =====
    def _worker():
        """后台工作线程：执行评估，更新进度，保存结果"""
        # 这个函数会在后台线程中执行，所以不会阻塞 API 的响应
        task = _eval_tasks[task_id]  # 从全局字典中获取当前任务的状态字典（方便后续更新）
        try:
            # ===== 创建 LLM 评判客户端 =====
            judge_client = OpenAIClient(  # 创建一个 OpenAI 客户端实例，用于调用大模型来评判检索结果
                api_key=conf.openai_api_key,  # 从配置中获取 OpenAI API 密钥
                base_url=conf.openai_base_url  # 从配置中获取 OpenAI API 的基础 URL（可以是 OpenAI 官方或其他兼容服务）
            )

            # ===== 延迟导入（避免循环导入） =====
            from api.deps import system  # 从 api.deps 导入 system 对象（包含系统的各种组件，如向量数据库、数据存储等）
            from agent.tools.registry import ToolContext  # 从 agent.tools.registry 导入 ToolContext 类
            from agent.tools import registry  # 从 agent.tools 导入 registry 对象，这是工具注册表，可以调用各种注册好的工具
            import json  # 导入 json 模块，用于 JSON 序列化和反序列化
            import re as _re  # 导入 re 模块并重命名为 _re，用于正则表达式操作（提取检索结果中的文本片段）

            # ===== 准备工具上下文 =====
            ctx = ToolContext(  # 创建一个 ToolContext 实例，包含了工具执行所需的各种资源
                vector_store=system.vector_store,  # 向量数据库实例（用于语义搜索）
                partition=None,  # 分区参数设为 None（表示不分区，搜索所有数据）
                data_store=system.data_store,  # 数据存储实例（用于读写原始数据）
            )

            # ===== 开始逐个评估查询 =====
            results: List[EvalResult] = []
            for i, query in enumerate(queries):
                # 暂停检查
                while task["paused"].is_set():
                    task["status"] = "paused"
                    time.sleep(0.5)
                task["status"] = "running"
                task["progress"]["current"] = query

                # ===== 调用检索工具 =====
                raw = registry.dispatch(  # 通过工具注册表调用指定工具，dispatch 表示派遣、调度
                    "search_knowledge_base",  # 工具名称：搜索知识库（这个工具会在知识库中搜索相关内容）
                    json.dumps({"queries": [query], "search_system": True}),  # 工具参数：将查询打包成 JSON 字符串
                    # {"queries": [query]} 表示要搜索的查询列表，search_system: True 表示同时搜索系统知识
                    ctx=ctx,  # 传入工具上下文（包含向量数据库等资源）
                )
                # raw 是一个字符串，包含了检索结果

                # ===== 提取结果片段 =====
                chunks = _re.findall(r"【片段 \d+.*?。", raw, _re.DOTALL)  # 用正则表达式提取所有"【片段 N】...。"格式的文本块
                # r"【片段 \d+.*?。" 是一个正则表达式：
                # 【片段 ：匹配"【片段 "这几个字
                # \d+：匹配一个或多个数字（片段的编号）
                # .*?：匹配任意字符（非贪婪模式），直到遇到句号
                # 。：匹配句号
                # _re.DOTALL：让 . 可以匹配换行符
                if not chunks and raw.strip():  # 如果没有匹配到任何片段，但 raw 内容不为空（去除首尾空格后）
                    chunks = [raw]  # 那就把整个 raw 当作一个片段来处理

                # ===== 用 LLM 给每个片段打分 =====
                scores = []  # 创建一个空列表，用于存放每个片段的得分
                for text in chunks:  # 遍历所有提取到的文本片段
                    from rag.eval_rag import llm_score  # 延迟导入 llm_score 函数（用 LLM 给片段打分）

                    # 调用 LLM 评判函数，对片段进行评分
                    # 评判标准：LLM 判断该片段是否与查询相关，相关度越高分数越高（1-5 分）
                    score = llm_score(judge_client, query, text[:500])  # 只取文本的前 500 个字符（避免超出 LLM 的上下文限制）
                    scores.append(score)  # 将评分添加到 scores 列表中

                # ===== 计算统计指标 =====
                relevant = sum(1 for s in scores if s >= 3)  # 计算相关片段数：得分 >= 3 的片段被认为是相关的
                # sum(1 for ...) 是生成器表达式，对每个符合条件的元素计 1，然后求和
                avg = sum(scores) / len(scores) if scores else 0.0  # 计算平均分：总分除以数量，如果 scores 为空则默认为 0.0
                # 如果 scores 不为空，则 avg = 总分 / 数量；否则 avg = 0.0

                # ===== 记录单个查询的评估结果 =====
                results.append(EvalResult(  # 创建一个 EvalResult 对象并添加到 results 列表
                    query=query,  # 当前查询的文本
                    retrieved_count=len(scores),  # 检索到的片段数量（即 scores 的长度）
                    relevant_count=relevant,  # 其中相关的片段数量（得分 >= 3）
                    avg_score=avg,  # 这些片段的平均得分
                    scores=scores,  # 每个片段的具体得分列表
                ))
                task["progress"]["completed"] = i + 1  # 更新进度：已完成的任务数（i 从 0 开始，所以加 1）

                # ===== 记录日志 =====
                logger.debug(f"[评估] {query}: {relevant}/{len(scores)} 相关, 平均分 {avg:.2f}")
                # 输出日志：当前查询名称、相关数/总数、平均分（保留两位小数）

            # ===== 所有查询评估完毕，生成汇总报告 =====
            # 计算所有查询的精确率之和
            total_p = sum(r.precision for r in results)  # r.precision 是 EvalResult 的一个属性，表示该查询的精确率
            # 精确率 = relevant_count / retrieved_count（相关片段数 / 总检索片段数）
            n = len(results)  # 查询总数
            avg_precision = total_p / n if n > 0 else 0.0  # 平均精确率 = 精确率总和 / 查询数量，如果查询数为 0 则默认为 0.0

            # ===== 格式化结果数据（转为可序列化的字典列表） =====
            task["results"] = [  # 将结果存入任务状态字典
                {
                    "query": r.query,  # 查询文本
                    "retrieved_count": r.retrieved_count,  # 检索到的片段总数
                    "relevant_count": r.relevant_count,  # 相关的片段数
                    "avg_score": round(r.avg_score, 2),  # 平均得分（四舍五入保留两位小数）
                    "scores": r.scores,  # 每个片段的具体得分列表
                    "precision": round(r.precision, 4),  # 该查询的精确率（四舍五入保留四位小数）
                }
                for r in results  # 遍历每个评估结果
            ]

            # ===== 生成汇总报告 =====
            task["report"] = {  # 汇总报告存入任务状态字典
                "total_queries": n,  # 总共评估了多少个查询
                "avg_precision": round(avg_precision, 4),  # 平均精确率（数值形式，保留四位小数）
                "avg_precision_pct": f"{avg_precision:.1%}",  # 平均精确率（百分比形式，保留一位小数，例如"85.3%"）
            }

            # ===== 标记任务完成并持久化 =====
            task["status"] = "finished"  # 将任务状态更新为 "finished"（已完成）
            task["finished_at"] = time.time()  # 记录任务完成时间（当前时间戳）
            _save_results_to_disk()  # 持久化到磁盘

            # ===== 记录完成日志 =====
            logger.info(f"评估完成: 平均精确率 {avg_precision:.1%}")

        # ===== 异常处理 =====
        except Exception as e:  # 如果在执行过程中发生任何异常
            task["status"] = "failed"  # 将任务状态更新为 "failed"（失败）
            task["error"] = str(e)  # 记录错误信息（将异常对象转为字符串）
            task["finished_at"] = time.time()  # 记录任务结束时间（即使失败了也算结束）
            logger.error(f"评估失败: {e}")

    # ===== 启动后台线程 =====
    threading.Thread(target=_worker, daemon=True).start()
    # target=_worker：指定线程要执行的函数
    # daemon=True：设置为守护线程，当主程序退出时，这个线程也会自动退出
    # .start()：启动线程开始执行

    # ===== 立即返回响应（不等待评估完成） =====
    return JSONResponse(content={  # 返回一个 JSON 格式的响应
        "task_id": task_id,  # 任务 ID，前端可以用这个 ID 来查询评估进度和结果
        "message": f"评估已启动，共 {len(queries)} 个查询，请稍后查看结果",  # 提示消息
        "total_queries": len(queries),  # 总共要评估的查询数量
    })
    # 前端收到这个响应后，就知道任务已经开始，然后可以轮询 /eval/status/{task_id} 接口来获取进度


# ===== API 端点：查询评估状态 =====
@router.get("/eval/status/{task_id}")  # 注册 GET 请求的路由，URL 路径是 /eval/status/{task_id}
# {task_id} 是路径参数，会被自动提取并传给函数参数
@auth_required  # 要求用户已登录
@admin_required  # 要求用户是管理员
async def get_eval_status(request: Request, task_id: str):
    """查询评估任务状态和结果"""
    # 前端轮询这个接口来获取评估进度和最终结果

    # 检查任务是否存在
    if task_id not in _eval_tasks:  # 如果传入的 task_id 不在全局字典中
        # 尝试从磁盘加载最近一次评估结果（服务器重启后仍有数据）
        saved = _load_results_from_disk()
        if saved and saved.get("results"):
            return JSONResponse(content={
                "task_id": task_id,
                "status": "finished",
                "progress": {"total": len(saved["results"]), "completed": len(saved["results"]), "current": ""},
                "report": saved.get("report"),
                "results": saved.get("results"),
                "error": None,
            })
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
        # 抛出 HTTP 404 错误（Not Found），提示任务不存在

    # 从全局字典中获取任务信息
    task = _eval_tasks[task_id]  # 通过 task_id 从全局字典中取出对应的任务状态字典

    # ===== 组装响应数据 =====
    resp = {  # 准备要返回的响应数据
        "task_id": task_id,  # 任务 ID
        "status": task["status"],  # 任务状态（running / finished / failed）
        "progress": task["progress"],  # 进度信息（total 总数 / completed 已完成 / current 当前查询）
        "report": task["report"],  # 汇总报告（评估完成后才有值）
        "results": task["results"] if task["status"] == "finished" else None,  # 如果任务已完成则返回结果，否则返回 None
        "error": task["error"],  # 错误信息（如果任务失败）
    }
    # 注意：results 只在状态为 finished 时返回，这样可以避免在任务还在运行时返回不完整的数据

    # ===== 清理旧任务（保留最近 5 个已完成的任务） =====
    _cleanup_tasks()  # 调用清理函数，删除过旧的已完成任务，防止内存占用过多

    # 返回 JSON 响应
    return JSONResponse(content=resp)  # 将 resp 字典转为 JSON 格式返回给前端


# ===== API 端点：获取最近一次评估结果 =====
@router.get("/eval/last")
@auth_required
@admin_required
async def get_last_eval_result(request: Request):
    """返回最近一次评估结果（从磁盘加载，服务器重启后仍有数据）。"""
    saved = _load_results_from_disk()
    if saved and saved.get("results"):
        return JSONResponse(content={
            "status": "finished",
            "report": saved.get("report"),
            "results": saved.get("results"),
            "finished_at": saved.get("finished_at"),
        })
    return JSONResponse(content={"status": "no_results", "results": None})


# ===== API 端点：暂停评估 =====
@router.post("/eval/pause/{task_id}")
@auth_required
@admin_required
async def pause_eval(request: Request, task_id: str):
    """暂停正在运行的评估。"""
    if task_id not in _eval_tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    task = _eval_tasks[task_id]
    if task["status"] not in ("running", "paused"):
        raise HTTPException(status_code=400, detail="任务不在运行中")
    task["paused"].set()
    task["status"] = "paused"
    return JSONResponse(content={"message": "评估已暂停", "task_id": task_id})


# ===== API 端点：继续评估 =====
@router.post("/eval/resume/{task_id}")
@auth_required
@admin_required
async def resume_eval(request: Request, task_id: str):
    """继续已暂停的评估。"""
    if task_id not in _eval_tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    task = _eval_tasks[task_id]
    if task["status"] != "paused":
        raise HTTPException(status_code=400, detail="任务不在暂停状态")
    task["paused"].clear()
    task["status"] = "running"
    return JSONResponse(content={"message": "评估已继续", "task_id": task_id})


# ===== API 端点：获取测试查询列表 =====
@router.get("/eval/queries")  # 注册 GET 请求的路由，URL 路径是 /eval/queries
@auth_required  # 要求用户已登录
@admin_required  # 要求用户是管理员
async def get_eval_queries(request: Request):
    """返回当前评估用的测试查询列表"""
    # 这个接口用于让前端展示当前有哪些测试查询

    queries = load_test_queries()  # 调用加载函数，从文件中读取测试查询列表
    return JSONResponse(content={"queries": queries, "total": len(queries)})
    # 返回 JSON，包含 queries（查询列表）和 total（查询总数）


# ===== API 端点：更新测试查询列表 =====
@router.put("/eval/queries")  # 注册 PUT 请求的路由，URL 路径是 /eval/queries
# PUT 请求通常用于更新资源（这里是更新测试查询列表）
@auth_required  # 要求用户已登录
@admin_required  # 要求用户是管理员
async def update_eval_queries(request: Request):
    """更新测试查询列表（保存到外部文件）"""
    # 前端通过这个接口来修改测试查询列表（增删改查中的"改"）

    try:  # 开始异常捕获
        body = await request.json()  # 异步读取请求体中的 JSON 数据（前端传来的数据）
        queries = body.get("queries", [])  # 从 JSON 中获取 queries 字段，如果不存在则默认空列表

        # ===== 参数校验 =====
        if not isinstance(queries, list) or not all(isinstance(q, str) and q.strip() for q in queries):
            # 检查 queries 是否满足以下条件：
            # 1. isinstance(queries, list)：queries 必须是一个列表
            # 2. all(...)：列表中的每个元素都必须满足：
            #    a. isinstance(q, str)：是字符串类型
            #    b. q.strip()：去除首尾空格后不为空（不能是空字符串或纯空格）
            # 如果不满足条件：
            raise HTTPException(status_code=400, detail="queries 必须是非空字符串列表")
            # 抛出 HTTP 400 错误（Bad Request），提示参数格式不对

        save_test_queries(queries)  # 调用保存函数，将查询列表写入文件（持久化存储）

        # 返回成功响应
        return JSONResponse(content={"message": f"已保存 {len(queries)} 个测试查询", "total": len(queries)})
        # 返回提示消息和查询总数

    except HTTPException:  # 如果捕获到 HTTPException 类型的异常
        raise  # 直接重新抛出（不做额外处理，让 FastAPI 的异常处理器来处理）
    except Exception as e:  # 如果是其他类型的异常（如文件写入失败）
        logger.error(f"保存测试查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出 HTTP 500 错误（服务器内部错误）


# ===== 辅助函数：清理旧任务 =====
def _cleanup_tasks():
    """清理已完成的任务，保留最近 5 个"""
    # 这个函数会在每次查询状态时被调用，防止全局字典 _eval_tasks 无限膨胀

    # 筛选出所有已完成或失败的任务
    finished = {k: v for k, v in _eval_tasks.items() if v["status"] in ("finished", "failed")}
    # 字典推导式：遍历 _eval_tasks 中的所有键值对
    # 只保留 status 为 "finished" 或 "failed" 的任务

    # 如果已完成的任务超过 5 个，就清理掉最早的
    if len(finished) > 5:  # 判断已完成的任务数量是否超过 5 个
        # 对已完成的任务按完成时间排序（从早到晚）
        sorted_tasks = sorted(  # sorted 函数返回一个排序后的列表
            finished.keys(),  # 取所有已完成任务的 ID
            key=lambda k: _eval_tasks[k].get("finished_at", 0)  # 排序依据：每个任务的 finished_at 时间戳
            # lambda k: ... 是一个匿名函数，输入是任务 ID k，输出是该任务的完成时间
            # .get("finished_at", 0) 表示获取 finished_at 字段，如果没有则默认 0
        )
        for tid in sorted_tasks[:-5]:  # 遍历除了最后 5 个之外的所有任务（最早的 N-5 个）
            _eval_tasks.pop(tid, None)  # 从全局字典中删除该任务
            # pop(key, default) 方法：删除指定键并返回对应的值，如果键不存在则返回 None
            # 这样就把最老的已完成任务清理掉了，只保留最近的 5 个
