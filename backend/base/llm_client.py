
import os
# Iterable  —— 可迭代对象类型（如列表、生成器等）
# List      —— 列表类型
from typing import Generator, Iterable, List, Optional



# 从 openai 库导入 OpenAI 类，用于创建与 OpenAI API 兼容的客户端
# 支持官方 OpenAI 以及兼容 OpenAI 接口的第三方服务（如 Azure、智谱、DeepSeek 等）
from openai import OpenAI



# 从 base.logger 导入自定义的 logger 日志工具，用于记录程序运行信息
from base.logger import logger
# 从 base.config 导入全局配置对象，用于读取 retrieval_top_k 等配置项
from base.config import conf


# OpenAIClient 类 —— 统一封装 OpenAI 同步客户端
# 这个类是整个项目中所有与 LLM（大语言模型）和 Embedding（文本向量化）

class OpenAIClient:
    """统一封装 OpenAI 同步客户端,供 LLM/Embedding 共用一个实例"""

    # __init__() —— 构造函数，初始化 OpenAI 客户端
    #   api_key      —— OpenAI API 密钥，可以不传，不传时自动从环境变量读取
    #   base_url     —— API 入口地址，兼容第三方服务（如 Azure、智谱等）
    #   timeout      —— 请求超时时间，单位秒，默认 60 秒
    #   max_retries  —— 请求失败时自动重试次数，默认 3 次

    def __init__(
        self,
        api_key: Optional[str] = None,          # API 密钥，可选，不传则从环境变量读
        base_url: Optional[str] = None,         # API 入口地址，可选，不传则用 OpenAI 官方地址
        timeout: float = 60.0,                  # 超时秒数，默认 60 秒
        max_retries: int = 3,                   # 失败重试次数，默认 3 次
        client_name: str = "Chat",              # 客户端名字，仅用于日志
    ):
        """
        初始化 OpenAI 客户端。
        ---
        参数说明:
          - api_key:    可显式传入; 为 None 时自动读取环境变量 OPENAI_API_KEY
          - base_url:   兼容第三方 API（例如 Azure、智谱、DeepSeek 等）的入口地址;
                        为 None 则使用 openai 官方默认值 https://api.openai.com/v1
          - timeout:    请求超时秒数, 默认 60s
          - max_retries: 失败自动重试次数, 默认 3 次
          - client_name: 仅用于日志标识, 不参与业务逻辑
        ---
        设计考量:
          整个项目共享同一个 OpenAI 客户端实例, 避免重复创建连接池。
        """

        # 如果传入了 api_key 就用传入的，否则从环境变量 OPENAI_API_KEY 读取
        # 如果两个都没有，key 的值就是 None
        key = api_key or os.environ.get("OPENAI_API_KEY")

        # 检查 key 是否为空
        if not key:
            raise RuntimeError(
                "未设置 OPENAI_API_KEY,请设置环境变量或在 config.ini [api] 中配置 api_key"
            )

        self.client = OpenAI(
            api_key=key,                        # 传入 API 密钥
            base_url=base_url or None,          # 传入 API 地址，如果 base_url 为 None 则用官方默认
            timeout=timeout,                    # 传入超时时间
            max_retries=max_retries,            # 传入重试次数
        )

        # 保存 base_url 到实例属性，方便其他地方查看当前使用的是哪个 API 地址
        self.base_url = base_url

        logger.debug(f"{client_name} OpenAI 客户端初始化完成,base_url={base_url or 'https://api.openai.com/v1'}")

    # 错误分类与重试

    @staticmethod
    def classify_error(e: Exception) -> str:
        """将 API 错误分类为用户友好的消息。"""
        msg = str(e)
        if "402" in msg or "Insufficient Balance" in msg or "insufficient_balance" in msg:
            return "API 余额不足，请检查账户余额或更换 API Key。"
        if "401" in msg or "Unauthorized" in msg or "invalid_api_key" in msg:
            return "API Key 无效，请在配置中检查 API Key。"
        if "429" in msg or "Rate limit" in msg or "rate_limit" in msg:
            return "API 请求频率过高，请稍后重试。"
        if "500" in msg or "502" in msg or "503" in msg or "server_error" in msg:
            return "API 服务暂时不可用，请稍后重试。"
        if "timeout" in msg.lower():
            return "API 请求超时，请检查网络连接。"
        if "model" in msg.lower() and "not found" in msg.lower():
            return f"模型不存在或不可用，请检查模型名称配置。"
        return f"LLM 调用失败: {e}"

    def chat_with_retry(self, **kwargs):
        """带重试和错误分类的 chat 调用。

        自动重试 429 和 5xx 错误最多 2 次。
        """
        from time import sleep
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                return self.chat(**kwargs)
            except Exception as e:
                cls = self.classify_error(e)
                last_error = cls
                # 只有 429/5xx 才重试
                msg = str(e)
                if "429" in msg or "500" in msg or "502" in msg or "503" in msg:
                    if attempt < max_attempts - 1:
                        wait = 2 ** attempt
                        logger.warning(f"API 错误, {wait}秒后重试 ({attempt+1}/{max_attempts}): {cls}")
                        sleep(wait)
                        continue
                return f"({cls})"
        return f"({last_error})"

    # chat() —— 纯文本对话（不带工具/函数调用）
    # 适用场景:
    #   1. 普通的问答、翻译、总结等不需要调用外部工具的对话
    #   2. workflow_router 在路由判断后, 只要结果为 "normal" 就走此路径
    #   3. Autoplan 内部各节点的独立推理
    # 核心区别:
    #   - chat()             返回类型为 str 或 Generator[str]（纯文本）
    #   - chat_with_tools()  返回类型为 dict 或 Generator[dict]（可能含 tool_calls）

    def chat(
        self,
        messages: List[dict],          # 对话消息列表，格式为 [{"role": "user", "content": "你好"}]
        model: str,                    # 使用的模型名称，如 "gpt-4"、"deepseek-v4-flash"
        stream: bool = False,          # 是否启用流式输出，默认关闭
        temperature: float = 0.7,      # 模型输出的随机性（0~2），值越大回答越有创意
        max_tokens: Optional[int] = None,  # 最大输出 token 数，不传则模型自己决定
        reasoning_effort: Optional[str] = None,  # 推理努力程度（某些模型支持），不传则不用
    ):
        kwargs = dict(model=model, messages=messages, temperature=temperature)

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        if not stream:
            # 直接调用 SDK 的 chat.completions.create, 等待完整响应返回。

            resp = self.client.chat.completions.create(**kwargs)

            # 如果 content 为 None，就用空字符串代替
            content = resp.choices[0].message.content or ""

            if not content.strip():
                logger.debug(f"LLM 返回空内容 model={model} finish_reason={resp.choices[0].finish_reason}")

            return content.strip()

        # kwargs 中加入 stream=True, 交给 _stream_chat 生成器逐 chunk 产出文本片段。

        kwargs["stream"] = True

        return self._stream_chat(kwargs)

    def _stream_chat(self, kwargs: dict) -> Generator[str, None, None]:
        """
        流式聊天生成器 —— 逐 chunk 产出文本内容 (str)。
        ---
        工作原理:
          1. 发起流式请求, SDK 返回一个迭代器 resp, 每次迭代得到一个 chunk。
          2. 每个 chunk 可能包含 0 个或多个 choices; 空 choices 的 chunk 跳过。
          3. 每个 choice 的 delta 字段携带增量文本 (content)。
          4. 使用 getattr 安全获取 content, 避免某些第三方接口缺失该字段时报 AttributeError。
          5. 非 None 的 content 直接 yield 给调用方逐段输出。
        ---
        与 _stream_chat_with_tools 的差异:
          - 本方法只 yield str, 不处理 tool_calls。
          - 外层不包裹 try...finally, 因为没有需要清理的累积状态。
        """

        # 发起流式请求，返回一个可迭代的 resp，每次迭代得到一个新的 chunk（数据块）
        resp = self.client.chat.completions.create(**kwargs)

        for chunk in resp:
            # 如果这个 chunk 没有 choices（选择结果），说明是空数据块，直接跳过
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 安全地获取 content 字段（用 getattr 避免某些 API 缺少该字段时报错）
            content = getattr(delta, "content", None)

            if content:
                yield content

    # chat_with_tools() —— 带工具/函数调用的对话
    # 适用场景:
    #   1. RAG 查询流程: 需要模型判断是否调用 retrieval 工具
    #   2. Autoplan 工作流: 模型通过 tool_call 决定下一步执行哪个节点
    #   3. workflow_router 在工作流间的路由选择 (route.md 提示词)
    # 与 chat() 的差异:
    #   - 入参多了 tools (工具定义列表) 和 tool_choice (工具选择策略)
    #   - 返回值为 dict, 包含 "content" (文本回复) 和 "tool_calls" (调用的工具列表)
    #   - tool_calls 列表每个元素含 id / name / arguments 三个字段

    def chat_with_tools(
        self,
        messages: List[dict],          # 对话消息列表
        model: str,                    # 模型名称
        tools: List[dict],             # 工具定义列表，描述模型可以调用哪些函数
        tool_choice: str = "auto",     # 工具选择策略："auto" 让模型自己决定，"none" 禁止调用，"required" 强制调用
        stream: bool = False,          # 是否启用流式输出
        temperature: float = 0.7,      # 输出随机性
        max_tokens: Optional[int] = None,  # 最大输出 token 数
        reasoning_effort: Optional[str] = None,  # 推理努力程度
    ):
        kwargs = dict(
            model=model,                        # 模型名称
            messages=messages,                  # 对话消息
            temperature=temperature,            # 输出随机性
        )

        if tools:
            kwargs["tools"] = tools             # 工具定义列表
            kwargs["tool_choice"] = tool_choice  # 工具选择策略

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # 如果不需要流式输出，走非流式分支
        if not stream:
            # 完整响应后, 解析 message.tool_calls 列表。
            # 将 SDK 的 ToolCall 对象转为简单 dict, 便于后续 JSON 序列化。

            resp = self.client.chat.completions.create(**kwargs)

            msg = resp.choices[0].message

            tool_calls = []

            # 遍历消息中的 tool_calls（可能为 None，所以用 or [] 兜底）
            for tc in (msg.tool_calls or []):
                tool_calls.append({
                    "id": tc.id,                          # 工具调用 ID，用于关联后续结果
                    "name": tc.function.name,             # 工具（函数）名称
                    "arguments": tc.function.arguments or "",  # 工具调用的参数（JSON 字符串）
                })

            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning is None:
                extra = getattr(msg, "model_extra", None) or {}
                reasoning = extra.get("reasoning_content")
            return {
                "content": msg.content or "",
                "reasoning_content": reasoning,
                "tool_calls": tool_calls,
                "finish_reason": resp.choices[0].finish_reason or "stop",
            }

        kwargs["stream"] = True

        return self._stream_chat_with_tools(kwargs)

    def _stream_chat_with_tools(self, kwargs: dict):
        """
        流式对话 + 工具调用生成器 —— 逐 chunk 产出内容文本或工具调用结果。
        ---
        产出格式 (dict):
          - 文本片段:  {"type": "content", "text": "..."}
          - 工具调用:  {"type": "tool_calls", "calls": [...]}
        调用方 (如 rag_system.py 或 workflow_router.py) 根据 type 字段分流处理。
        ---
        流式 tool_calls 的合并原理:
          由于工具调用在流式响应中是分多个 chunk 逐步到达的, 同一个工具调用的
          name 和 arguments 可能横跨多个 chunk。因此需要一个累积结构来暂存:
            accumulated: dict[int, {"id": str, "name": str, "arguments": str}]
          其中 key 是工具调用的 index (或位置序号), value 是逐步拼接的结果。
          当调用方遍历生成器时, 只要遇到 {"type": "tool_calls", "calls": [...]},
          即可将 calls 列表直接作为工具调用执行。
        """

        resp = self.client.chat.completions.create(**kwargs)

        # 结构：{index: {"id": "", "name": "", "arguments": ""}}
        # key 是工具调用的序号，value 是逐步拼接起来的完整调用信息
        accumulated: dict = {}
        finish_reason: str | None = None  # 记录最终的 finish_reason

        try:
            for chunk in resp:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]

                delta = choice.delta

                content = getattr(delta, "content", None)
                if content:
                    # 如果有文本内容，以 {"type": "content", "text": "..."} 的格式产出
                    yield {"type": "content", "text": content}

                # DeepSeek R1 / QwQ / Gemini 等模型的思考链通过 SSE 原始 JSON 的
                # choices[0].delta.reasoning_content 字段返回，但 OpenAI SDK 的
                # ChoiceDelta 对象不解析该字段（非标准字段存于 model_extra）。
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning is None:
                    extra = getattr(delta, "model_extra", None) or {}
                    reasoning = extra.get("reasoning_content")
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}

                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    for i, tcd in enumerate(tc_deltas):
                        # 背景: OpenAI 官方 SDK 的 ToolCallDelta 对象包含 index 字段,
                        #       直接访问 tcd.index 可能抛出 AttributeError。
                        # 做法: 用 getattr 兜底, 若 index 不存在则使用枚举变量 i,

                        idx = getattr(tcd, "index", i)

                        # setdefault 方法：如果 idx 已存在则返回已有的值，否则插入新值并返回
                        acc = accumulated.setdefault(idx, {"id": "", "name": "", "arguments": ""})

                        # id 只在首个携带该工具调用的 chunk 中出现, 后续 chunk 为 None
                        if getattr(tcd, "id", None):
                            acc["id"] = tcd.id

                        fn = getattr(tcd, "function", None)
                        if fn is not None:
                            # name 同样只在首个 chunk 中出现
                            if getattr(fn, "name", None):
                                acc["name"] = fn.name
                            # arguments 是字符串片段, 需要逐 chunk 追加拼接
                            if getattr(fn, "arguments", None):
                                acc["arguments"] += fn.arguments

                #       finish_reason 会变为 "tool_calls"。此时该 chunk 中已经不
                #       再有新的文本或工具增量, 但 accumulated 中已经累积了完整的
                #       工具调用信息。
                # 目的: 及时将累积的工具调用 yield 出去, 避免调用方等到流结束后
                # 兼容性: 部分第三方接口可能在 finish_reason 为 "stop" 或 None
                #         时才结束, 但主流模型在工具调用完成时会准确发送
                #         "tool_calls" 标记。

                finish_reason = getattr(choice, "finish_reason", None)

                # 如果结束原因是 "tool_calls"（模型决定调用工具）并且有累积数据
                if finish_reason == "tool_calls" and accumulated:
                    # 将累积的工具调用列表以标准格式 yield 出去
                    yield {"type": "tool_calls", "calls": list(accumulated.values())}
                    # 清空累积数据，防止 finally 中重复 yield
                    accumulated.clear()

        finally:
            # 场景: 部分第三方兼容接口可能不会在流结束前发送 finish_reason 为
            #       "tool_calls" 的 chunk (例如流被截断、网络异常等)。
            # 做法: 在 finally 中检查 accumulated 是否还有未 yield 的残余数据,
            #       若有则确保它们最终能被调用方收到, 防止工具调用丢失。
            # 注意: 如果已经在循环内 yield 并 clear 了, accumulated 为空,
            #       此处的 yield 不会执行, 不会产生重复。

            if accumulated:
                # 如果有残余数据，确保它们被 yield 出去
                yield {"type": "tool_calls", "calls": list(accumulated.values())}

            # 产出 finish_reason 事件，供调用方做续写等处理
            if finish_reason:
                yield {"type": "finish", "reason": finish_reason}

    # embed() —— 批量文本向量化
    # 用途: 将文本转换为 Embedding 向量, 用于向量数据库 (如 FAISS) 的相似度检索。
    # 设计要点:
    #   - 支持 batch_size 分批, 避免单次请求过大被 API 拒绝。
    #   - 分批逻辑采用朴素的步进切片, 不涉及多线程。
    #   - 日志输出每批进度, 便于监控长文本集的嵌入进度。
    #   - texts 参数是 Iterable, 内部先转为 list 以便多次切片; 若传入的是
    #     生成器, 此操作会一次性消费它, 内存占用与总文本量成正比。
    #   - 不同模型对单次请求的文本条数有限制 (如 text-embedding-3-small
    #     支持最多 2048 条), batch_size 默认 32 是保守值。

    def embed(
        self,
        texts: Iterable[str],          # 待向量化的文本列表（可以是列表、生成器等可迭代对象）
        model: str,                    # 向量化模型名称，如 "text-embedding-3-small"
        batch_size: int = 32,          # 每批处理的文本数量，默认 32 条
    ) -> List[List[float]]:            # 返回一个列表，每个元素是一个浮点数向量
        # 将传入的可迭代文本转为列表（因为后续需要多次切片操作）
        texts = list(texts)

        if not texts:
            return []

        total = len(texts)

        # 计算需要分多少批处理：向上取整（例如 50 条文本，每批 32，需要 2 批）
        num_batches = (total + batch_size - 1) // batch_size

        out: List[List[float]] = []

        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]

            # 计算当前批次是第几批（从 1 开始，方便日志展示）
            batch_idx = i // batch_size + 1

            logger.debug(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")

            kwargs = dict(model=model, input=batch)

            # 使用 try...except 捕获 API 请求异常
            try:
                # 调用 OpenAI 的 embeddings.create API，获取文本向量
                resp = self.client.embeddings.create(**kwargs)

                # resp.data 是一个列表，每个元素有 .embedding 属性，就是向量
                out.extend([d.embedding for d in resp.data])

                # 记录日志：当前批次嵌入完成
                logger.debug(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")

            except Exception as e:
                # 如果嵌入失败，记录错误日志
                logger.error(f"嵌入失败 {batch_idx}/{num_batches}: {e}")

                # 向上层抛出异常，让调用方决定如何处理（是重试还是放弃）
                raise

        return out