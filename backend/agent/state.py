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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from base.config import conf

# 从配置中读取最大 tool-call 迭代轮次，作为全局上限
MAX_TOOL_ITER = conf.max_tool_iter


@dataclass
class AgentState:
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
    # 整个对话的消息历史，按 OpenAI API 格式组织，包含 system / user / assistant / tool 四种角色
    messages: List[dict] = field(default_factory=list)
    # 当前已执行的 tool-call 轮次数，每调用一次 add_assistant_response 就 +1
    iteration: int = 0
    # 最大允许的 tool-call 轮次，达到此上限后 should_continue() 返回 False，循环终止
    max_iterations: int = MAX_TOOL_ITER
    # 每个工具在单轮回答中的最大调用次数，None 则从 conf 中读取默认值
    max_calls_per_tool: int = None
    # 向量检索时的命名空间/分区标识（通常为用户标识），用于隔离不同用户的检索数据
    partition: Optional[str] = None
    # 回答风格标识，例如 "style-formal"，可为 None 表示使用默认风格
    style: Optional[str] = None
    # 当前会话的短期任务列表，用于本轮对话中 LLM 自主规划的子目标
    short_term_tasks: List[str] = field(default_factory=list)
    # 当前会话的长期任务列表，跨多轮对话持续追踪，在每次提问时注入 system prompt
    long_term_tasks: List[str] = field(default_factory=list)
    # 已调用过的工具签名集合 (tool_name::序列化参数)，用于检测完全相同的重复调用
    # 作用：防止 LLM 因上下文遗忘而用完全相同的参数反复调用同一个工具，陷入原地打转
    _called_tools_history: set = field(default_factory=set)
    # 每个工具在当前 iteration 阶段的累计调用次数 (tool_name -> count)
    # 作用：防止 LLM 换用不同参数但本质仍是同一个工具的频繁调用，构成第一道防线
    _tool_call_counts: dict = field(default_factory=dict)

    def should_continue(self) -> bool:
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
        return self.iteration < self.max_iterations

    def add_assistant_response(self, content: str, tool_calls: List[dict]):
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
        self.messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ],
        })
        self.iteration += 1

    def add_tool_result(self, tool_call_id: str, content: str):
        """将工具执行结果以 tool 角色消息追加到 messages，供 LLM 下一轮读取。

        参数:
            tool_call_id: 对应的 assistant 消息中 tool_call 的 id，用于关联
            content: 工具执行返回的结果字符串（通常是 JSON 或文本）

        注意:
          - tool_call_id 必须与 add_assistant_response 中记录的 id 一一对应
          - content 应尽量结构化，便于 LLM 理解；若工具出错也应返回错误信息而非抛出异常
          - 此方法不涉及 iteration 递增 —— iteration 只在 LLM 发出 tool_calls 时计数
        """
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def check_and_record_tool_call(self, name: str, arguments: str) -> tuple[bool, str]:
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
        import json
        # 确定当前工具的单轮调用上限：优先使用实例级别设置，否则从全局配置读取
        limit = self.max_calls_per_tool if self.max_calls_per_tool is not None else conf.max_calls_per_tool

        # === 参数归一化 ===
        # 将参数字符串解析为字典再重新序列化，保证排序一致
        # 例如 {"a":1,"b":2} 和 {"b":2,"a":1} 会被归一化为同一个签名
        try:
            parsed_args = json.loads(arguments) if arguments else {}
            norm_args = json.dumps(parsed_args, sort_keys=True)
        except Exception:
            # 如果参数不是合法 JSON（例如纯字符串、空值等），则直接使用原始字符串作为签名
            norm_args = arguments

        # === 第一道防线：调用次数上限检测 ===
        # 对当前工具名计数 +1，若超过上限则拦截并返回警告
        self._tool_call_counts.setdefault(name, 0)
        self._tool_call_counts[name] += 1
        if self._tool_call_counts[name] > limit:
            return True, f"(系统警告：为了防止死循环，工具 {name} 在本轮回答中已达到最大调用次数 {limit} 次上限。请停止搜索，立刻根据已有信息进行总结作答，若无答案请直接承认。)"

        # === 第二道防线：完全重复调用检测 ===
        # 构造工具签名：工具名 + "::" + 归一化参数
        sig = f"{name}::{norm_args}"
        if sig in self._called_tools_history:
            # 如果完全相同的签名已存在，说明这是一次重复调用，拦截并返回警告
            return True, "(系统警告：您刚刚已经使用过完全相同的参数调用了此工具并获得了相同结果。请停止尝试，直接进行总结回答。)"

        # 通过所有检查，将本次调用签名加入历史记录，返回通过
        self._called_tools_history.add(sig)
        return False, ""
