"""管理后台 API - RAG 检索质量评估(精确率)"""

import json
import os
import threading
import uuid as _uuid
import time

from dataclasses import dataclass
from typing import List


@dataclass
class EvalResult:
    """单条评估结果。

    Attributes:
        query: 测试查询语句。
        retrieved_count: 召回片段数。
        relevant_count: 相关片段数(评分 >= 3)。
        avg_score: 平均评分。
        scores: 逐片段评分列表。
    """
    query: str
    retrieved_count: int
    relevant_count: int
    avg_score: float
    scores: list

    @property
    def precision(self) -> float:
        """计算该查询的精确率(precision = relevant / retrieved)。"""
        return self.relevant_count / self.retrieved_count if self.retrieved_count else 0.0


from . import router
from ..deps import admin_required, auth_required
from base.config import conf
from base.llm_client import OpenAIClient
from base.logger import logger
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse
from ..deps import system




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
    """从磁盘加载测试查询列表,不存在时返回默认列表。

    Returns:
        list[str]: 测试查询语句列表。
    """
    try:
        if os.path.exists(_TEST_QUERIES_FILE):
            with open(_TEST_QUERIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return _DEFAULT_EVAL_QUERIES


def save_test_queries(queries: list[str]):
    """保存测试查询列表到磁盘文件。

    Args:
        queries: 测试查询语句列表。
    """
    os.makedirs(os.path.dirname(_TEST_QUERIES_FILE), exist_ok=True)
    with open(_TEST_QUERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, indent=2)


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
    """从磁盘加载最近一次评估结果。

    Returns:
        dict | None: 包含 report / results / finished_at 的字典,无数据时返回 None。
    """
    try:
        if os.path.exists(_EVAL_RESULTS_FILE):
            with open(_EVAL_RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"评估结果加载失败: {e}")
    return None



@router.post("/eval/run")
@auth_required
@admin_required
async def run_eval(request: Request):
    """启动精确率评估(后台运行,不阻塞)。

    # ── 评估流程

    1. 加载测试查询列表 (load_test_queries)
    2. 后台线程逐条执行 ``search_knowledge_base`` 工具召回
    3. 使用 LLM 对每条召回片段评分 (0-4 分)
    4. 统计精确率,保存结果到磁盘

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"task_id": str, "message": str, "total_queries": int}``,
        立即返回,不等待评估完成。
    """


    task_id = "eval_" + _uuid.uuid4().hex[:8]

    queries = load_test_queries()
    _eval_tasks[task_id] = {
        "status": "running",
        "progress": {
            "total": len(queries),
            "completed": 0,
            "current": "",
        },
        "results": None,
        "report": None,
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
    }


    def _worker():
        """后台工作线程:执行评估,更新进度,保存结果。"""

        task = _eval_tasks[task_id]
        try:
            judge_client = OpenAIClient(
                api_key=conf.openai_api_key,
                base_url=conf.openai_base_url
            )


            from agent.tools.registry import ToolContext
            from agent.tools import registry
            import json
            import re as _re

            ctx = ToolContext(
                vector_store=system.vector_store,
                partition=None,
                data_store=system.data_store,
            )

            results: List[EvalResult] = []
            import concurrent.futures as _cf

            def _eval_one(query: str) -> EvalResult:
                """评估单个查询:知识库召回 + LLM 评分。

                Args:
                    query: 测试查询语句。

                Returns:
                    EvalResult: 包含召回片段数、相关片段数、平均评分。
                """

                raw = registry.dispatch(
                    "search_knowledge_base",
                    json.dumps({"queries": [query], "search_system": True}),
                    ctx=ctx,
                )

                chunks = _re.findall(r"【片段 \d+.*?。", raw, _re.DOTALL)
                if not chunks and raw.strip():
                    chunks = [raw]

                scores = []
                for text in chunks:
                    from rag.eval_rag import llm_score
                    score = llm_score(judge_client, query, text)
                    scores.append(score)

                relevant = sum(1 for s in scores if s >= 3)
                avg = sum(scores) / len(scores) if scores else 0.0

                return EvalResult(
                    query=query,
                    retrieved_count=len(scores),
                    relevant_count=relevant,
                    avg_score=avg,
                    scores=scores,
                )

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

            total_p = sum(r.precision for r in results)
            n = len(results)
            avg_precision = total_p / n if n > 0 else 0.0

            task["results"] = [
                {
                    "query": r.query,
                    "retrieved_count": r.retrieved_count,
                    "relevant_count": r.relevant_count,
                    "avg_score": round(r.avg_score, 2),
                    "scores": r.scores,
                    "precision": round(r.precision, 4),
                }
                for r in results
            ]

            task["report"] = {
                "total_queries": n,
                "avg_precision": round(avg_precision, 4),
                "avg_precision_pct": f"{avg_precision:.1%}",
            }

            task["status"] = "finished"
            task["finished_at"] = time.time()
            _save_results_to_disk()

            logger.info(f"评估完成: 平均精确率 {avg_precision:.1%}")

        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            task["finished_at"] = time.time()
            logger.error(f"评估失败: {e}")

    threading.Thread(target=_worker, daemon=True).start()



    return JSONResponse(content={
        "task_id": task_id,
        "message": f"评估已启动，共 {len(queries)} 个查询，请稍后查看结果",
        "total_queries": len(queries),
    })


@router.get("/eval/status/{task_id}")
@auth_required
@admin_required
async def get_eval_status(request: Request, task_id: str):
    """查询评估任务状态和结果。

    # ── 返回

    - running: 返回进度信息
    - finished: 返回报告和详细结果
    - failed: 返回错误信息

    若 task_id 不在内存中,尝试从磁盘加载最近一次结果。

    Args:
        request: FastAPI 请求对象。
        task_id: 评估任务 ID。

    Returns:
        JSONResponse: 包含 status / progress / report / results 等字段。

    Raises:
        HTTPException 404: 任务不存在且无磁盘缓存。
    """
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

    task = _eval_tasks[task_id]

    resp = {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "report": task["report"],
        "results": task["results"] if task["status"] == "finished" else None,
        "error": task["error"],
    }

    _cleanup_tasks()
    return JSONResponse(content=resp)

@router.get("/eval/last")
@auth_required
@admin_required
async def get_last_eval_result(request: Request):
    """返回最近一次评估结果(从磁盘加载,服务器重启后仍有数据)。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 有数据时返回 ``{"status": "finished", "report": dict, "results": [...]}``;
        无数据时返回 ``{"status": "no_results"}``。
    """
    saved = _load_results_from_disk()
    if saved and saved.get("results"):
        return JSONResponse(content={
            "status": "finished",
            "report": saved.get("report"),
            "results": saved.get("results"),
            "finished_at": saved.get("finished_at"),
        })
    return JSONResponse(content={"status": "no_results", "results": None})


@router.get("/eval/queries")
@auth_required
@admin_required
async def get_eval_queries(request: Request):
    """返回当前评估用的测试查询列表。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"queries": [str, ...], "total": int}``。
    """
    queries = load_test_queries()
    return JSONResponse(content={"queries": queries, "total": len(queries)})


@router.put("/eval/queries")
@auth_required
@admin_required
async def update_eval_queries(request: Request):
    """更新测试查询列表(保存到外部文件)。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"queries": [str, ...]}``。

    Returns:
        JSONResponse: ``{"message": str, "total": int}``。

    Raises:
        HTTPException 400: queries 格式非法。
        HTTPException 500: 保存失败。
    """
    try:
        body = await request.json()
        queries = body.get("queries", [])
        if not isinstance(queries, list) or not all(isinstance(q, str) and q.strip() for q in queries):
            raise HTTPException(status_code=400, detail="queries 必须是非空字符串列表")
        save_test_queries(queries)
        return JSONResponse(content={"message": f"已保存 {len(queries)} 个测试查询", "total": len(queries)})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存测试查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _cleanup_tasks():
    """清理已完成的任务,保留最近 5 个。"""
    finished = {k: v for k, v in _eval_tasks.items() if v["status"] in ("finished", "failed")}

    if len(finished) > 5:
        sorted_tasks = sorted(
            finished.keys(),
            key=lambda k: _eval_tasks[k].get("finished_at", 0)
        )
        for tid in sorted_tasks[:-5]:
            _eval_tasks.pop(tid, None)
