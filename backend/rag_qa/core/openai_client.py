import os
from typing import Generator, Iterable, List, Optional

from openai import OpenAI

from base.logger import logger


class OpenAIClient:
    """统一封装 OpenAI 同步客户端,供 LLM/Embedding 共用一个实例"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        # 优先环境变量
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "未设置 OPENAI_API_KEY,请设置环境变量或在 config.ini [api] 中配置 api_key"
            )
        self.client = OpenAI(
            api_key=key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.base_url = base_url
        logger.info(f"OpenAI 客户端初始化完成,base_url={base_url or 'https://api.openai.com/v1'}")

    def chat(
        self,
        messages: List[dict],
        model: str,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ):
        """非流式返回 str,流式返回增量 token 的 Generator[str]"""
        kwargs = dict(model=model, messages=messages, temperature=temperature)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if not stream:
            resp = self.client.chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()

        kwargs["stream"] = True
        return self._stream_chat(kwargs)

    def _stream_chat(self, kwargs: dict) -> Generator[str, None, None]:
        resp = self.client.chat.completions.create(**kwargs)
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    def embed(
        self,
        texts: Iterable[str],
        model: str,
        batch_size: int = 32,
        dimensions: Optional[int] = None,
    ) -> List[List[float]]:
        """批量嵌入,内部分批以避免单请求超限

        batch_size 默认 32,兼容 SiliconFlow 等服务商单次 ≤32 条 input 的限制。
        dimensions 仅 OpenAI text-embedding-3 系列支持,其它服务商(SiliconFlow/BGE 等)
        传入会被拒绝(参数无效),所以默认不传。
        """
        texts = list(texts)
        if not texts:
            return []
        total = len(texts)
        num_batches = (total + batch_size - 1) // batch_size
        out: List[List[float]] = []
        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]
            batch_idx = i // batch_size + 1
            logger.info(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")
            kwargs = dict(model=model, input=batch)
            if dimensions is not None:
                kwargs["dimensions"] = dimensions
            resp = self.client.embeddings.create(**kwargs)
            out.extend([d.embedding for d in resp.data])
            logger.info(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")
        return out
