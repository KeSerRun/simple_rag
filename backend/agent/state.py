# ===== 模块文档字符串 =====
"""Agent 状态机: 封装 tool-calling 循环的运行时状态。

职责:
  - 持有 messages (会话消息列表, 随 tool 调用自动增长)
  - 追踪迭代轮次, 到达上限后自动终结
  - 存储上下文参数 (partition / style)
  - 追踪短期/长期任务 (跨提问轮次持久化)

使用方式:
  state = AgentState(messages, partition=..., short_term_tasks=[...])
  while state.should_continue():
      ...
"""
# ===== 导入标准库 / 第三方库 / 项目内部模块 =====
# 导入 __future__ 的 annotations 特性，让类型注解中的类名可以延迟求值（即支持前向引用）
from __future__ import annotations

# 从 dataclasses 模块导入 dataclass 装饰器和 field 函数，用于定义数据类
from dataclasses import dataclass, field
# 从 typing 模块导入 List（列表类型）和 Optional（可选类型）用于类型注解
from typing import List, Optional

# 从项目基础配置模块导入 conf 对象，该对象持有全局配置（如最大迭代次数、工具调用上限等）
from base.config import conf

# 从配置对象 conf 中读取 max_tool_iter 属性，作为 LLM 工具调用循环的最大迭代轮数的全局默认值
MAX_TOOL_ITER = conf.max_tool_iter


