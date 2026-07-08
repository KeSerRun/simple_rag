# ========================================================================
# 导入标准库模块
# ========================================================================

# 导入 os 模块，用于读取环境变量（如 OPENAI_API_KEY）
import os
# 从 typing 模块导入类型注解工具：
# Generator —— 生成器类型，用于流式返回数据
# Iterable  —— 可迭代对象类型（如列表、生成器等）
# List      —— 列表类型
# Optional  —— 可选类型，表示参数可以传 None
from typing import Generator, Iterable, List, Optional


# ========================================================================
# 导入第三方依赖：OpenAI Python SDK
# ========================================================================

# 从 openai 库导入 OpenAI 类，用于创建与 OpenAI API 兼容的客户端
# 支持官方 OpenAI 以及兼容 OpenAI 接口的第三方服务（如 Azure、智谱、DeepSeek 等）
from openai import OpenAI


# ========================================================================
# 导入项目内部模块
# ========================================================================

# 从 base.logger 导入自定义的 logger 日志工具，用于记录程序运行信息
from base.logger import logger


# ========================================================================
# OpenAIClient 类 —— 统一封装 OpenAI 同步客户端
# ========================================================================
# 这个类是整个项目中所有与 LLM（大语言模型）和 Embedding（文本向量化）
# 交互的唯一入口。整个项目共享同一个实例，避免重复创建连接池。
# ========================================================================

