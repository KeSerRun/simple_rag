"""工具注册中心: ToolRegistry + ToolContext + ToolDef

设计目标:
  - 工具通过 registry.register() 注册，不再写 if/elif 链
  - 前后端兼容: registry.schemas 替代 TOOL_SCHEMAS, registry.dispatch 替代 execute_tool
"""
# 从 __future__ 导入 annotations，使得所有类型注解变成字符串形式（延迟求值），
# 这样可以解决类定义中引用自身类型时的循环引用问题（PEP 563）
from __future__ import annotations

# 导入 Python 内置的 json 模块，用于处理 JSON 数据的序列化和反序列化
# 后续在 dispatch 方法中会把前端传过来的 JSON 字符串解析成 Python 字典
import json
# 从 dataclasses 模块导入 dataclass 装饰器，它可以自动为类生成 __init__、__repr__ 等方法
# 使用 dataclass 可以大大简化数据类的定义，不用手动写一堆模板代码
from dataclasses import dataclass
# 从 typing 模块导入类型提示相关的工具：
#   Callable —— 表示可调用对象（函数/方法）的类型
#   List    —— 表示列表类型（虽然 Python 3.9+ 可以用内置 list，这里为了兼容旧版本）
#   Optional —— 表示可选类型，等价于 Union[T, None]
from typing import Callable, List, Optional

# 从 base.logger 模块导入 logger 对象，这是项目自定义的日志记录器
# 用于在工具注册、调用、出错时输出日志信息，方便调试和排查问题
from base.logger import logger

# 从 rag.vector_store 模块导入 VectorStore 类，这是向量数据库的封装
# 向量存储用于存储文档的向量表示，并支持相似度检索（给 LLM 提供相关知识）
from rag.vector_store import VectorStore


# ===== ToolContext：工具调用的运行时上下文 =====

@dataclass
# 使用 @dataclass 装饰器，Python 会自动生成 __init__、__repr__、__eq__ 等方法
class ToolContext:
    """传递给 tool handler 的运行时上下文。"""
    # vector_store: 向量数据库实例，工具处理函数可以通过它来检索相关文档片段
    # 这是工具与 RAG 系统的核心连接点
    vector_store: VectorStore
    # partition: 分区标识符，用于在多租户场景下隔离不同用户/项目的文档数据
    # 如果不传就是 None，表示不限制分区
    partition: Optional[str] = None
    # data_store: 通用数据存储接口，可用于存取任意结构化数据（比如用户配置、对话历史等）
    # 类型标注为 Optional[object]，表示可以是任何类型的对象或 None
    data_store: Optional[object] = None
    # reranker: LLMReranker 重排序器实例，用于对检索结果进行重新排序
    # 让最相关的结果排在前面，提高 RAG 的回答质量
    reranker: Optional[object] = None  # LLMReranker 实例，用于 rerank 检索结果


# ===== ToolDef：单个工具的定义 =====

@dataclass
class ToolDef:
    """单个工具的定义。"""
    # name: 工具的名称，LLM 根据这个名字来调用对应的工具，必须唯一
    name: str
    # description: 工具的自然语言描述，LLM 根据这个描述判断何时应该使用该工具
    description: str
    # parameters: JSON Schema 格式的参数定义字典，描述该工具需要哪些参数及其类型
    # LLM 会根据这个 schema 自动生成符合格式的参数 JSON
    parameters: dict
    # handler: 实际执行工具逻辑的函数，接收两个参数：
    #   1. args (dict): 解析后的参数字典
    #   2. ctx (ToolContext): 运行时上下文
    #   返回一个字符串作为工具调用的结果
    handler: Callable
    # source: 工具来源标识，默认为空字符串，用于说明该工具来自哪个模块或插件
    source: str = ""

    @property
    # @property 装饰器将 schema 方法变成属性，调用时不用加括号（即 tool.schema）
    # 这个方法把工具定义转换成 OpenAI 兼容的 function calling 格式的字典
    def schema(self) -> dict:
        # 返回符合 OpenAI function calling 规范的字典结构
        # 这样前端或其他兼容 OpenAI API 的系统可以直接使用
        return {
            # type 固定为 "function"，表示这是一个函数调用工具
            "type": "function",
            # function 字段包含工具的具体信息
            "function": {
                # name: 工具的唯一名称
                "name": self.name,
                # description: 工具的描述文本
                "description": self.description,
                # parameters: 工具的 JSON Schema 参数定义
                "parameters": self.parameters,
            },
        }


# ===== ToolRegistry：工具注册中心 =====