# ===== AgentState 数据类定义 =====
# 使用 @dataclass 装饰器标记此类为 Python 数据类，自动生成 __init__、__repr__ 等方法
@dataclass
class AgentState:
    # ===== AgentState 的文档字符串 =====
    """Agent 状态, 在 tool-calling 循环中逐步累积。

    Attributes:
        messages: OpenAI 格式的 messages 列表 (system + history + user + assistant + tool)
        iteration: 当前已完成的 tool-call 轮次
        max_iterations: 最多允许的 tool-call 轮数
        partition: 向量检索分区 (用户名)
        style: 回答风格 skill 名 (如 style-formal), None 表示默认
        short_term_tasks: 当前会话的短期任务列表（本轮对话的核心目标）
        long_term_tasks: 当前会话的长期任务列表（多轮对话中持续追踪的目标）
    """
    # ===== 实例字段定义 =====
    # messages: 整个对话的消息历史，按 OpenAI API 格式组织，包含 system / user / assistant / tool 四种角色
    # field(default_factory=list) 表示每个实例独立拥有一个空列表，不会在所有实例间共享
    messages: List[dict] = field(default_factory=list)
    # iteration: 当前已执行的 tool-call 轮次数，每调用一次 add_assistant_response 就 +1
    # 初始值为 0，从第一轮开始计数
    iteration: int = 0
    # max_iterations: 最大允许的 tool-call 轮次，达到此上限后 should_continue() 返回 False，循环终止
    # 默认值从模块常量 MAX_TOOL_ITER 读取，该常量来自全局配置 conf.max_tool_iter
    max_iterations: int = MAX_TOOL_ITER
    # max_calls_per_tool: 每个工具在单轮回答中的最大调用次数
    # 默认值为 None，表示从全局配置 conf 中读取 conf.max_calls_per_tool 作为实际阈值
    max_calls_per_tool: int = None
    # partition: 向量检索时的命名空间/分区标识（通常为用户标识），用于隔离不同用户的检索数据
    # Optional[str] 表示该字段可为 None（不指定分区时默认为 None）
    partition: Optional[str] = None
    # style: 回答风格标识，例如 "style-formal"，可为 None 表示使用默认风格
    # 该值会被注入 system prompt，影响 LLM 回答的语气和格式
    style: Optional[str] = None
    # _called_tools_history: 已调用过的工具签名集合，类型为 set
    # 签名格式为 "tool_name::序列化参数"，用于检测完全相同的重复调用
    # 以下划线开头表示"私有"属性，不应在外部直接访问
    # 作用：防止 LLM 因上下文遗忘而用完全相同的参数反复调用同一个工具，陷入原地打转
    _called_tools_history: set = field(default_factory=set)
    # _tool_call_counts: 每个工具在当前 iteration 阶段的累计调用次数
    # 类型为 dict，键为工具名 (str)，值为调用次数 (int)
    # 初始值为空字典，通过 field(default_factory=dict) 确保每个实例独立拥有
    # 作用：防止 LLM 换用不同参数但本质仍是同一个工具的频繁调用，构成第一道防线
    _tool_call_counts: dict = field(default_factory=dict)

    # ===== should_continue 方法 =====
    def should_continue(self) -> bool:
        # ===== 方法文档字符串 =====
        """判断 tool-calling 循环是否应继续执行。

        控制逻辑:
          - 只要 iteration < max_iterations 就返回 True，允许 LLM 继续发起 tool call
          - 一旦达到或超过上限，返回 False，主循环退出，将当前 messages 返回给上层
          - 这是一种"硬边界"保护，防止 LLM 无限制地调用工具导致无限循环或 token 耗尽

        外部调用方通常这样使用:
            while state.should_continue():
                response = client.chat(...)
                if response.tool_calls:
                    state.add_assistant_response(...)
                    # 处理 tool calls ...
                else:
                    break  # LLM 主动选择不再调用工具

        注意: 即使 LLM 不再发起 tool call，外层循环也可以根据此方法提前 break，
        因此 max_iterations 仅作为最坏情况下的安全阀（safety valve）。
        """
        # 比较当前已完成的迭代轮次是否小于最大允许轮次
        # 如果小于则返回 True（继续循环），否则返回 False（终止循环）
        return self.iteration < self.max_iterations

    # ===== add_assistant_response 方法 =====
    def add_assistant_response(self, content: str, tool_calls: List[dict]):
        # ===== 方法文档字符串 =====
        """将 LLM 的文本回复及其触发的 tool_calls 结构化为 assistant 消息，追加到 messages 列表。

        参数:
            content: LLM 返回的文本内容（可能为空字符串，当 LLM 只调用工具时）
            tool_calls: LLM 返回的工具调用列表，每个元素包含 id / name / arguments 字段

        处理逻辑:
          1. 将原始的 tool_calls 列表重新格式化为 OpenAI API 标准格式
             (包含 id / type / function.name / function.arguments)
          2. 将格式化后的消息以 role="assistant" 追加到 messages
          3. iteration 计数器 +1，标记完成了一轮 tool-call 迭代

        为什么 iteration 在这里递增:
          - 因为每次 LLM 发出 tool_calls 就意味着"一轮"交互的结束
          - 后续 tool 结果返回后 LLM 可能再次调用工具，那将是下一轮
          - iteration 递增后，should_continue() 会重新评估是否已达上限
        """
        # 向 self.messages 列表中追加一条新的 assistant 角色消息
        # 使用列表的 append 方法在末尾添加一个字典
        self.messages.append({
            # 设置消息角色为 "assistant"，表示这是 LLM 生成的回复
            "role": "assistant",
            # 设置消息的文本内容，可能是空字符串（当 LLM 只调用工具不说话时）
            "content": content,
            # 设置工具调用列表，将原始 tool_calls 转换为 OpenAI API 标准格式
            "tool_calls": [
                {
                    # 工具调用唯一标识符，用于后续关联 tool 结果消息
                    "id": tc["id"],
                    # 固定为 "function"，表示这是一个函数调用类型的工具
                    "type": "function",
                    # function 对象包含工具名称和参数字符串
                    "function": {
                        # 工具/函数名称，如 "web_search"、"retrieve_knowledge" 等
                        "name": tc["name"],
                        # 工具调用的参数字符串，JSON 格式，如 '{"query": "..."}'
                        "arguments": tc["arguments"],
                    },
                }
                # 遍历原始的 tool_calls 列表，逐条转换格式
                for tc in tool_calls
            ],
        })
        # iteration 计数器加 1，标记已完成一轮 tool-call 迭代
        # 这会影响 should_continue() 的下一次判断结果
        self.iteration += 1

    # ===== add_tool_result 方法 =====
    def add_tool_result(self, tool_call_id: str, content: str):
        # ===== 方法文档字符串 =====
        """将工具执行结果以 tool 角色消息追加到 messages，供 LLM 下一轮读取。

        参数:
            tool_call_id: 对应的 assistant 消息中 tool_call 的 id，用于关联
            content: 工具执行返回的结果字符串（通常是 JSON 或文本）

        注意:
          - tool_call_id 必须与 add_assistant_response 中记录的 id 一一对应
          - content 应尽量结构化，便于 LLM 理解；若工具出错也应返回错误信息而非抛出异常
          - 此方法不涉及 iteration 递增 —— iteration 只在 LLM 发出 tool_calls 时计数
        """
        # 向 self.messages 列表中追加一条 tool 角色消息
        self.messages.append({
            # 设置消息角色为 "tool"，表示这是工具执行结果的反馈消息
            "role": "tool",
            # 设置此工具结果对应的原始工具调用 ID，用于与 assistant 消息中的 tool_call 关联
            # LLM 通过此 ID 知道这条结果是对应哪个工具调用
            "tool_call_id": tool_call_id,
            # 工具执行返回的具体内容，通常是 JSON 字符串或纯文本描述
            "content": content,
        })

    # ===== check_and_record_tool_call 方法 =====
    def check_and_record_tool_call(self, name: str, arguments: str) -> tuple[bool, str]:
        # ===== 方法文档字符串 =====
        """检查工具调用是否合法，构成"双重防御机制"拦截潜在的死循环调用。

        参数:
            name: 工具名称 (如 "web_search", "retrieve_knowledge")
            arguments: 工具的原始参数字符串 (JSON 格式)

        返回:
            (is_blocked: bool, reason: str)
            - is_blocked=True  表示调用被拦截，reason 为对 LLM 的警告消息
            - is_blocked=False 表示调用通过检查，reason 为空字符串

        === 双重防御机制详解 ===

        第一道防线 —— 调用次数上限检测 (count-based):
          - 使用 _tool_call_counts 字典对每个工具名独立计数
          - 无论参数是否变化，同一个工具名被调用超过 max_calls_per_tool 次即触发拦截
          - 防御场景：LLM 反复尝试同一种工具但每次换用略微不同的参数
            (例如用不同的关键词反复搜索，期待不同结果)
          - 阈值可从两个层级配置：实例级 max_calls_per_tool（优先级高）或全局 conf.max_calls_per_tool

        第二道防线 —— 完全重复调用检测 (signature-based):
          - 使用 _called_tools_history 集合记录每条 "工具名::序列化参数" 签名
          - 如果完全相同的一组参数已被调用过，直接拦截
          - 防御场景：LLM 因上下文遗忘而用完全相同的参数再次调用同一个工具
            (例如在长对话中重复搜索同一个关键词)
          - 参数先 JSON.parse 再 sort_keys 序列化，确保语义相同的不同格式被归一化

        为什么需要两套机制:
          - _tool_call_counts (计数) 可以拦截"换词但本质相同"的频繁调用
          - _called_tools_history (签名) 可以拦截"参数完全相同"的重复调用
          - 两者互补：计数防高频、签名防重复，共同构成鲁棒的死循环防护

        为什么 _called_tools_history 和 _tool_call_counts 是分开的两个字段:
          - 它们追踪的是不同维度的信息：
            * _tool_call_counts: {工具名 -> 次数}，关注"某个工具被调了多少次"
            * _called_tools_history: {签名集合}，关注"某个具体参数组合是否已被调用过"
          - 数据结构不同：一个需要计数值 (dict)，一个只需存在性判断 (set)
          - 生命周期和重置策略可能不同：未来如果引入"每轮重置"机制，
            计数可能按轮次重置，而历史签名可能跨轮次保持去重
          - 设计上符合单一职责原则：一个字段做计数，一个字段做去重
        """
        # 在函数内部导入 json 模块，用于解析和序列化工具参数字符串
        import json
        # 确定当前工具的单轮调用上限：
        # 优先使用实例级别设置的 max_calls_per_tool（在 __init__ 时传入）
        # 如果实例级别为 None，则回退到全局配置中的 conf.max_calls_per_tool
        limit = self.max_calls_per_tool if self.max_calls_per_tool is not None else conf.max_calls_per_tool

        # ===== 参数归一化处理 =====
        # 将工具参数字符串解析为 Python 字典，再重新序列化为 JSON 字符串
        # 使用 sort_keys=True 保证字典键的排序一致，从而实现参数归一化
        # 例如 {"a":1,"b":2} 和 {"b":2,"a":1} 会被归一化为同一个签名字符串
        try:
            # 尝试将 arguments 字符串解析为 JSON 对象
            # 如果 arguments 是空字符串或 None，则解析为空字典 {}
            parsed_args = json.loads(arguments) if arguments else {}
            # 将解析后的字典重新序列化为 JSON，键按字母排序（sort_keys=True）
            # 这样不同顺序但语义相同的参数会被归一化为统一字符串
            norm_args = json.dumps(parsed_args, sort_keys=True)
        except Exception:
            # 如果参数不是合法 JSON（例如纯字符串、数字、空值等情况），则直接使用原始字符串作为签名
            # 异常捕获确保即使参数格式异常也不会破坏整个流程
            norm_args = arguments

        # ===== 第一道防线：调用次数上限检测 =====
        # 如果当前工具名还没有在 _tool_call_counts 字典中注册，则初始化为 0
        # setdefault 方法：键不存在时设置默认值，存在时不做任何操作
        self._tool_call_counts.setdefault(name, 0)
        # 将当前工具的调用计数加 1，表示又发起了一次对该工具的调用
        self._tool_call_counts[name] += 1
        # 检查该工具的累计调用次数是否超过了设定的上限 limit
        # 如果是，则拦截本次调用，返回 (True, 警告消息)
        if self._tool_call_counts[name] > limit:
            # 返回拦截结果：True 表示已拦截，第二个参数是向 LLM 展示的警告文本
            # 警告消息中明确告知 LLM 已达到上限，要求其停止搜索并直接总结
            return True, f"(系统警告：为了防止死循环，工具 {name} 在本轮回答中已达到最大调用次数 {limit} 次上限。请停止搜索，立刻根据已有信息进行总结作答，若无答案请直接承认。)"

        # ===== 第二道防线：完全重复调用检测 =====
        # 构造本次调用的唯一签名：格式为 "工具名::归一化参数"
        # 使用 "::" 作为分隔符，区分工具名称和参数部分，避免命名冲突
        sig = f"{name}::{norm_args}"
        # 检查签名 sig 是否已经存在于历史记录集合 _called_tools_history 中
        # in 运算符用于判断 set 中是否包含某元素，时间复杂度为 O(1)
        if sig in self._called_tools_history:
            # 如果完全相同的签名已存在，说明这是一次重复调用
            # 返回拦截结果：True 表示已拦截，警告消息告知 LLM 已调用过相同参数
            return True, "(系统警告：您刚刚已经使用过完全相同的参数调用了此工具并获得了相同结果。请停止尝试，直接进行总结回答。)"

        # 所有检查均已通过，将本次调用的签名加入历史记录集合中
        # add 方法将元素添加到 set 中，如果已存在则不会重复添加
        self._called_tools_history.add(sig)
        # 返回 (False, "") 表示调用未被拦截，可以正常执行
        # False 表示"允许调用"，空字符串表示没有警告消息
        return False, ""
