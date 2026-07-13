
"""管理后台 API - RAG 检索质量评估（精确率）"""

import json
import os
import threading
import uuid as _uuid
import time

from dataclasses import dataclass
from typing import List


@dataclass
class EvalResult:
    """单条评估结果。"""
    query: str
    retrieved_count: int
    relevant_count: int
    avg_score: float
    scores: list

    @property
    def precision(self) -> float:
        return self.relevant_count / self.retrieved_count if self.retrieved_count else 0.0


from . import router
from ..deps import admin_required, auth_required
from base.config import conf
from base.llm_client import OpenAIClient
from base.logger import logger
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse
from ..deps import system


# test_precision: 测试精确率的函数（虽然本文件中没有直接用到）
# load_test_queries: 加载测试查询列表（从文件中读取）
# save_test_queries: 保存测试查询列表（写入文件）


# ===== 全局变量：评估任务状态追踪 =====

_eval_tasks: dict[str, dict] = {}
_EVAL_RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "rag_eval", "eval_results.json",
)

_EVAL_DIR = os.path.dirname(_EVAL_RESULTS_FILE)
_TEST_QUERIES_FILE = os.path.join(_EVAL_DIR, "eval_queries.json")
_DEFAULT_EVAL_QUERIES = [
    "沪深300择时策略",
    "TD序列 GFTD 择时模型",
    "基金定投策略 智能定投",
    "保本基金 CPPI TIPP 策略",
    "行业轮动 景气度投资",
    "分析师推荐 港股 投资策略",
    "单向波动差值择时模型",
    "布林带择时定投",
    "量化择时 趋势跟踪",
    "风险平价 资产配置",
    "事件驱动策略 调研",
    "财报分析 营收增速",
    "机器学习 股价预测",
    "ETF 行业配置 轮动",
    "市场微观结构 高频数据",
    "违约风险 信用评估",
    "动量因子 反转效应",
    "波动率预测 风险管理",
    "止损策略 回撤控制",
    "多因子模型 选股",
]


