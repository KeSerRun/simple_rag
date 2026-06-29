from base.logger import logger

from .context_builder import ContextBuilder
from .openai_client import OpenAIClient

STRATEGIES = ["直接检索", "假设问题检索", "子查询检索", "回溯问题检索"]


class StrategySelector:
    """基于 LLM 的检索策略选择器,prompt 由 ContextBuilder 加载"""

    def __init__(
        self,
        client: OpenAIClient,
        model: str,
        context_builder: ContextBuilder,
        device: str = "openai",
    ):
        self.client = client
        self.model = model
        self.context_builder = context_builder
        self.device = device

    def select_strategy(self, query: str) -> str:
        messages = self.context_builder.build_messages("strategy_selector", query=query)
        try:
            strategy = self.client.chat(
                messages=messages,
                model=self.model,
                stream=False,
                temperature=0.1,
                max_tokens=16,
            )
        except Exception as e:
            logger.error(f"策略选择调用失败: {e},默认使用直接检索")
            return "直接检索"

        strategy = (strategy or "").strip()
        if strategy in STRATEGIES:
            return strategy
        for s in STRATEGIES:
            if s in strategy:
                return s
        logger.warning(f"策略选择器返回了非预期的响应: {strategy!r}，默认使用直接检索策略")
        return "直接检索"
