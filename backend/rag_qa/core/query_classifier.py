from typing import List

from base.logger import logger

from .context_builder import ContextBuilder
from .openai_client import OpenAIClient


class QueryClassifier:
    """基于 LLM 的意图分类器,prompt 由 ContextBuilder 加载

    向后兼容:`.predict(query) -> str` 接口不变。
    """

    def __init__(
        self,
        client: OpenAIClient,
        model: str,
        label_list: List[str],
        context_builder: ContextBuilder,
        device: str = "openai",
    ):
        if not label_list or len(label_list) < 2:
            raise ValueError("label_list 至少需要两个标签 (需要/不需要)")
        self.client = client
        self.model = model
        self.label_list = label_list
        self.context_builder = context_builder
        self.device = device

    def predict(self, query: str) -> str:
        messages = self.context_builder.build_messages(
            "query_classifier",
            needed=self.label_list[0],
            generic=self.label_list[1],
            query=query,
        )
        try:
            resp = self.client.chat(
                messages=messages,
                model=self.model,
                stream=False,
                temperature=0.0,
                max_tokens=8,
            )
        except Exception as e:
            logger.error(f"意图分类调用失败: {e},回退为默认需要检索")
            return self.label_list[0]

        text = (resp or "").strip().replace("。", "").replace(".", "")
        for label in self.label_list:
            if text == label:
                return label
        for label in self.label_list:
            if label in text:
                return label
        logger.warning(f"意图分类返回无法解析的内容: {resp!r},默认按需要检索处理")
        return self.label_list[0]
