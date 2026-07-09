"""Agent 状态机：显式的回合处理状态转换。

基于 nanobot 的 TurnState 模式，使用同步实现适配当前架构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional

from base.config import conf

MAX_TOOL_ITER = conf.max_tool_iter


class TurnState(Enum):
    """代理回合状态枚举。"""
    RESTORE = auto()    # 恢复/加载会话
    COMPACT = auto()    # 压缩/归档旧历史
    COMMAND = auto()    # 命令分发
    BUILD = auto()      # 构建 prompt
    RUN = auto()        # LLM + 工具循环
    SAVE = auto()       # 保存回合到历史
    RESPOND = auto()    # 组装响应
    DONE = auto()       # 完成


# 状态转换表
# 格式: {(当前状态, 事件): 下一状态}
TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
    (TurnState.RESTORE, "ok"): TurnState.COMPACT,
    (TurnState.COMPACT, "ok"): TurnState.COMMAND,
    (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
    (TurnState.COMMAND, "shortcut"): TurnState.DONE,
    (TurnState.BUILD, "ok"): TurnState.RUN,
    (TurnState.RUN, "ok"): TurnState.SAVE,
    (TurnState.RUN, "empty_response"): TurnState.RUN,     # 空响应重试（仍在 RUN 内）
    (TurnState.RUN, "length_recovery"): TurnState.RUN,    # 长度截断恢复
    (TurnState.RUN, "clarification"): TurnState.SAVE,     # 需要澄清，提前保存
    (TurnState.SAVE, "ok"): TurnState.RESPOND,
    (TurnState.RESPOND, "ok"): TurnState.DONE,
}


class StateMachine:
    """回合状态机。

    驱动循环:
      while ctx.state is not TurnState.DONE:
          handler = self._handlers[ctx.state]
          event = handler(ctx)
          ctx.state = TRANSITIONS[(ctx.state, event)]
    """

    def __init__(self):
        self._handlers: dict[TurnState, Callable] = {}

    def register(self, state: TurnState, handler: Callable):
        """注册状态处理器。"""
        self._handlers[state] = handler

    def run(self, ctx: StateContext) -> str:
        """驱动状态机运行。返回最终输出。"""
        while ctx.state is not TurnState.DONE:
            handler = self._handlers.get(ctx.state)
            if handler is None:
                raise RuntimeError(f"未注册状态处理器: {ctx.state}")

            event = handler(ctx)
            next_state = TRANSITIONS.get((ctx.state, event))
            if next_state is None:
                raise RuntimeError(
                    f"无效状态转换: {ctx.state.name} + event={event!r}"
                )

            ctx.state = next_state

        return ctx.output

    def step(self, ctx: StateContext) -> bool:
        """单步执行（用于流式/异步场景）。返回 True 表示仍在运行。"""
        if ctx.state is TurnState.DONE:
            return False

        handler = self._handlers.get(ctx.state)
        if handler is None:
            raise RuntimeError(f"未注册状态处理器: {ctx.state}")

        event = handler(ctx)
        next_state = TRANSITIONS.get((ctx.state, event))
        if next_state is None:
            raise RuntimeError(
                f"无效状态转换: {ctx.state.name} + event={event!r}"
            )

        ctx.state = next_state
        return ctx.state is not TurnState.DONE


class StateContext:
    """状态机上下文，在各状态之间传递数据。"""

    def __init__(self, session_id: str, question: str, **kwargs):
        self.session_id = session_id
        self.question = question
        self.state: TurnState = TurnState.RESTORE
        self.partition: Optional[str] = kwargs.get("partition")
        self.style: Optional[str] = kwargs.get("style")
        self.history: list = kwargs.get("history") or []

        # 状态间共享数据
        self.messages: list = []
        self.system_msg: str = ""
        self.answer: str = ""
        self.output: str = ""
        self.tool_results: list = []
        self.error: Optional[str] = None
        self.is_cancelled: bool = False

        # 运行时数据
        self.metadata: dict = {}  # 供 checkpoint 等使用


# ========================================================================
# AgentState: tool-calling 循环的运行时状态 (原 state.py)
# ========================================================================
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
    # partition: 向量检索时的命名空间/分区标识（通常为用户标识），用于隔离不同用户的检索数据
    # Optional[str] 表示该字段可为 None（不指定分区时默认为 None）
    partition: Optional[str] = None
    # style: 回答风格标识，例如 "style-formal"，可为 None 表示使用默认风格
    # 该值会被注入 system prompt，影响 LLM 回答的语气和格式
    style: Optional[str] = None
    # 签名格式为 "tool_name::序列化参数"，用于检测完全相同的重复调用
    # 以下划线开头表示"私有"属性，不应在外部直接访问
    # 作用：防止 LLM 因上下文遗忘而用完全相同的参数反复调用同一个工具，陷入原地打转
    # 类型为 dict，键为工具名 (str)，值为调用次数 (int)
    # 初始值为空字典，通过 field(default_factory=dict) 确保每个实例独立拥有
    # 作用：防止 LLM 换用不同参数但本质仍是同一个工具的频繁调用，构成第一道防线

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
