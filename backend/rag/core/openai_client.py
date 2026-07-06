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
        client_name: str = "Chat",
    ):
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
        logger.info(f"{client_name} OpenAI 客户端初始化完成,base_url={base_url or 'https://api.openai.com/v1'}")

    def chat(
        self,
        messages: List[dict],
        model: str,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        kwargs = dict(model=model, messages=messages, temperature=temperature)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
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

    def chat_with_tools(
        self,
        messages: List[dict],
        model: str,
        tools: List[dict],
        tool_choice: str = "auto",
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if not stream:
            resp = self.client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            tool_calls = []
            for tc in (msg.tool_calls or []):
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "",
                })
            return {"content": msg.content or "", "tool_calls": tool_calls}
        kwargs["stream"] = True
        return self._stream_chat_with_tools(kwargs)

    def _stream_chat_with_tools(self, kwargs: dict):
        resp = self.client.chat.completions.create(**kwargs)
        accumulated: dict = {}
        try:
            for chunk in resp:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                content = getattr(delta, "content", None)
                if content:
                    yield {"type": "content", "text": content}

                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    for i, tcd in enumerate(tc_deltas):
                        # 如果没有 index，就使用它在数组中的序号，防止第三方接口崩溃
                        idx = getattr(tcd, "index", i)
                        acc = accumulated.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if getattr(tcd, "id", None):
                            acc["id"] = tcd.id
                        fn = getattr(tcd, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                acc["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                acc["arguments"] += fn.arguments

                # 某些兼容接口会提前在 finish_reason 宣称工具调用完成
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason == "tool_calls" and accumulated:
                    yield {"type": "tool_calls", "calls": list(accumulated.values())}
                    accumulated.clear()  # 防止在最终外层重复 yield

        finally:
            if accumulated:
                yield {"type": "tool_calls", "calls": list(accumulated.values())}

    def embed(
        self,
        texts: Iterable[str],
        model: str,
        batch_size: int = 32,
    ) -> List[List[float]]:
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
            resp = self.client.embeddings.create(**kwargs)
            out.extend([d.embedding for d in resp.data])
            logger.info(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")
        return out