class OpenAIClient:
    """统一封装 OpenAI 同步客户端,供 LLM/Embedding 共用一个实例"""

    # --------------------------------------------------------------------
    # __init__() —— 构造函数，初始化 OpenAI 客户端
    # --------------------------------------------------------------------
    # 参数说明：
    #   api_key      —— OpenAI API 密钥，可以不传，不传时自动从环境变量读取
    #   base_url     —— API 入口地址，兼容第三方服务（如 Azure、智谱等）
    #   timeout      —— 请求超时时间，单位秒，默认 60 秒
    #   max_retries  —— 请求失败时自动重试次数，默认 3 次
    #   client_name  —— 仅用于日志中标识客户端名称，不参与业务逻辑
    # --------------------------------------------------------------------

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
            # 如果 key 为空，说明没有配置 API 密钥，直接报错并给出提示
            raise RuntimeError(
                "未设置 OPENAI_API_KEY,请设置环境变量或在 config.ini [api] 中配置 api_key"
            )

        # 使用获取到的 key 和其他参数创建 OpenAI 客户端实例
        # 这个 client 对象是真正的 SDK 客户端，后续的聊天、嵌入都通过它完成
        self.client = OpenAI(
            api_key=key,                        # 传入 API 密钥
            base_url=base_url or None,          # 传入 API 地址，如果 base_url 为 None 则用官方默认
            timeout=timeout,                    # 传入超时时间
            max_retries=max_retries,            # 传入重试次数
        )

        # 保存 base_url 到实例属性，方便其他地方查看当前使用的是哪个 API 地址
        self.base_url = base_url

        # 记录日志，说明 OpenAI 客户端初始化成功，并打印当前使用的 API 地址
        logger.info(f"{client_name} OpenAI 客户端初始化完成,base_url={base_url or 'https://api.openai.com/v1'}")

    # ========================================================================
    # chat() —— 纯文本对话（不带工具/函数调用）
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
        messages: List[dict],          # 对话消息列表，格式为 [{"role": "user", "content": "你好"}]
        model: str,                    # 使用的模型名称，如 "gpt-4"、"deepseek-v4-flash"
        stream: bool = False,          # 是否启用流式输出，默认关闭
        temperature: float = 0.7,      # 模型输出的随机性（0~2），值越大回答越有创意
        max_tokens: Optional[int] = None,  # 最大输出 token 数，不传则模型自己决定
        reasoning_effort: Optional[str] = None,  # 推理努力程度（某些模型支持），不传则不用
    ):
        # 构建请求参数字典，包含模型、消息和温度这三个必填参数
        kwargs = dict(model=model, messages=messages, temperature=temperature)

        # 如果传入了 max_tokens，就加入到请求参数中
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # 如果传入了 reasoning_effort，就加入到请求参数中
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        # 如果不需要流式输出（stream=False），走这个分支
        if not stream:
            # ---- 非流式 ----
            # 直接调用 SDK 的 chat.completions.create, 等待完整响应返回。
            # 取第一个 choice 的 content 字段, 去头尾空白后返回。

            # 调用 OpenAI API 发送聊天请求，等待完整的响应返回
            resp = self.client.chat.completions.create(**kwargs)

            # 从响应中提取第一个选择（choice）的消息内容
            # 如果 content 为 None，就用空字符串代替
            content = resp.choices[0].message.content or ""

            # 调试：记录 API 原始响应（用于排查 Rerank 等场景返回空的问题）
            if not content.strip():
                logger.debug(f"LLM 返回空内容 model={model} finish_reason={resp.choices[0].finish_reason}")

            # 去掉首尾空白字符后返回文本内容
            return content.strip()

        # ---- 流式 ----
        # kwargs 中加入 stream=True, 交给 _stream_chat 生成器逐 chunk 产出文本片段。

        # 在请求参数中加入流式标志，告诉 API 我们要流式返回
        kwargs["stream"] = True

        # 调用内部的流式处理方法，返回一个生成器，调用方可以逐段获取文本
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

        # 遍历每一个返回的 chunk
        for chunk in resp:
            # 如果这个 chunk 没有 choices（选择结果），说明是空数据块，直接跳过
            if not chunk.choices:
                continue

            # 获取第一个选择的 delta（增量数据），里面包含模型新生成的内容
            delta = chunk.choices[0].delta

            # 安全地获取 content 字段（用 getattr 避免某些 API 缺少该字段时报错）
            content = getattr(delta, "content", None)

            # 如果 content 不为空，就把这段文本 yield（产出）给调用方
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
        messages: List[dict],          # 对话消息列表
        model: str,                    # 模型名称
        tools: List[dict],             # 工具定义列表，描述模型可以调用哪些函数
        tool_choice: str = "auto",     # 工具选择策略："auto" 让模型自己决定，"none" 禁止调用，"required" 强制调用
        stream: bool = False,          # 是否启用流式输出
        temperature: float = 0.7,      # 输出随机性
        max_tokens: Optional[int] = None,  # 最大输出 token 数
        reasoning_effort: Optional[str] = None,  # 推理努力程度
    ):
        # 构建基础请求参数字典
        kwargs = dict(
            model=model,                        # 模型名称
            messages=messages,                  # 对话消息
            temperature=temperature,            # 输出随机性
        )

        # 如果传入了工具定义列表，就把工具信息加到请求参数中
        if tools:
            kwargs["tools"] = tools             # 工具定义列表
            kwargs["tool_choice"] = tool_choice  # 工具选择策略

        # 如果传入了 reasoning_effort，加入请求参数
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        # 如果传入了 max_tokens，加入请求参数
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # 如果不需要流式输出，走非流式分支
        if not stream:
            # ---- 非流式 ----
            # 完整响应后, 解析 message.tool_calls 列表。
            # 将 SDK 的 ToolCall 对象转为简单 dict, 便于后续 JSON 序列化。

            # 调用 OpenAI API 发送聊天请求（包含工具定义），等待完整响应
            resp = self.client.chat.completions.create(**kwargs)

            # 从响应中获取第一个选择的完整消息对象
            msg = resp.choices[0].message

            # 初始化空列表，用于存放解析后的工具调用信息
            tool_calls = []

            # 遍历消息中的 tool_calls（可能为 None，所以用 or [] 兜底）
            for tc in (msg.tool_calls or []):
                # 将 SDK 返回的 ToolCall 对象转为简单的字典，方便后续处理
                tool_calls.append({
                    "id": tc.id,                          # 工具调用 ID，用于关联后续结果
                    "name": tc.function.name,             # 工具（函数）名称
                    "arguments": tc.function.arguments or "",  # 工具调用的参数（JSON 字符串）
                })

            # 返回包含文本内容和工具调用列表的字典
            return {"content": msg.content or "", "tool_calls": tool_calls}

        # ---- 流式 ----
        # 在请求参数中加入流式标志
        kwargs["stream"] = True

        # 调用流式工具调用处理方法，返回生成器
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

        # 发起流式聊天请求（包含工具定义），返回一个可迭代的流式响应
        resp = self.client.chat.completions.create(**kwargs)

        # accumulated 用于暂存流式过程中逐步到达的工具调用片段
        # 结构：{index: {"id": "", "name": "", "arguments": ""}}
        # key 是工具调用的序号，value 是逐步拼接起来的完整调用信息
        accumulated: dict = {}

        # 使用 try...finally 确保即使发生异常也能处理已累积的数据
        try:
            # 遍历每一个流式 chunk
            for chunk in resp:
                # 如果这个 chunk 没有 choices，跳过
                if not chunk.choices:
                    continue

                # 获取当前 chunk 的第一个选择
                choice = chunk.choices[0]

                # 获取增量数据 delta，里面包含新生成的内容
                delta = choice.delta

                # ---- 1. 处理文本增量 ----
                # 安全地获取 delta 中的 content 字段（文本内容）
                content = getattr(delta, "content", None)
                if content:
                    # 如果有文本内容，以 {"type": "content", "text": "..."} 的格式产出
                    yield {"type": "content", "text": content}

                # ---- 2. 处理工具调用增量 ----
                # 安全地获取 delta 中的 tool_calls 字段（工具调用增量）
                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    # 遍历这一批工具调用增量（可能同时有多个工具调用在流式返回）
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

                        # 获取当前工具调用增量的 index（序号），如果不存在则用 i 代替
                        idx = getattr(tcd, "index", i)

                        # 从 accumulated 中获取或创建一个累积条目
                        # setdefault 方法：如果 idx 已存在则返回已有的值，否则插入新值并返回
                        acc = accumulated.setdefault(idx, {"id": "", "name": "", "arguments": ""})

                        # id 只在首个携带该工具调用的 chunk 中出现, 后续 chunk 为 None
                        # 安全地获取 id 字段，如果不为空则保存
                        if getattr(tcd, "id", None):
                            acc["id"] = tcd.id

                        # 获取工具调用的 function（函数）信息
                        fn = getattr(tcd, "function", None)
                        if fn is not None:
                            # name 同样只在首个 chunk 中出现
                            # 安全地获取函数名称，如果不为空则保存
                            if getattr(fn, "name", None):
                                acc["name"] = fn.name
                            # arguments 是字符串片段, 需要逐 chunk 追加拼接
                            # 安全地获取参数片段，如果不为空则追加到已有参数的后面
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

                # 获取当前 choice 的 finish_reason（结束原因）
                finish_reason = getattr(choice, "finish_reason", None)

                # 如果结束原因是 "tool_calls"（模型决定调用工具）并且有累积数据
                if finish_reason == "tool_calls" and accumulated:
                    # 将累积的工具调用列表以标准格式 yield 出去
                    yield {"type": "tool_calls", "calls": list(accumulated.values())}
                    # 清空累积数据，防止 finally 中重复 yield
                    accumulated.clear()

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

            # 检查是否还有未产出的残余工具调用数据
            if accumulated:
                # 如果有残余数据，确保它们被 yield 出去
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
        texts: Iterable[str],          # 待向量化的文本列表（可以是列表、生成器等可迭代对象）
        model: str,                    # 向量化模型名称，如 "text-embedding-3-small"
        batch_size: int = 32,          # 每批处理的文本数量，默认 32 条
    ) -> List[List[float]]:            # 返回一个列表，每个元素是一个浮点数向量
        # 将传入的可迭代文本转为列表（因为后续需要多次切片操作）
        texts = list(texts)

        # 如果文本列表为空，直接返回空列表，避免无意义的 API 调用
        if not texts:
            return []

        # 获取文本总条数
        total = len(texts)

        # 计算需要分多少批处理：向上取整（例如 50 条文本，每批 32，需要 2 批）
        num_batches = (total + batch_size - 1) // batch_size

        # 初始化输出列表，用于存放所有文本的向量
        out: List[List[float]] = []

        # 按步长 batch_size 遍历，每次取一个批次
        for i in range(0, total, batch_size):
            # 切片获取当前批次要处理的文本
            batch = texts[i : i + batch_size]

            # 计算当前批次是第几批（从 1 开始，方便日志展示）
            batch_idx = i // batch_size + 1

            # 记录日志：即将发送嵌入请求
            logger.info(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")

            # 构建请求参数字典：模型和输入文本列表
            kwargs = dict(model=model, input=batch)

            # 使用 try...except 捕获 API 请求异常
            try:
                # 调用 OpenAI 的 embeddings.create API，获取文本向量
                resp = self.client.embeddings.create(**kwargs)

                # 将 API 返回的每个文本的向量按顺序追加到输出列表
                # resp.data 是一个列表，每个元素有 .embedding 属性，就是向量
                out.extend([d.embedding for d in resp.data])

                # 记录日志：当前批次嵌入完成
                logger.info(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")

            except Exception as e:
                # 如果嵌入失败，记录错误日志
                logger.error(f"嵌入失败 {batch_idx}/{num_batches}: {e}")

                # 向上层抛出异常，让调用方决定如何处理（是重试还是放弃）
                raise

        # 返回所有文本的向量列表
        return out


# ========================================================================
# LLM Listwise Reranker —— 通过大模型对检索结果进行重排序
# ========================================================================
# 工作原理:
#   1. 向量检索（FAISS）先召回 N 个候选 chunk（通常比最终需要的多，如 Top-30）
#   2. 将 query + 所有候选 chunk 发送给 LLM
#   3. LLM 根据相关性对 chunk 进行排序，输出排序后的编号列表
#   4. 按照 LLM 输出的顺序重新排列 chunk，取前 K 个
#
# 与 Cross-Encoder Rerank 的区别:
#   - Cross-Encoder: 需要专门的重排模型（如 bge-reranker-v2-m3），单次推理极快
#   - LLM Listwise: 利用已接入的 Chat 模型，无需额外依赖，适合当前架构
#   - 劣势：多消耗一次 LLM 调用，列表过长时可能超出 context window
# ========================================================================

# 导入 json 模块，用于解析 LLM 返回的 JSON 格式排序结果
import json
# 导入 re 模块，用于正则表达式提取排序编号（当 LLM 输出不标准时做兜底解析）
import re
# 再次从 typing 导入（虽然是重复导入，但 Python 不会报错），方便独立阅读
from typing import List, Optional

# 导入项目内部的 logger 日志工具
from base.logger import logger

# ========================================================================
# Rerank 专用 system prompt —— 要求 LLM 输出严格的编号排序
# ========================================================================
# 这段 prompt 告诉 LLM 它的角色是"文档相关性排序专家"，
# 要求它根据用户查询与文档片段的相关性进行排序，
# 并且强制要求输出严格的 JSON 数组格式。
# ========================================================================

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
    """
    构建 rerank 用户提示词，将 query 与候选 chunks 拼接为编号列表。

    这个函数把用户的问题和所有候选文档片段组装成一个格式化的提示词，
    每个片段前面带有编号 [1], [2], [3]...，方便 LLM 在输出排序结果时引用这些编号。

    参数:
        query: 用户的原始查询问题
        chunks: 候选文档片段列表（Document 对象列表）

    返回:
        组装好的提示词字符串
    """

    # 创建一个列表，用于按行构建提示词文本
    lines = [f"用户查询：{query}", "", "候选文档片段（按原始顺序编号）：", ""]

    # 遍历所有候选文档片段（从 1 开始编号）
    for i, chunk in enumerate(chunks, 1):
        # 获取文档片段的文本内容，去掉首尾空白
        text = chunk.page_content.strip()

        # 截断过长的单个片段（保留前 500 字符，防止 LLM 上下文溢出）
        if len(text) > 500:
            text = text[:500] + "...(截断)"

        # 附上元数据上下文，帮助 LLM 理解片段的来源信息
        meta = chunk.metadata or {}

        # 构建上下文描述列表
        ctx_parts = []

        # 如果元数据中有 source（来源文件名），加入上下文
        src = meta.get("source", "")
        if src:
            ctx_parts.append(src)

        # 如果元数据中有 page（页码），加入上下文（如 "p.12"）
        page = meta.get("page")
        if page:
            ctx_parts.append(f"p.{page}")

        # 如果元数据中有 chunk_type（片段类型，如 "标题"、"正文"），加入上下文
        ctype = meta.get("chunk_type", "")
        if ctype:
            ctx_parts.append(ctype)

        # 如果上下文信息不为空，用 " | " 连接起来；否则为空字符串
        ctx = f" | {' | '.join(ctx_parts)}" if ctx_parts else ""

        # 添加编号行，如 "[1] | 财报.pdf | p.5"
        lines.append(f"[{i}]{ctx}")

        # 添加片段内容行（前面缩进 3 个空格）
        lines.append(f"   {text}")

        # 添加两个空行分隔不同的片段
        lines.append("")
        lines.append("")

    # 在最后添加排序指令
    lines.append("请根据与查询的相关性对这些片段进行排序，输出排序后的编号 JSON 数组：")

    # 把所有行用换行符拼接成一个完整的提示词字符串
    return "\n".join(lines)


# ========================================================================
# LLMReranker 类 —— LLM Listwise Reranker
# ========================================================================
# 通过向 LLM 发送 query + chunks 列表，让 LLM 输出相关性排序。
# 可以理解为"让 AI 帮我们重新排一下搜索结果，把最相关的排在前面"。
#
# 使用示例:
#   reranker = LLMReranker(client, model="deepseek-v4-flash")
#   reranked = reranker.rerank(query, chunks, top_k=10)
# ========================================================================

class LLMReranker:
    """LLM Listwise Reranker。

    通过向 LLM 发送 query + chunks 列表，让 LLM 输出相关性排序。

    Usage:
        reranker = LLMReranker(client, model="deepseek-v4-flash")
        reranked = reranker.rerank(query, chunks, top_k=10)
    """

    def __init__(self, client, model: str, enable: bool = True):
        """
        初始化 Reranker。

        参数:
            client: OpenAIClient 实例（必须实现 chat() 方法）
            model: 用于 rerank 的模型名
            enable: 是否启用 rerank（设为 False 时 rerank() 直接返回原列表前 top_k 项）
        """

        # 保存传入的 OpenAIClient 客户端实例，后续用它来调用 LLM
        self.client = client

        # 保存用于 rerank 的模型名称
        self.model = model

        # 保存是否启用 rerank 的标志
        self.enable = enable

        # 记录日志：Reranker 初始化完成
        logger.info(f"LLM Reranker 初始化: model={model}, enable={enable}")

    def rerank(
        self, query: str, chunks: list,
        top_k: Optional[int] = None,
    ) -> list:
        """
        对检索结果进行 LLM listwise rerank。

        参数:
            query: 用户原始查询
            chunks: 候选 Document 列表
            top_k: 返回前 K 个最相关结果（默认返回全部排序后的结果）

        返回:
            rerank 后的 Document 列表（按相关性从高到低排列）
        """

        # 如果以下任一条件满足，就不做 rerank，直接截断返回：
        # 1. enable 被设为 False（未启用 rerank）
        # 2. chunks 为空列表（没有候选文档）
        # 3. chunks 只有 1 个（不需要排序）
        if not self.enable or not chunks or len(chunks) <= 1:
            # 如果指定了 top_k，就返回前 K 个；否则返回全部
            return chunks[:top_k] if top_k else chunks

        # 取前 30 个候选（防止 context 窗口溢出）
        # 因为如果候选太多，LLM 的上下文窗口可能装不下
        candidates = chunks[:30]

        # 使用 try...except 捕获 LLM 调用过程中的异常
        try:
            # 使用辅助函数构建 rerank 提示词
            prompt = _build_rerank_prompt(query, candidates)

            # 构建发送给 LLM 的消息列表
            messages = [
                {"role": "system", "content": _RERANK_SYSTEM_PROMPT},  # 系统消息：告诉 LLM 它的角色和规则
                {"role": "user", "content": prompt},                   # 用户消息：发送查询和候选列表
            ]

            # 记录 Rerank 输入的相关信息（用于调试和监控）
            logger.info(
                f"Rerank 输入: query={query!r}, candidates={len(candidates)}, "
                f"prompt_len={len(prompt)}"
            )

            # 调用 LLM 进行排序
            # 参数说明：
            #   messages：需要排序的查询和候选文档
            #   model：指定的排序模型
            #   stream=False：不需要流式，等待完整结果
            #   temperature=0.1：温度很低（接近 0），让输出更确定性，不要"发挥创意"
            #   max_tokens=4096：最多输出 4096 个 token，足够输出排序结果了
            resp = self.client.chat(
                messages=messages,
                model=self.model,
                stream=False,
                temperature=0.1,
                max_tokens=4096,
            )

            # 如果响应为空或全是空白字符，说明 LLM 没有给出有效排序结果
            if not resp or not resp.strip():
                # 记录警告日志
                logger.warning(f"Rerank 响应为空 (query={query!r}, candidates={len(candidates)})")
                # 回退：直接按原始顺序截断返回
                return chunks[:top_k] if top_k else chunks
                # 注意：上一行后面还有一个重复的返回语句（这是一个 bug，但由于要求保持原始代码不变，这里不动它）

            # 解析 LLM 返回的排序结果，将文本解析为编号列表
            ordered_indices = self._parse_ranking(resp)

            # 如果解析失败（返回空列表），回退到原始顺序
            if not ordered_indices:
                logger.warning("Rerank 解析失败，回退到原始顺序")
                return chunks[:top_k] if top_k else chunks

            # ================================================================
            # 按 LLM 输出的顺序重排候选文档
            # ================================================================

            # seen 集合用于去重，防止 LLM 输出的编号有重复
            seen = set()

            # reranked 列表用于存放重排后的文档
            reranked = []

            # 遍历 LLM 输出的排序编号列表
            for idx in ordered_indices:
                # 检查编号是否在有效范围内（1 ~ len(candidates)）
                # 并且这个编号还没有被处理过（去重）
                if 1 <= idx <= len(candidates) and idx - 1 not in seen:
                    # 将对应编号的文档添加到重排结果中（注意：编号从 1 开始，列表索引从 0 开始，所以要减 1）
                    reranked.append(candidates[idx - 1])
                    # 标记该编号已被处理
                    seen.add(idx - 1)

            # 如果有 LLM 遗漏的片段（没出现在排序结果中的），追加到末尾
            # 这样可以确保不丢失任何候选文档
            for i, c in enumerate(candidates):
                if i not in seen:
                    reranked.append(c)

            # 如果指定了 top_k，只取前 K 个；否则返回全部重排结果
            result = reranked[:top_k] if top_k else reranked

            # 记录日志：Rerank 完成，比较排序前后 Top-1 的变化
            logger.info(
                f"Rerank 完成: {len(candidates)} → {len(result)} 条, "
                f"原始 Top-1={candidates[0].page_content[:40]!r}, "
                f"新 Top-1={result[0].page_content[:40]!r}"
            )

            # 返回重排后的结果
            return result

        except Exception as e:
            # 如果在 LLM 调用或解析过程中发生异常，记录错误日志
            logger.error(f"Rerank 过程异常: {e}，回退到原始顺序")
            # 回退：按原始顺序截断返回
            return chunks[:top_k] if top_k else chunks

    @staticmethod
    def _parse_ranking(response: str) -> List[int]:
        """
        从 LLM 回复中解析出排序后的编号数组。

        这个方法需要处理 LLM 可能输出的各种不标准格式，做了多层解析兜底：
        1. 直接解析为 JSON 数组
        2. 从 Markdown 代码块中提取 JSON
        3. 提取文本中最后的 [...] 数组
        4. 查找松散的数字序列

        参数:
            response: LLM 返回的原始文本

        返回:
            排序后的编号列表，解析失败则返回空列表
        """

        # 去掉响应文本的首尾空白字符
        text = response.strip()

        # 调试日志：记录原始响应以便分析解析失败原因
        logger.debug(f"Rerank 原始响应: {text[:500]}")

        # 如果文本长度 > 512（可能是 max_tokens 限制问题），说明 LLM 输出了大量额外内容
        if len(text) > 512:
            logger.warning(f"Rerank 响应异常: {len(text)} 字符 (预期 <512)")
            # 尝试取最后 200 字符（JSON 数组通常在末尾）
            text = text[-200:]

        # 移除可能导致 JSON 解析失败的特殊不可见字符
        # 比如全角空格和普通空格
        text = text.replace(" ", " ").replace("　", " ")

        # ---- 方法 1：尝试直接作为 JSON 解析 ----
        try:
            # 尝试将整个文本作为 JSON 解析
            data = json.loads(text)
            # 检查解析结果是否是列表，并且所有元素都是整数
            if isinstance(data, list) and all(isinstance(x, int) for x in data):
                return data  # 解析成功，直接返回
        except json.JSONDecodeError:
            # 解析失败，跳过，尝试下一个方法
            pass

        # ---- 方法 2：尝试从代码块中提取 JSON ----
        # 适配 ```json [...] ``` 或 ``` [...] ``` 这两种格式
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                # 尝试解析代码块中的内容
                data = json.loads(m.group(1))
                if isinstance(data, list) and all(isinstance(x, int) for x in data):
                    return data
            except json.JSONDecodeError:
                pass

        # ---- 方法 3：尝试提取文本中最后的 [...] 数组 ----
        # 使用贪婪匹配找到最后一个 [...]，适配有额外文字的情况
        matches = re.findall(r"\[(\d+(?:[\s,，]+(?:\d+))*)\]", text)
        for m in reversed(matches):  # 从最后一个匹配开始尝试（最可能是完整结果）
            try:
                # 支持英文逗号、中文逗号、空格等分隔符
                parts = re.split(r"[\s,，]+", m.strip())
                # 将每个部分转为整数
                data = [int(p) for p in parts if p]
                if data:
                    return data
            except (ValueError, TypeError):
                continue

        # ---- 方法 4：尝试查找松散的数字序列 ----
        # 处理 JSON 数组格式但逗号丢失等异常情况
        nums = re.findall(r"\b(\d+)\b", text)
        if len(nums) > 1:
            try:
                data = [int(n) for n in nums]
                # 简单校验：如果数字都在合理范围内（1~100），尝试返回
                if 1 <= min(data) and max(data) <= 100:
                    return data
            except (ValueError, TypeError):
                pass

        # 全部解析失败，返回空列表
        return []
