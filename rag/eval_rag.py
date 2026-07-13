# ── RAG 检索质量 LLM 评估 ─────────────────────────────────────────
"""RAG 检索质量 LLM 评估：基于实际数据的精确率测试。

评估流程：
  1. 准备测试查询（从 eval_queries.json 加载）
  2. 对每个查询调用 _exec_search_kb 工具执行检索
  3. LLM 对每条检索结果打分 (0-4)
  4. 计算平均精确率 Precision@K
"""

import json
import os

from typing import List

from dataclasses import dataclass

from base.config import conf
from base.logger import logger
from base.llm_client import OpenAIClient
from agent.tools.registry import ToolContext
from agent.tools import registry


_QUERIES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "rag_eval", "eval_queries.json"
)


# ── 测试查询加载 ──────────────────────────────────────────────────


def load_test_queries(path: str = _QUERIES_FILE) -> List[str]:
    """从外部 JSON 文件加载测试查询列表。

    Args:
        path: 查询 JSON 文件路径。

    Returns:
        查询字符串列表。文件不存在或格式异常时使用内置默认查询。
    """
    if not os.path.exists(path):
        logger.warning(f"测试查询文件不存在: {path}，使用内置默认查询")
        queries = _default_queries()
        _save_test_queries(queries, path)
        return queries
    with open(path, "r", encoding="utf-8") as f:
        queries = json.load(f)
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        logger.warning(f"测试查询文件格式异常，使用内置默认查询")
        queries = _default_queries()
        _save_test_queries(queries, path)
        return queries
    logger.info(f"已加载 {len(queries)} 个测试查询: {path}")
    return queries


def save_test_queries(queries: List[str], path: str = _QUERIES_FILE) -> None:
    """保存测试查询列表到外部 JSON 文件。

    Args:
        queries: 查询字符串列表。
        path: 目标 JSON 文件路径。
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存 {len(queries)} 个测试查询: {path}")


def _default_queries() -> List[str]:
    """返回内置默认测试查询列表。

    Returns:
        20 条金融量化相关的默认测试查询。
    """
    return [
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


def _save_test_queries(queries, path):
    """将查询写入 JSON 文件（方便用户自定义）。

    Args:
        queries: 查询字符串列表。
        path: 目标 JSON 文件路径。
    """
    try:
        import os as _os
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(queries, f, ensure_ascii=False, indent=2)
        logger.info(f"已生成默认测试查询文件: {path} ({len(queries)} 条)")
    except Exception as e:
        logger.warning(f"写入测试查询文件失败: {e}")


# ── 评估数据结构 ──────────────────────────────────────────────────


@dataclass
class EvalResult:
    """单条查询的评估结果。"""

    query: str
    """测试查询内容。"""

    retrieved_count: int
    """检索到的文档片段数量。"""

    relevant_count: int
    """相关片段数量（评分 ≥ 3）。"""

    avg_score: float
    """所有片段的平均得分。"""

    scores: List[int]
    """每个片段的评分列表（0-4）。"""

    @property
    def precision(self) -> float:
        """计算该查询的精确率。

        Returns:
            精确率值（0.0 ~ 1.0）。
        """
        return self.relevant_count / self.retrieved_count if self.retrieved_count > 0 else 0.0


# ── 评估执行 ──────────────────────────────────────────────────────

_EVAL_SYSTEM_PROMPT = (
    "你是一个检索质量评估专家。给定用户查询和检索到的文档片段，"
    "判断该片段是否与查询相关。\n\n"
    "评分标准：\n"
    "0 - 完全不相关\n"
    "1 - 主题相关但内容不直接回答查询\n"
    "2 - 部分相关，包含一些相关信息\n"
    "3 - 比较相关，包含关键信息\n"
    "4 - 高度相关，直接回答查询\n\n"
    "只输出一个数字（0-4），不要包含其他文字。"
)


def llm_score(client: OpenAIClient, query: str, text: str) -> int:
    """LLM 判断文本与查询的相关性，返回 0-4。

    Args:
        client: OpenAI 客户端实例。
        query: 用户查询文本。
        text: 待评估的文档片段文本。

    Returns:
        相关性评分 (0-4)，解析失败返回 0。
    """
    try:
        resp = client.chat(
            messages=[
                {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"用户查询：{query}\n\n文档片段：{text}"},
            ],
            model=conf.chat_model,
            stream=False,
            temperature=0.1,
            max_tokens=conf.max_output_chars,
        )
        score = int(resp.strip())
        return max(0, min(4, score))
    except (ValueError, TypeError):
        import re
        m = re.search(r"[0-4]", resp or "")
        if m:
            return int(m.group())
        logger.warning(f"LLM 评分失败 query={query!r} resp={resp!r}")
        return 0


def test_precision(judge_client: OpenAIClient, queries: List[str] = None) -> List[EvalResult]:
    """精确率测试：调用 _exec_search_kb，LLM 评判结果质量。

    Args:
        judge_client: 用于评分的 OpenAI 客户端实例。
        queries: 测试查询列表；为 None 时从文件加载默认查询。

    Returns:
        EvalResult 列表，每个查询对应一个评估结果。
    """
    from api.deps import system

    test_queries = queries if queries is not None else load_test_queries()

    ctx = ToolContext(
        vector_store=system.vector_store,
        partition=None,
        data_store=system.data_store,
    )

    results = []
    for query in test_queries:
        raw = registry.dispatch(
            "search_knowledge_base",
            json.dumps({"queries": [query], "search_system": True}),
            ctx=ctx,
        )

        import re
        chunks = re.findall(r"【片段 \d+.*?。", raw, re.DOTALL)
        if not chunks and raw.strip():
            chunks = [raw]

        scores = []
        for text in chunks:
            score = llm_score(judge_client, query, text)
            scores.append(score)

        relevant = sum(1 for s in scores if s >= 3)
        avg = sum(scores) / len(scores) if scores else 0.0

        results.append(EvalResult(
            query=query,
            retrieved_count=len(scores),
            relevant_count=relevant,
            avg_score=avg,
            scores=scores,
        ))

        logger.debug(f"[精确率] {query}: {relevant}/{len(scores)} 相关, 平均分 {avg:.2f}")

    return results


# ── 报告输出 ──────────────────────────────────────────────────────


def print_precision_report(results: List[EvalResult]):
    """打印精确率评估报告。

    Args:
        results: test_precision() 返回的评估结果列表。
    """
    print(f"\n{'=' * 70}")
    print(f"  精确率评估报告 (基于 _exec_search_kb)")
    print(f"{'=' * 70}\n")
    total_p = 0.0
    for r in results:
        print(f"  [{r.query[:20]:20s}] 评分={r.scores}  相关={r.relevant_count}/{r.retrieved_count}  "
              f"Prec@{r.retrieved_count}={r.precision:.1%}  均分={r.avg_score:.2f}")
        total_p += r.precision
    n = len(results)
    print(f"\n{'=' * 70}")
    print(f"  平均精确率 Precision@{results[0].retrieved_count}: {total_p / n:.1%}")
    print(f"{'=' * 70}")


# ── 主入口 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("  RAG 检索质量 LLM 评估（精确率）")
    print("  基于实际向量库数据，调用 _exec_search_kb")
    print("=" * 70)

    judge_client = OpenAIClient(api_key=conf.openai_api_key, base_url=conf.openai_base_url)

    precision_results = test_precision(judge_client)

    print_precision_report(precision_results)
