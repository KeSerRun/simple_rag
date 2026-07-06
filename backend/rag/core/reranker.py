"""LLM Listwise Reranker: 通过大模型对检索结果进行重排序。

工作原理:
  1. 向量检索（FAISS）先召回 N 个候选 chunk（通常比最终需要的多，如 Top-30）
  2. 将 query + 所有候选 chunk 发送给 LLM
  3. LLM 根据相关性对 chunk 进行排序，输出排序后的编号列表
  4. 按 LLM 输出的顺序重新排列 chunk，取前 K 个

与 Cross-Encoder Rerank 的区别:
  - Cross-Encoder: 需要专门的重排模型（如 bge-reranker-v2-m3），单次推理极快
  - LLM Listwise: 利用已接入的 Chat 模型，无需额外依赖，适合当前架构
  - 劣势：多消耗一次 LLM 调用，列表过长时可能超出 context window
"""

import json
import re
from typing import List, Optional

from base.logger import logger

# Rerank 专用 system prompt —— 要求 LLM 输出严格的编号排序
_RERANK_SYSTEM_PROMPT = (
    "你是一个文档相关性排序专家。你的任务是根据用户查询与文档片段的相关性，"
    "对候选文档片段从高到低进行排序。\n\n"
    "规则:\n"
    "1. 只依赖文档片段中明确包含的信息判断相关性\n"
    "2. 完全无关的片段排在最后\n"
    "3. 语义相关但信息量少的排在相关但信息量全的后面\n"
    "4. 输出格式必须是严格的 JSON 数组，如 [3, 1, 5, 2, 4]\n"
    "5. 仅输出 JSON 数组，不要包含任何其他文字、说明或 Markdown 格式\n"
    "6. 数组中的数字对应候选文档列表中的编号，按相关性从高到低排列"
)


def _build_rerank_prompt(query: str, chunks: list) -> str:
    """构建 rerank 用户提示词，将 query 与候选 chunks 拼接为编号列表。"""
    lines = [f"用户查询：{query}", "", "候选文档片段（按原始顺序编号）：", ""]
    for i, chunk in enumerate(chunks, 1):
        text = chunk.page_content.strip()
        # 截断过长的单个片段（保留前 500 字符，防 LLM 上下文溢出）
        if len(text) > 500:
            text = text[:500] + "...(截断)"
        lines.append(f"[{i}] {text}")
        lines.append("")
    lines.append("请根据与查询的相关性对这些片段进行排序，输出排序后的编号 JSON 数组：")
    return "\n".join(lines)


class LLMReranker:
    """LLM Listwise Reranker。

    通过向 LLM 发送 query + chunks 列表，让 LLM 输出相关性排序。

    Usage:
        reranker = LLMReranker(client, model="deepseek-v4-flash")
        reranked = reranker.rerank(query, chunks, top_k=10)
    """

    def __init__(self, client, model: str, enable: bool = True):
        """初始化 Reranker。

        Args:
            client: OpenAIClient 实例（必须实现 chat() 方法）
            model: 用于 rerank 的模型名
            enable: 是否启用 rerank（设为 False 时 rerank() 直接返回原列表前 top_k 项）
        """
        self.client = client
        self.model = model
        self.enable = enable
        logger.info(f"LLM Reranker 初始化: model={model}, enable={enable}")

    def rerank(
        self, query: str, chunks: list,
        top_k: Optional[int] = None,
    ) -> list:
        """对检索结果进行 LLM listwise rerank。

        Args:
            query: 用户原始查询
            chunks: 候选 Document 列表
            top_k: 返回前 K 个最相关结果（默认返回全部排序后的结果）

        Returns:
            rerank 后的 Document 列表
        """
        if not self.enable or not chunks or len(chunks) <= 1:
            # 不启用或无需排序时，直接截断返回
            return chunks[:top_k] if top_k else chunks

        # 如果片段太多，先做一次预截断（防止 LLM context 溢出）
        # 取前 60 个候选（超过此值的先丢弃，Rerank 的 token 成本太高）
        candidates = chunks[:60]

        try:
            prompt = _build_rerank_prompt(query, candidates)

            resp = self.client.chat(
                messages=[
                    {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                stream=False,
                temperature=0.1,  # 低温度使输出更稳定
                max_tokens=512,
            )

            # 解析 LLM 输出的排序编号
            ordered_indices = self._parse_ranking(resp)
            if not ordered_indices:
                logger.warning("Rerank 解析失败，回退到原始顺序")
                return chunks[:top_k] if top_k else chunks

            # 按 LLM 输出的顺序重排，并去重
            seen = set()
            reranked = []
            for idx in ordered_indices:
                if 1 <= idx <= len(candidates) and idx - 1 not in seen:
                    reranked.append(candidates[idx - 1])
                    seen.add(idx - 1)

            # 如果有 LLM 遗漏的片段，追加到末尾
            for i, c in enumerate(candidates):
                if i not in seen:
                    reranked.append(c)

            result = reranked[:top_k] if top_k else reranked
            logger.info(
                f"Rerank 完成: {len(candidates)} → {len(result)} 条, "
                f"原始 Top-1={candidates[0].page_content[:40]!r}, "
                f"新 Top-1={result[0].page_content[:40]!r}"
            )
            return result

        except Exception as e:
            logger.error(f"Rerank 过程异常: {e}，回退到原始顺序")
            return chunks[:top_k] if top_k else chunks

    @staticmethod
    def _parse_ranking(response: str) -> List[int]:
        """从 LLM 回复中解析出排序后的编号数组。"""
        text = response.strip()

        # 调试日志：记录原始响应以便分析解析失败原因
        logger.debug(f"Rerank 原始响应: {text[:500]}")

        # 如果文本长度 > 512（max_tokens 限制），可能是 LLM 输出了大量额外内容
        if len(text) > 512:
            logger.warning(f"Rerank 响应异常: {len(text)} 字符 (预期 <512)")
            # 尝试取最后 200 字符（JSON 数组通常在末尾）
            text = text[-200:]

        # 移除可能导致 JSON 解析失败的不可见字符
        text = text.replace(" ", " ").replace("　", " ")

        # 1. 尝试直接作为 JSON 解析
        try:
            data = json.loads(text)
            if isinstance(data, list) and all(isinstance(x, int) for x in data):
                return data
        except json.JSONDecodeError:
            pass

        # 2. 尝试从代码块中提取 JSON（适配 ```json [...] ``` 或 ``` [...] ```）
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, list) and all(isinstance(x, int) for x in data):
                    return data
            except json.JSONDecodeError:
                pass

        # 3. 尝试提取文本中最后的 [...] 数组
        # 使用贪婪匹配找到最后一个 [...]，适配有额外文字的情况
        matches = re.findall(r"\[(\d+(?:[\s,，]+(?:\d+))*)\]", text)
        for m in reversed(matches):  # 从最后一个匹配开始尝试
            try:
                # 支持中文逗号
                parts = re.split(r"[\s,，]+", m.strip())
                data = [int(p) for p in parts if p]
                if data:
                    return data
            except (ValueError, TypeError):
                continue

        # 4. 尝试查找松散的数字序列（JSON 数组但逗号丢失等异常情况）
        nums = re.findall(r"\b(\d+)\b", text)
        if len(nums) > 1:
            try:
                data = [int(n) for n in nums]
                # 简单校验：如果数字都在合理范围内，尝试返回
                if 1 <= min(data) and max(data) <= 100:
                    return data
            except (ValueError, TypeError):
                pass

        # 全部解析失败
        return []
