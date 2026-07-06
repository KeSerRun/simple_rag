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

    # ========================================================================
    # chat() —— 纯文本对话 (不带工具/函数调用)
    # ========================================================================
    # 适用场景:
    #   1. 普通的问答、翻译、总结等不需要调用外部工具的对话
    #   2. workflow_router 在路由判断后, 只要结果为 "normal" 就走此路径
    #   3. Autoplan 内部各节点的独立推理
    # 核心区别:
    #   - chat()             返回类型为 str 或 Generator[str]（纯文本）
    #   - chat_with_tools()  返回类型为 dict 或 Generator[dict]（可能含 tool_calls）
    # ========================================================================
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
            # ---- 非流式 ----
            # 直接调用 SDK 的 chat.completions.create, 等待完整响应返回。
            # 取第一个 choice 的 content 字段, 去头尾空白后返回。
            resp = self.client.chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()
        # ---- 流式 ----
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
        resp = self.client.chat.completions.create(**kwargs)
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    # ========================================================================
    # chat_with_tools() —— 带工具/函数调用的对话
    # ========================================================================
    # 适用场景:
    #   1. RAG 查询流程: 需要模型判断是否调用 retrieval 工具
    #   2. Autoplan 工作流: 模型通过 tool_call 决定下一步执行哪个节点
    #   3. workflow_router 在工作流间的路由选择 (route.md 提示词)
    # 与 chat() 的差异:
    #   - 入参多了 tools (工具定义列表) 和 tool_choice (工具选择策略)
    #   - 返回值为 dict, 包含 "content" (文本回复) 和 "tool_calls" (调用的工具列表)
    #   - tool_calls 列表每个元素含 id / name / arguments 三个字段
    # ========================================================================
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
            # ---- 非流式 ----
            # 完整响应后, 解析 message.tool_calls 列表。
            # 将 SDK 的 ToolCall 对象转为简单 dict, 便于后续 JSON 序列化。
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
        # ---- 流式 ----
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
        accumulated: dict = {}     # 累积工具调用片段, key = index, value = 合并后的 dict
        try:
            for chunk in resp:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # ---- 1. 处理文本增量 ----
                content = getattr(delta, "content", None)
                if content:
                    yield {"type": "content", "text": content}

                # ---- 2. 处理工具调用增量 ----
                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    for i, tcd in enumerate(tc_deltas):
                        # -------------------------------------------------------
                        # 防御性获取 index: getattr(tcd, "index", i)
                        # -------------------------------------------------------
                        # 背景: OpenAI 官方 SDK 的 ToolCallDelta 对象包含 index 字段,
                        #       用于标识该片段属于第几个工具调用。
                        # 问题: 部分第三方兼容接口 (如某些国产模型) 不保证返回 index,
                        #       直接访问 tcd.index 可能抛出 AttributeError。
                        # 做法: 用 getattr 兜底, 若 index 不存在则使用枚举变量 i,
                        #       即当前 delta 在数组中的位置序号。
                        # -------------------------------------------------------
                        idx = getattr(tcd, "index", i)
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

                # ---- 3. finish_reason 提前检测 ----
                # ---------------------------------------------------------------
                # 原理: 当模型决定调用工具时, 最后一个包含工具调用信息的 chunk 的
                #       finish_reason 会变为 "tool_calls"。此时该 chunk 中已经不
                #       再有新的文本或工具增量, 但 accumulated 中已经累积了完整的
                #       工具调用信息。
                # 目的: 及时将累积的工具调用 yield 出去, 避免调用方等到流结束后
                #       才收到工具调用。这对于需要边接收边执行工具的场景至关重要。
                # 兼容性: 部分第三方接口可能在 finish_reason 为 "stop" 或 None
                #         时才结束, 但主流模型在工具调用完成时会准确发送
                #         "tool_calls" 标记。
                # ---------------------------------------------------------------
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason == "tool_calls" and accumulated:
                    yield {"type": "tool_calls", "calls": list(accumulated.values())}
                    accumulated.clear()  # 清空以防后续 finally 块重复 yield

        finally:
            # ---- 4. try...finally 兜底 ----
            # ---------------------------------------------------------------
            # 场景: 部分第三方兼容接口可能不会在流结束前发送 finish_reason 为
            #       "tool_calls" 的 chunk (例如流被截断、网络异常等)。
            # 做法: 在 finally 中检查 accumulated 是否还有未 yield 的残余数据,
            #       若有则确保它们最终能被调用方收到, 防止工具调用丢失。
            # 注意: 如果已经在循环内 yield 并 clear 了, accumulated 为空,
            #       此处的 yield 不会执行, 不会产生重复。
            # ---------------------------------------------------------------
            if accumulated:
                yield {"type": "tool_calls", "calls": list(accumulated.values())}

    # ========================================================================
    # embed() —— 批量文本向量化
    # ========================================================================
    # 用途: 将文本转换为 Embedding 向量, 用于向量数据库 (如 FAISS) 的相似度检索。
    # 设计要点:
    #   - 支持 batch_size 分批, 避免单次请求过大被 API 拒绝。
    #   - 分批逻辑采用朴素的步进切片, 不涉及多线程。
    #   - 每批完成后立即追加到最终结果列表 out 中, 整体保持原有顺序。
    #   - 日志输出每批进度, 便于监控长文本集的嵌入进度。
    # 注意事项:
    #   - texts 参数是 Iterable, 内部先转为 list 以便多次切片; 若传入的是
    #     生成器, 此操作会一次性消费它, 内存占用与总文本量成正比。
    #   - 不同模型对单次请求的文本条数有限制 (如 text-embedding-3-small
    #     支持最多 2048 条), batch_size 默认 32 是保守值。
    # ========================================================================
    def embed(
        self,
        texts: Iterable[str],
        model: str,
        batch_size: int = 32,
    ) -> List[List[float]]:
        texts = list(texts)
        if not texts:
            return []                               # 空输入直接返回空列表
        total = len(texts)
        num_batches = (total + batch_size - 1) // batch_size   # 向上取整计算批数
        out: List[List[float]] = []
        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]                   # 当前批次切片
            batch_idx = i // batch_size + 1
            logger.info(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")
            kwargs = dict(model=model, input=batch)
            resp = self.client.embeddings.create(**kwargs)
            out.extend([d.embedding for d in resp.data])        # 按顺序追加嵌入向量
            logger.info(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")
        return out