class ToolRegistry:
    """工具注册中心。"""
    # 这个类负责统一管理所有工具的生命周期：
    #   - 注册新工具（register）
    #   - 查询已注册的工具（get、schemas、tool_names）
    #   - 根据名称分发并执行工具调用（dispatch）

    def __init__(self):
        # _tools: 内部字典，存储所有已注册的工具
        # 键是工具名称（str），值是 ToolDef 对象
        # 使用字典存储可以实现 O(1) 时间复杂度的查找
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        # name: 要注册的工具名称，必须是唯一的，LLM 通过这个名字来调用
        name: str,
        # description: 描述工具的用途，LLM 根据描述决定是否使用该工具
        description: str,
        # parameters: JSON Schema 格式的参数定义，告诉 LLM 需要提供哪些参数
        parameters: dict,
        # handler: 实际执行工具逻辑的函数，它会接收参数字典和运行时上下文
        handler: Callable[[dict, ToolContext], str],
        # source: 可选的来源标识，表示这个工具来自哪里（默认空字符串）
        source: str = "",
    ) -> ToolDef:
        # 检查是否已经存在同名的工具
        if name in self._tools:
            # 如果已存在同名工具，记录一条警告日志（注意并不会阻止注册，会直接覆盖）
            # 这是为了防止开发者不小心重复注册了同一个工具而没有意识到
            logger.warning(f"工具 {name!r} 被覆盖注册")
        # 根据传入的参数创建一个 ToolDef 数据类的实例
        tool = ToolDef(name=name, description=description,
                       parameters=parameters, handler=handler, source=source)
        # 将新创建的工具对象存入 _tools 字典，键是工具名称
        self._tools[name] = tool
        # 返回创建的 ToolDef 对象，方便调用方在需要时直接引用
        return tool

    @property
    # schemas 属性返回所有已注册工具的 JSON Schema 列表
    # 这个列表可以直接传给 LLM，告诉它所有可用的工具及其调用方式
    def schemas(self) -> List[dict]:
        # 遍历 _tools 字典中的所有 ToolDef 对象，调用每个对象的 schema 属性
        # 将结果组装成一个列表并返回
        return [t.schema for t in self._tools.values()]

    @property
    # tool_names 属性返回所有已注册工具的名称列表
    # 可以用于调试、展示可用工具列表等场景
    def tool_names(self) -> List[str]:
        # 直接从 _tools 字典中取出所有键（工具名称）并转为列表
        return list(self._tools.keys())

    def get(self, name: str) -> Optional[ToolDef]:
        # 根据工具名称查找对应的 ToolDef 对象
        # 使用字典的 .get() 方法，如果找不到不会抛异常，而是返回 None
        # 返回 Optional[ToolDef] 表示可能找到也可能找不到
        return self._tools.get(name)

    def dispatch(self, name: str, args_json: str, *, ctx: ToolContext) -> str:
        # dispatch 是工具调用的核心方法，负责：
        #   1. 解析参数 JSON
        #   2. 查找对应工具
        #   3. 执行工具处理函数
        #   4. 返回执行结果字符串
        # 参数:
        #   name: 要调用的工具名称
        #   args_json: JSON 格式的参数字符串
        #   ctx: 运行时上下文对象（包含 vector_store 等资源）
        #
        # 注意: ctx 使用了关键字参数（* 后面），调用时必须写成 ctx=xxx 的形式

        # ===== 步骤 1: 解析参数 JSON =====
        try:
            # 将 JSON 字符串解析成 Python 字典
            # 如果 args_json 为空字符串或 None，则使用空字典 {}
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError as e:
            # 如果 JSON 格式不正确，记录警告日志并返回错误信息
            logger.warning(f"tool {name!r} 参数 JSON 解析失败 ({e})")
            # 返回友好的错误消息，这样 LLM 可以看到并尝试重新生成正确的参数
            return f"(工具调用失败: 参数 JSON 解析错误 {e})"

        # ===== 步骤 2: 查找已注册的工具 =====
        # 从 _tools 字典中获取指定名称的工具
        tool = self._tools.get(name)
        if tool is None:
            # 如果找不到对应的工具（未注册或名称拼写错误）
            # 记录警告日志，同时打印出所有已注册的工具名称，方便调试
            logger.warning(f"未注册的工具: {name!r}, 已注册: {sorted(self._tools.keys())}")
            # 返回错误消息，LLM 收到后就不会再调用这个不存在的工具了
            return f"(未知工具: {name})"

        # ===== 步骤 3: 执行工具处理函数 =====
        try:
            # 调用工具处理函数，传入解析后的参数和运行时上下文
            # handler 是开发者在 register 时传入的函数
            result = tool.handler(args, ctx)
            # 如果结果是 None 或空字符串，返回空字符串（让 LLM 自行处理）
            # 否则返回实际的结果文本
            return result or ""
        except Exception as e:
            # 捕获所有可能的异常（比如调用外部 API 失败、数据库连接错误等）
            # 记录错误日志
            logger.error(f"工具 {name!r} 执行失败: {e}")
            # 返回错误消息给 LLM，让它知道工具执行出了问题
            return f"(工具执行失败: {e})"
