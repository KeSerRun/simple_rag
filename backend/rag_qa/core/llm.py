from typing import Generator, List, Optional, Union

from base.logger import logger

from .openai_client import OpenAIClient


class LLMModel:
    """基于 OpenAI Chat Completion 的 LLM 封装,接口向后兼容旧 transformers 版本"""

    def __init__(self, client: OpenAIClient, model: str, identity: str = ""):
        self.client = client
        self.model = model
        # identity 由 ContextBuilder.identity 注入,可为空字符串
        self.identity = identity
        # 保留 device 字段供老调用者打印日志
        self.device = "openai"

    def _call_llm_model(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.8,
        history: Optional[List[dict]] = None,
        stream: bool = False,
    ) -> Union[str, Generator[str, None, None]]:
        try:
            messages: List[dict] = []
            if self.identity:
                messages.append({"role": "system", "content": self.identity})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            return self.client.chat(
                messages=messages,
                model=self.model,
                stream=stream,
                temperature=temperature,
                max_tokens=max_new_tokens,
            )
        except Exception as e:
            logger.error(f"LLM 模型调用失败: {e}")
            if stream:
                def _err():
                    yield "抱歉，模型处理请求时发生了错误。"
                return _err()
            return "抱歉，模型处理请求时发生了错误。"