def load_test_queries() -> list[str]:
    """从磁盘加载测试查询列表，不存在时返回默认列表。"""
    try:
        if os.path.exists(_TEST_QUERIES_FILE):
            with open(_TEST_QUERIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return _DEFAULT_EVAL_QUERIES


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

# started_at: 任务开始时间（时间戳）
# finished_at: 任务结束时间（时间戳）


# ===== API 端点：启动评估 =====
@router.post("/eval/run")
@auth_required
@admin_required  # 装饰器：要求用户必须是管理员（普通用户无权执行评估）
async def run_eval(request: Request):
    """启动精确率评估（后台运行，不阻塞）"""


    task_id = "eval_" + _uuid.uuid4().hex[:8]  # 用 uuid 生成随机字符串，取前 8 位，前面加上 "eval_" 前缀
    # 示例结果："eval_a1b2c3d4"

    # ===== 注册任务（初始化任务状态） =====
    queries = load_test_queries()
    _eval_tasks[task_id] = {
        "status": "running",  # 初始状态设为 "running"（运行中）
        "progress": {
            "total": len(queries),  # 总共需要评估的查询数量
            "completed": 0,  # 已经完成的查询数量（初始为 0）
            "current": "",  # 当前正在处理的查询内容（初始为空字符串）
        },
        "results": None,  # 评估结果列表，初始为 None，评估完成后会替换为实际结果
        "report": None,  # 汇总报告，初始为 None，评估完成后会生成
        "error": None,
        "started_at": time.time(),
        "finished_at": None,  # 任务结束时间，初始为 None，任务完成后会记录
    }


    def _worker():
        """后台工作线程：执行评估，更新进度，保存结果"""

        task = _eval_tasks[task_id]
        try:
            # ===== 创建 LLM 评判客户端 =====
            judge_client = OpenAIClient(
                api_key=conf.openai_api_key,
                base_url=conf.openai_base_url
            )


            from agent.tools.registry import ToolContext
            from agent.tools import registry
            import json
            import re as _re

            # ===== 准备工具上下文 =====
            ctx = ToolContext(
                vector_store=system.vector_store,
                partition=None,
                data_store=system.data_store,
            )

            # ===== 开始逐个评估查询 =====
            results: List[EvalResult] = []
            import concurrent.futures as _cf

            def _eval_one(query: str) -> EvalResult:
                """评估单个查询。"""

                raw = registry.dispatch(
                    "search_knowledge_base",
                    json.dumps({"queries": [query], "search_system": True}),
                    ctx=ctx,
                )

                # ===== 提取结果片段 =====
                chunks = _re.findall(r"【片段 \d+.*?。", raw, _re.DOTALL)
                if not chunks and raw.strip():
                    chunks = [raw]

                # ===== 用 LLM 给每个片段打分 =====
                scores = []
                for text in chunks:
                    from rag.eval_rag import llm_score
                    score = llm_score(judge_client, query, text)
                    scores.append(score)

                # ===== 计算统计指标 =====
                relevant = sum(1 for s in scores if s >= 3)
                avg = sum(scores) / len(scores) if scores else 0.0

                return EvalResult(
                    query=query,
                    retrieved_count=len(scores),
                    relevant_count=relevant,
                    avg_score=avg,
                    scores=scores,
                )

            # 并发执行（最多 N 个查询同时进行，从配置读取）
            max_workers = min(conf.eval_max_workers, len(queries))
            with _cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_eval_one, q): q for q in queries}
                for i, future in enumerate(_cf.as_completed(futures)):
                    query = futures[future]
                    task["progress"]["current"] = query
                    try:
                        result = future.result()
                        results.append(result)
                        task["progress"]["completed"] = i + 1
                        logger.debug(f"[评估] {query}: {result.relevant_count}/{result.retrieved_count} 相关, 平均分 {result.avg_score:.2f}")
                    except Exception as e:
                        logger.error(f"[评估] {query} 失败: {e}")
                        results.append(EvalResult(
                            query=query, retrieved_count=0, relevant_count=0,
                            avg_score=0.0, scores=[],
                        ))
                        task["progress"]["completed"] = i + 1

            # ===== 所有查询评估完毕，生成汇总报告 =====
            # 计算所有查询的精确率之和
            total_p = sum(r.precision for r in results)
            # 精确率 = relevant_count / retrieved_count（相关片段数 / 总检索片段数）
            n = len(results)
            avg_precision = total_p / n if n > 0 else 0.0

            # ===== 格式化结果数据（转为可序列化的字典列表） =====
            task["results"] = [  # 将结果存入任务状态字典
                {
                    "query": r.query,
                    "retrieved_count": r.retrieved_count,
                    "relevant_count": r.relevant_count,
                    "avg_score": round(r.avg_score, 2),  # 平均得分（四舍五入保留两位小数）
                    "scores": r.scores,
                    "precision": round(r.precision, 4),  # 该查询的精确率（四舍五入保留四位小数）
                }
                for r in results
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
            _save_results_to_disk()

            # ===== 记录完成日志 =====
            logger.info(f"评估完成: 平均精确率 {avg_precision:.1%}")

        # ===== 异常处理 =====
        except Exception as e:
            task["status"] = "failed"  # 将任务状态更新为 "failed"（失败）
            task["error"] = str(e)  # 记录错误信息（将异常对象转为字符串）
            task["finished_at"] = time.time()  # 记录任务结束时间（即使失败了也算结束）
            logger.error(f"评估失败: {e}")

    # ===== 启动后台线程 =====
    threading.Thread(target=_worker, daemon=True).start()
    # target=_worker：指定线程要执行的函数

    # .start()：启动线程开始执行


    return JSONResponse(content={
        "task_id": task_id,
        "message": f"评估已启动，共 {len(queries)} 个查询，请稍后查看结果",
        "total_queries": len(queries),  # 总共要评估的查询数量
    })


# ===== API 端点：查询评估状态 =====
@router.get("/eval/status/{task_id}")  # 注册 GET 请求的路由，URL 路径是 /eval/status/{task_id}
@auth_required
@admin_required
async def get_eval_status(request: Request, task_id: str):
    """查询评估任务状态和结果"""
    if task_id not in _eval_tasks:
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

    task = _eval_tasks[task_id]  # 通过 task_id 从全局字典中取出对应的任务状态字典

    # ===== 组装响应数据 =====
    resp = {
        "task_id": task_id,
        "status": task["status"],  # 任务状态（running / finished / failed）
        "progress": task["progress"],  # 进度信息（total 总数 / completed 已完成 / current 当前查询）
        "report": task["report"],  # 汇总报告（评估完成后才有值）
        "results": task["results"] if task["status"] == "finished" else None,
        "error": task["error"],
    }

    # ===== 清理旧任务（保留最近 5 个已完成的任务） =====
    _cleanup_tasks()
    return JSONResponse(content=resp)

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


@router.get("/eval/queries")  # 注册 GET 请求的路由，URL 路径是 /eval/queries
@auth_required
@admin_required
async def get_eval_queries(request: Request):
    """返回当前评估用的测试查询列表"""
    queries = load_test_queries()
    return JSONResponse(content={"queries": queries, "total": len(queries)})


# ===== API 端点：更新测试查询列表 =====
@router.put("/eval/queries")  # 注册 PUT 请求的路由，URL 路径是 /eval/queries
@auth_required
@admin_required
async def update_eval_queries(request: Request):
    """更新测试查询列表（保存到外部文件）"""
    try:
        body = await request.json()  # 异步读取请求体中的 JSON 数据（前端传来的数据）
        queries = body.get("queries", [])
        if not isinstance(queries, list) or not all(isinstance(q, str) and q.strip() for q in queries):
            #  all(...)：列表中的每个元素都必须满足：
            #    a. isinstance(q, str)：是字符串类型
            #    b. q.strip()：去除首尾空格后不为空（不能是空字符串或纯空格）
            raise HTTPException(status_code=400, detail="queries 必须是非空字符串列表")
        save_test_queries(queries)
        return JSONResponse(content={"message": f"已保存 {len(queries)} 个测试查询", "total": len(queries)})

    except HTTPException:
        raise  # 直接重新抛出（不做额外处理，让 FastAPI 的异常处理器来处理）
    except Exception as e:
        logger.error(f"保存测试查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))  # 抛出 HTTP 500 错误（服务器内部错误）


# ===== 辅助函数：清理旧任务 =====
def _cleanup_tasks():
    """清理已完成的任务，保留最近 5 个"""
    # 筛选出所有已完成或失败的任务
    finished = {k: v for k, v in _eval_tasks.items() if v["status"] in ("finished", "failed")}
    # 字典推导式：遍历 _eval_tasks 中的所有键值对
    # 只保留 status 为 "finished" 或 "failed" 的任务

    if len(finished) > 5:  # 判断已完成的任务数量是否超过 5 个
        # 对已完成的任务按完成时间排序（从早到晚）
        sorted_tasks = sorted(
            finished.keys(),  # 取所有已完成任务的 ID
            key=lambda k: _eval_tasks[k].get("finished_at", 0)  # 排序依据：每个任务的 finished_at 时间戳
        )
        for tid in sorted_tasks[:-5]:  # 遍历除了最后 5 个之外的所有任务（最早的 N-5 个）
            _eval_tasks.pop(tid, None)  # 从全局字典中删除该任务
            # 这样就把最老的已完成任务清理掉了，只保留最近的 5 个
