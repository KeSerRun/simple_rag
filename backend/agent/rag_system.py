# ===== 文件说明：RAG 系统的核心 Agent =====
# 这个文件实现了 RAG（检索增强生成）系统的主循环逻辑
# 它负责协调 LLM（大语言模型）、向量检索库、工具调用等工作

# ===== 模块文档字符串：说明本文件的作用和整体流程 =====
"""RAG agent: tool-calling 循环驱动 LLM 自主决策是否检索 / 如何拆解查询 / 最终答案。

流程:
  1. identity + 当前分区文档清单 → system message    # 第一步：组装系统提示消息（身份信息 + 文档列表）
  2. [system, ...history, user(query)] → LLM (带 search_knowledge_base 工具)  # 第二步：把消息发给 LLM，并告诉它可以调用检索工具
  3. LLM 决定是否调工具 / 调几次 → 工具结果回灌 messages  # 第三步：LLM 自己决定要不要查资料，查完的结果放回消息列表
  4. 无更多工具调用 → streamed 最终答案  # 第四步：当 LLM 不再需要查资料时，输出最终答案

AgentState 封装了循环中的 messages / 轮次 / 上下文参数。  # AgentState 负责管理整个循环过程中的状态
"""
# ===== 导入标准库模块 =====
import hashlib
import json
import os  # 导入操作系统模块，用于文件路径操作（拼接路径、获取目录等）
import threading
from functools import lru_cache
from pathlib import Path

from typing import Callable, List, Optional

# —— 配置与日志 ——  （这两个是项目自己的基础模块）
from base.config import conf          # 全局配置（模型名、超时、token 限制等）
# conf 是一个全局配置对象，里面保存了所有模型名称、API 密钥、超时时间等配置项
from base.logger import logger        # 结构化日志
# logger 是项目的日志工具，用于在控制台输出带时间戳和级别的日志信息

# —— RAG 核心组件 ——  （RAG 系统的三个核心模块）
from rag.vector_store import VectorStore  # 本地向量存储，用于语义搜索
# VectorStore 负责把文本转成向量，并支持根据语义相似度搜索最相关的内容
from base.llm_client import OpenAIClient      # OpenAI 兼容的 API 客户端（流式 / 非流式）
# OpenAIClient 封装了调用 OpenAI 或兼容 API（如阿里云通义千问）的细节，支持流式和非流式两种模式

# —— Agent 内部组件 ——  （Agent 自己的子模块）
from .context_builder import ContextBuilder  # 从 prompts 目录加载 identity / 风格模板
# ContextBuilder 负责从 prompts 文件夹读取"AI 身份设定"和"回答风格模板"
from .state_machine import AgentState                # 工具循环的状态机（迭代计数、消息列表、工具调用记录）
# AgentState 负责管理 tool loop 的状态，包括已经轮了多少次、消息列表、调用了哪些工具等
from .tools.registry import ToolContext            # 工具执行时的上下文（向量库、分区、数据存储）
# ToolContext 是执行工具时传给工具的上下文对象，包含向量库、知识库分区、数据存储等信息
from .tools import registry                  # 全局工具注册表，管理所有可用工具的 schema 和 dispatch
# registry 是一个全局的工具注册表，记录了所有可用的工具（如搜索知识库、网络搜索等）
from .workflow_router import WorkflowRouter  # 路由引擎：根据用户问题匹配预设工作流
# WorkflowRouter 负责根据用户的问题内容匹配预设的工作流（比如股票查询走"金融分析"流程）

# ===== 全局路径和日志配置 =====
# 后端根目录（本项目 backend/ 目录的绝对路径）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 这行代码通过两次 dirname 从当前文件路径向上跳两级，得到 backend/ 目录的绝对路径
# 比如：文件在 backend/agent/rag_system.py → 得到 backend/

# 输入日志（每次调 LLM 的完整 messages）
_input_log_path = os.path.join(_BACKEND_ROOT, "logs", "input.log")
# 这行代码拼接出日志文件的完整路径：backend/logs/input.log
# 每次调用 LLM 时，发送给 LLM 的消息都会记录到这个日志文件，方便调试

# 确保日志目录在启动时已创建，与 base/logger.py 中 app.log/http.log/user.log 保持一致
os.makedirs(os.path.dirname(_input_log_path), exist_ok=True)


# ===== 日志记录辅助函数 =====
def _log_input(messages: list, round: int = 0, suffix: str = ""):
    """将 messages 追加到 input.log。suffix 用于区分不同阶段的日志。"""
    # 这个函数的作用是把 messages 写入 input.log 文件
    # messages 参数是发送给 LLM 的消息列表
    # round 参数表示当前的轮次
    # suffix 参数是一个后缀标识，比如 "_sent" 表示实际发送的（可能被截断后的）消息

    import json as _json, datetime as _dt  # 导入 JSON 模块（用于序列化数据）和 datetime 模块（用于获取当前时间）
    # 在函数内部导入，避免模块级别的命名冲突（加下划线前缀表示内部使用）

    try:  # 用 try 包裹，防止日志写入失败影响主流程
        os.makedirs(os.path.dirname(_input_log_path), exist_ok=True)  # 确保 logs/ 目录存在，如果不存在就自动创建
        # os.makedirs 会递归创建目录，exist_ok=True 表示目录已存在时不报错

        with open(_input_log_path, "a", encoding="utf-8") as _f:  # 以追加模式（a）打开日志文件，编码用 UTF-8
            tag = f" round={round}{suffix}" if suffix else f" round={round}"  # 构造日志标签，比如 " round=1_sent"
            # 如果有 suffix，标签就是 " round=1_sent"；没有就是 " round=1"

            _f.write(f"\n=== {_dt.datetime.now().isoformat()}{tag} ===\n")  # 写入分隔行，包含当前时间和轮次信息
            # 例：=== 2026-07-08T10:30:00.123456 round=1_sent ===

            _f.write(_json.dumps(messages, ensure_ascii=False, indent=2))  # 把消息列表转为格式化的 JSON 字符串写入文件
            # ensure_ascii=False 表示中文不会被转义成 \uXXXX
            # indent=2 表示 JSON 缩进 2 个空格，方便阅读

            _f.write("\n")  # 末尾加一个换行，分隔不同的日志记录
    except Exception:
        pass


# ===== Token 估算（基于 tiktoken） =====

@lru_cache(maxsize=1)
def _get_token_encoder():
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """估算文本 token 数。"""
    try:
        enc = _get_token_encoder()
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        return len(text) // 2


def _count_message_tokens(m: dict) -> int:
    """估算一条消息的 token 数。"""
    content = m.get("content", "") or ""
    base = 4
    if isinstance(content, str):
        return base + _count_tokens(content)
    return base + _count_tokens(str(content))


# ===== 工具结果持久化 =====

_TOOL_RESULTS_DIR = ".tool_results"
_PREVIEW_CHARS = 200
_MAX_PERSIST_CHARS = 2000  # 超过此长度的工具结果写入文件


def _persist_tool_result(session_id: str, tool_name: str, content: str) -> str:
    """将过长的工具结果写入文件，返回引用字符串。"""
    if len(content) <= _MAX_PERSIST_CHARS:
        return content  # 不长，直接返回

    try:
        work_dir = Path(conf.data_dir) / _TOOL_RESULTS_DIR / (session_id or "default")
        work_dir.mkdir(parents=True, exist_ok=True)

        # 用 MD5 去重，避免同一结果重复存多份
        digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        path = work_dir / f"{tool_name}_{digest}.txt"

        if not path.exists():
            path.write_text(content, encoding="utf-8")
            # 清理过期文件（保留最近 50 个）
            files = sorted(work_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[50:]:
                old.unlink(missing_ok=True)

        preview = content[:_PREVIEW_CHARS].replace("\n", " ")
        reference = (
            f"[工具结果已保存至 {path}]\n"
            f"原始长度: {len(content)} 字符, 预览: {preview}..."
        )
        logger.debug(f"工具结果持久化: {tool_name} ({len(content)} chars → {path.name})")
        return reference
    except Exception as e:
        logger.warning(f"工具结果持久化失败: {e}, 返回原始内容")
        return content


# ===== RAGSystem 主类 =====
class RAGSystem:
    """RAG 系统的核心入口，管理 LLM 客户端、向量库、工具注册表和工作流路由。

    整体流程：
      generate_answer(query)  # 用户调用这个方法来问问题
        └─ _build_system_message()          → 组装 system prompt（identity + 时间 + 任务 + 风格）
        # 第一步：构造系统消息，告诉 AI 它是什么身份、当前时间、有什么任务、用什么风格回答
        └─ workflow_router.match()           → 匹配对应的工作流并注入 system prompt
        # 第二步：根据用户问题匹配预设的工作流（如"股票分析"流程）
        └─ AgentState 初始化                 → 封装 messages、分区、迭代限制
        # 第三步：创建状态管理器，记录消息列表、知识库分区、最大轮次等信息
        └─ _run_tool_loop(state)            → 非流式：工具循环直到 LLM 不再调用工具
        # 第四步（非流式）：进入工具调用循环，直到 LLM 不再需要调用工具
           └─ 循环内：LLM → tool_calls → 并发执行 → 结果回灌 → 重复
           # 循环流程：询问 LLM → LLM 要求调用工具 → 并发执行工具 → 结果放回消息 → 再问 LLM
           └─ 达上限时：注入强制结束指令，生成最终回答
           # 如果循环次数太多达到上限，强制 LLM 基于已有信息生成答案
        └─ _run_tool_loop_stream(state)     → 流式：同上 + 逐 token yield + status 事件
        # 第四步（流式）：同上，但逐字返回结果，适合前端实时展示
    """

    # ===== 构造函数：初始化 RAG 系统的所有组件 =====
    def __init__(
        self,
        chat_model: Optional[str] = None,         # 对话模型名称，如 "gpt-4o"，不传就用配置文件里的
        embedding_model: Optional[str] = None,    # 向量化模型名称，如 "text-embedding-3-small"
        embedding_dim: Optional[int] = None,      # 向量维度，如 1536
        prompts_dir: Optional[str] = None,        # 提示词模板目录（单个目录）
        prompts_dirs: Optional[List[str]] = None, # 提示词模板目录（多个目录）
        data_store: Optional[object] = None,      # 数据存储对象，用于保存额外数据
    ):
        # —— 模型配置：如果未传入则从 global conf 读取默认值 ——
        self.chat_model = chat_model or conf.chat_model  # 设置对话模型名称，如果没传就用全局配置的默认值
        # chat_model 是 LLM 对话模型的名字，比如 "gpt-4o-mini" 或 "qwen-max"
        self.embedding_model = embedding_model or conf.openai_embedding_model  # 设置向量模型名称，如果没传用全局配置
        # embedding_model 是把文本转成向量的模型名字
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim  # 设置向量维度，如果没传用全局配置
        # embedding_dim 是向量的长度，比如 1536 或 1024
        self.data_store = data_store  # 保存数据存储对象，这是一个可选的持久化存储组件

        # —— prompts 目录解析：支持单目录 / 多目录，默认为 backend/prompts/{,style/} ——
        if prompts_dirs:  # 如果传了多目录列表
            dirs = prompts_dirs  # 直接使用传入的目录列表
        elif prompts_dir:  # 如果只传了单目录
            dirs = [prompts_dir]  # 把单目录包成列表
        else:  # 如果都没传，使用默认目录
            dirs = [  # 默认目录列表
                os.path.join(_BACKEND_ROOT, "prompts"),        # backend/prompts/ 目录
                os.path.join(_BACKEND_ROOT, "prompts", "style"),  # backend/prompts/style/ 目录（回答风格模板）
            ]
        self.context_builder = ContextBuilder(dirs)  # 创建 ContextBuilder 实例，用于加载和提供提示词模板
        # ContextBuilder 会扫描这些目录，加载所有 prompt 模板文件

        # —— LLM 客户端（对话 / 工具调用） ——
        self.client = OpenAIClient(  # 创建 OpenAI API 客户端
            api_key=conf.openai_api_key,    # API 密钥，从全局配置读取
            base_url=conf.openai_base_url,  # API 地址，比如 https://api.openai.com 或者阿里云兼容地址
            timeout=conf.openai_timeout,    # 请求超时时间（秒）
            max_retries=conf.openai_max_retries,  # 请求失败时最大重试次数
        )

        # —— Embedding 客户端：如果 endpoint 与 chat 相同则复用，否则独立创建 ——
        if conf.embedding_api_key == conf.openai_api_key and conf.embedding_base_url == conf.openai_base_url:
            # 判断：如果向量化的 API 密钥和地址和聊天 API 完全一样
            self.embed_client = self.client  # 复用同一个客户端，节省资源
            logger.debug("Embedding 端与 chat 端共用同一 OpenAI 客户端")
        else:  # 如果配置不同（比如用了不同的 API 服务商）
            self.embed_client = OpenAIClient(  # 单独创建一个独立的 embedding 客户端
                api_key=conf.embedding_api_key,    # 使用独立的 API 密钥
                base_url=conf.embedding_base_url,  # 使用独立的 API 地址
                timeout=conf.openai_timeout,       # 使用相同的超时设置
                max_retries=conf.openai_max_retries,  # 使用相同的重试设置
            )
            logger.debug(f"Embedding 端使用独立客户端: base_url={conf.embedding_base_url}")

        # —— 向量存储：用于语义检索（RAG 的核心检索组件） ——
        self.vector_store = VectorStore(  # 创建向量存储实例
            client=self.embed_client,          # 传入 embedding 客户端，用于将文本转成向量
            embedding_model=self.embedding_model,  # 传入向量化模型名称
            embedding_dim=self.embedding_dim,      # 传入向量维度
        )

        # —— 工作流路由器：根据 query 关键词匹配预设 workflow（如 USstocks、Autoplan） ——
        self.workflow_router = WorkflowRouter(  # 创建工作流路由器实例
            os.path.join(_BACKEND_ROOT, "prompts")  # 传入 prompts 目录路径，路由器会扫描目录下的 workflow 配置
        )

        logger.info(  # 打印 RAG 系统初始化完成的日志
            f"RAG agent 就绪, chat_model={self.chat_model}, "  # 打印当前使用的对话模型
            f"工具={[t['function']['name'] for t in registry.schemas]}"  # 列出所有已注册的工具名称
        )

        # —— PDF 解析方案日志（MinerU vs OCRPDFLoader） ——
        if conf.mineru_api_key:  # 如果配置了 MinerU 的 API 密钥
            tok_preview = f"{conf.mineru_api_key[:12]}...({conf.mineru_token_name})"  # 截取 API 密钥前 12 位做预览，保护隐私
            logger.debug(f"PDF 解析: MinerU {conf.mineru_model_version}/{conf.mineru_language} token={tok_preview}")
            # 打印日志：使用 MinerU 进行 PDF 解析，显示模型版本、语言和密钥预览
        else:  # 如果没有配置 MinerU 密钥
            logger.debug("PDF 解析: OCRPDFLoader (MinerU token 未配置)")
            # 打印日志：使用 OCRPDFLoader 做 PDF 解析（后备方案）

    # ─── System Message 组装 ───────────────────────

    # ===== 构建系统提示消息 =====
    def _build_system_message(
        self,
        style: Optional[str] = None,                # 回答风格模板名称
    ) -> str:  # 返回值类型是字符串，即拼装好的 system message
        """构造 system message: identity + 可选回答风格。

        style 为 None / "style-default" 时跳过风格注入。
        文档清单不再注入 system message，LLM 通过 list_documents 工具按需获取。
        """
        # —— 注入身份设定文本（identity） ——
        parts = [self.context_builder.identity or ""]  # 获取 AI 的身份设定文本，如果没有则为空字符串
        # context_builder.identity 是从 prompt 模板加载的"AI 角色设定"，比如"你是一个金融助手"
        # 用一个列表来存储所有要拼装的部分

        # —— 注入当前时间, 帮助 LLM 理解 "今年" "最近" "今天" 等时间指代 ——
        from datetime import datetime as _dt  # 导入 datetime 模块，用于获取当前时间
        import time as _time  # 导入 time 模块，用于获取时区信息
        _tz = _time.tzname  # 获取当前系统的时区名称，比如 ('CST', 'CST') 或 ('UTC', 'UTC')
        parts.append(f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} (时区: {_tz[0] if _tz else 'UTC'})")
        # 把当前时间格式化为"2026年07月08日 Wednesday 10:30"的形式添加到消息中
        # 如果获取不到时区信息，默认显示 UTC


        # —— 注入回答风格 ——
        # style 是预先定义好的 prompt 模板（如 "concise"、"detailed"、"friendly"）
        if style and style != "style-default":  # 如果指定了风格且不是默认风格
            skill = self.context_builder.skills.get(style)  # 从 skills 字典中获取对应风格的模板对象
            if skill and skill.template:  # 如果风格存在且模板内容不为空
                parts.append(f"\n\n{skill.template}")  # 将风格模板内容追加到消息中
        return "".join(parts)  # 把列表中的所有字符串拼接在一起，返回完整的 system message

    # ─── 答案生成入口 ───────────────────────────

    # ===== 生成答案的顶层入口方法 =====
    def generate_answer(
        self, query,
        force_retrieve: bool = False,
        stream=False,
        history: list = None,
        partition: str = None,
        style: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_checkpoint: Optional[Callable[[str, dict], None]] = None,
        drain_pending: Optional[Callable[[], list[dict]]] = None,
        emit_event: Optional[Callable[[dict], None]] = None,
    ):
        """生成答案的顶层入口。

        参数:
          query           : 用户当前问题
          force_retrieve  : 是否强制 LLM 必须调用检索工具
          stream          : 是否启用流式输出
          history         : 历史对话列表
          partition       : 知识库分区
          style           : 回答风格模板名称
          cancel_check    : 可选的中断检测函数
        """
        # 每次对话前检查 config.ini 是否被修改，自动热重载（hash 比对，无 I/O 开销）
        conf.reload_if_changed()
        # 重置空响应和 length 恢复重试计数器
        self._empty_retries = 0
        self._length_retries = 0
        # 重置重复外部查询计数（nanobot 模式）
        from .tools import registry as _reg
        _reg.reset_external_lookup_counts()
        logger.debug(f"收到用户查询: {query} (style={style})")

        # —— 第一步：组装 system message ——
        system_msg = self._build_system_message(  # 调用内部方法构建系统提示消息
            style=style,                        # 传入回答风格
        )

        # ── Workflow 渐进式加载（nanobot 模式） ─────────
        # 所有工作流以摘要形式注入 system prompt，LLM 通过 read_workflow 按需获取完整内容
        wf_summaries = self.workflow_router.get_workflow_summaries()
        if wf_summaries:
            system_msg += (
                f"\n\n---\n# 工作流\n"
                f"{wf_summaries}\n"
                f"如需加载完整工作流指令，请调用 read_workflow 工具。"
            )

        # —— 第二步：组装完整的 messages ——
        # 结构：[system, ...历史对话, 当前用户问题]
        messages: List[dict] = [{"role": "system", "content": system_msg}]  # 第一条消息是 system，放刚才拼装的系统提示
        if history:  # 如果有历史对话
            messages.extend(history)  # 把历史对话追加到消息列表中（在 system 之后）
        messages.append({"role": "user", "content": query})  # 最后加上用户当前的问题
        # 最终消息结构：[system 消息, 历史对话 1, 历史对话 2, ..., 当前用户问题]

        # —— 第三步：确定迭代次数上限 ——
        max_iter = conf.max_tool_iter

        # —— 第四步：初始化 AgentState（工具循环的状态管理） ——
        state = AgentState(  # 创建 AgentState 实例，管理工具循环的状态
            messages=messages,        # 传入完整的消息列表
            partition=partition,      # 传入知识库分区
            style=style,              # 传入回答风格
            max_iterations=max_iter,      # 传入最大迭代次数
        )

        # —— 第五步：分发到流式或非流式执行路径 ——
        if stream:
            return self._run_tool_loop_stream(
                state, force_retrieve,
                cancel_check=cancel_check,
                on_checkpoint=on_checkpoint,
                drain_pending=drain_pending,
                emit_event=emit_event,
            )

        return self._run_tool_loop(state, force_retrieve, on_checkpoint=on_checkpoint)

    # ─── 上下文治理 ───────────────────────────

    def _govern_context(self, messages: List[dict]) -> List[dict]:
        """上下文治理流水线：在每次调用 LLM 前清理消息列表。

        nanobot 风格的 5 步治理：
          1. 丢弃孤立 tool_result（没有对应 assistant tool_calls 的）
          2. 补充缺失 tool_result（有 tool_calls 但没有结果的）
          3. 微压缩：将冗长的工具结果替换为一行摘要
          4. 预算控制：截断超过上限的工具结果
          5. 历史裁剪：按字符数裁剪
        """
        # ── 1. 收集所有活跃的 tool_call ID ──
        active_ids = set()
        for m in messages:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    if isinstance(tc, dict):
                        active_ids.add(tc.get("id", ""))

        # ── 2. 过滤消息 ──
        governed = []
        for m in messages:
            role = m.get("role", "")
            # 丢弃孤立 tool_result（不在活跃 ID 中的）
            if role == "tool" and m.get("tool_call_id"):
                if m["tool_call_id"] not in active_ids:
                    continue

            # ── 3. 微压缩：verbose 工具结果替换为一行的摘要 ──
            if role == "tool":
                content = m.get("content", "") or ""
                if len(content) > 2000:
                    # 取前 200 字符作为摘要
                    summary = content[:200].replace("\n", " ") + "...(已压缩)"
                    m = dict(m)  # 复制避免修改原始
                    m["content"] = f"[工具返回 {len(content)} 字符，已压缩]\n{summary}"

            governed.append(m)

        # ── 4. Backfill：补充缺失的 tool_result ──
        # 如果 assistant 有 tool_calls 但没有对应的 tool 消息（中断场景），
        # 注入合成错误结果，防止 LLM 以为工具还没执行
        backfill_needed = {}
        for m in governed:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else ""
                    if tc_id:
                        backfill_needed[tc_id] = tc

        # 移除已有结果的 ID
        for m in governed:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                backfill_needed.pop(m["tool_call_id"], None)

        # 为剩余未完成的调用补结果
        for tc_id, tc in backfill_needed.items():
            tc_name = tc.get("name", "") if isinstance(tc, dict) else ""
            governed.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"(工具 {tc_name} 在上一轮执行后被中断，结果不可用。请根据已有信息继续。)",
            })

        # ── 5. Tool Result Budget：单个工具结果上限（默认 8000 字符） ──
        MAX_TOOL_CHARS = getattr(conf, 'max_tool_result_chars', 8000)
        for i, m in enumerate(governed):
            if m.get("role") == "tool":
                content = m.get("content", "") or ""
                if len(content) > MAX_TOOL_CHARS:
                    truncated = content[:MAX_TOOL_CHARS]
                    governed[i] = dict(m)
                    governed[i]["content"] = truncated + "\n\n...(工具结果过长，已截断)..."
                    logger.debug(f"工具结果预算截断: {len(content)} → {MAX_TOOL_CHARS} 字符")

        # ── 6. 调用截断方法做最终裁剪 ──
        return self._truncate_messages(governed)

    # ===== 上下文窗口裁剪：基于 token 估算 =====
    def _truncate_messages(self, messages: List[dict]) -> List[dict]:
        """按 token 预算裁剪消息。保留首尾，裁剪中间过长工具结果。

        阈值：conf.context_window_tokens 的 80%（留出 20% 给输出）。
        """
        budget = int(conf.context_window_tokens * 0.8)
        total = sum(_count_message_tokens(m) for m in messages)
        if total <= budget:
            return messages

        logger.warning(
            f"上下文超预算: ~{total} tokens > {budget} "
            f"(context_window_tokens={conf.context_window_tokens}), 截断中..."
        )

        new_messages = []
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None

        for idx, m in enumerate(messages):
            # system 始终完整保留
            if idx == 0 and system_msg:
                new_messages.append(m)
                continue
            # 最后一条始终保留
            if idx == len(messages) - 1:
                new_messages.append(m)
                continue

            # 中间 tool 消息过长时截断（阈值：3000 token）
            if m.get("role") == "tool":
                content = m.get("content", "") or ""
                tok = _count_tokens(content)
                if tok > 3000:
                    # 保留首尾各 1500 字符，中间替换为摘要
                    truncated = content[:1500] + (
                        f"\n...(工具结果过长，原 ~{tok} tokens，已截断)...\n"
                    ) + content[-1500:]
                    m_copy = m.copy()
                    m_copy["content"] = truncated
                    new_messages.append(m_copy)
                    continue

            new_messages.append(m)

        after = sum(_count_message_tokens(m) for m in new_messages)
        logger.debug(f"截断后: ~{after} tokens ({int((1-after/total)*100)}% 压缩)")
        return new_messages

    # ─── Tool-call 循环 (非流式) ─────────────────

    # ===== 非流式工具调用主循环 =====
    def _run_tool_loop(self, state: AgentState, force_retrieve: bool,
                       on_checkpoint: Optional[Callable[[str, dict], None]] = None) -> str:
        """非流式工具调用主循环。

        循环逻辑（LLM 驱动的工具调用循环）：
          1. LLM 收到完整的 messages（含历史和之前的工具结果）  # LLM 看到所有对话和工具返回结果
          2. LLM 决定调用哪些工具 → 返回 tool_calls 列表  # LLM 自己决定要不要查资料、查什么
          3. 如果 tool_calls 为空：LLM 已准备好最终答案，直接返回  # LLM 不需要查了，直接回答
          4. 如果 tool_calls 包含 ask_user_for_clarification：提前终止，返回澄清问题  # LLM 觉得信息不够，反问用户
          5. 否则：并发执行所有工具调用（ThreadPoolExecutor），结果写回 state.messages  # 同时执行多个工具
          6. 回到步骤 1，直到达到 max_iterations  # 重复，把工具结果给 LLM，看它是否还需要更多

        达上限处理：
          - 注入一条"不再允许调工具"的 user 消息  # 强制告诉 LLM 不能再调工具了
          - 调用纯 chat（不带 tools）让 LLM 基于已有信息生成最终答案  # 没有工具可用，LLM 只能直接回答
        """
        tool_choice = "required" if force_retrieve else "auto"  # 设置工具调用策略：required 表示必须调，auto 表示让 LLM 自己决定

        # while 循环直到 should_continue() 返回 False（达上限或主动 break）
        while state.should_continue():  # 检查是否应该继续循环（没达到上限且没有被终止）

            # 发送前裁剪（避免上下文窗口溢出）
            truncated_messages = self._govern_context(state.messages)  # 上下文治理：去孤/压缩/裁剪

            # 记录实际发送给 LLM 的输入（仅在最后迭代时记录，避免重复）
            if state.iteration == state.max_iterations - 1:
                _log_input(truncated_messages, round=state.iteration, suffix="_final")

            # —— 1. LLM 调用（不带流式） ——
            try:
                resp = self.client.chat_with_tools(
                    messages=truncated_messages,
                    model=self.chat_model,
                    tools=registry.schemas,
                    tool_choice=tool_choice,
                    stream=False,
                    temperature=0.7,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.iteration}): {e}")
                return "抱歉，模型处理请求时发生了错误。"

            # —— 2. 终止条件 ——
            if not resp["tool_calls"]:
                content = (resp.get("content") or "").strip()
                if not content:
                    retries = getattr(self, "_empty_retries", 0)
                    if retries < 2:
                        self._empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({retries+1}/2)")
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        continue
                length_retries = getattr(self, "_length_retries", 0)
                if resp.get("finish_reason") == "length" and content and length_retries < 3:
                    self._length_retries = length_retries + 1
                    logger.warning(f"LLM 响应被截断 (length), 自动续写 ({length_retries+1}/3)")
                    state.messages.append({"role": "assistant", "content": content})
                    state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                    continue
                return content

            logger.debug(f"tool-loop {state.iteration} LLM 请求 {len(resp['tool_calls'])} 个工具调用")
            state.add_assistant_response(resp["content"], resp["tool_calls"])

            # —— 3. 执行工具（共享一个线程池，避免反复创建开销） ——
            import concurrent.futures

            def _dispatch_task(tc):
                try:
                    res = registry.dispatch(
                        tc["name"], tc["arguments"],
                        ctx=ToolContext(
                            vector_store=self.vector_store,
                            partition=state.partition,
                            data_store=self.data_store,
                            session_id=state.partition or "",
                            subagent_manager=getattr(self, "subagent_manager", None),
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    # 工具结果持久化：过长结果写入文件
                    if isinstance(res, str):
                        res = _persist_tool_result(state.partition or "", tc["name"], res)
                    return tc["id"], res
                except Exception as e:
                    logger.error(f"工具 {tc['name']} 执行发生严重异常: {e}", exc_info=True)
                    return tc["id"], f"(系统提示: 执行工具 {tc['name']} 时发生了严重错误: {e}，请尝试使用其他工具或根据现有信息回答)"

            from .tools.registry import ToolRegistry
            batches = ToolRegistry.partition_tool_batches(resp["tool_calls"])
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(resp["tool_calls"])
            ) as executor:
                for batch in batches:
                    futures = [executor.submit(_dispatch_task, tc) for tc in batch]
                    for future in concurrent.futures.as_completed(futures):
                        tc_id, result = future.result()
                        state.add_tool_result(tc_id, result)

            # —— 4. 提前退出检查：LLM 需要向用户提问 ——
            for tc in resp["tool_calls"]:
                if tc["name"] == "ask_user_for_clarification":
                    import json
                    try:
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")
                    except:
                        q = "我需要您提供更多背景信息。"
                    logger.debug("提前中断工具循环：LLM 需要澄清")
                    return q

            # 首轮过后不再强制 tool_choice
            tool_choice = "auto"

        # ── 达上限: 用已收集的信息生成最终答案 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")
        return self._finalize_answer(state.messages, stream=False)

    # ─── 共享：最终答案生成（非流式 + 流式复用） ─────────

    _FORCE_STOP_MSG = (
        "（本轮工具调用额度已用完。请仅根据已有对话和工具结果，"
        "直接给出最终回答。不要请求或调用任何工具。"
        "如果信息不足以做出完整回答，如实说明已获取的信息和仍缺少的部分。）"
    )
    _FALLBACK_MSG = "我已尽力根据已有信息完成分析。如需更深入的回答，请补充更多细节或分步骤提问。"

    def _finalize_answer(self, messages, stream=False, emit_event=None):
        """强制 LLM 基于已有信息生成最终答案（无工具可用）。"""
        final = list(messages)
        final.append({"role": "user", "content": self._FORCE_STOP_MSG})

        try:
            if stream:
                events = self.client.chat(
                    messages=final, model=self.chat_model,
                    stream=True, temperature=0.7,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
                has_content = False
                for text in events:
                    has_content = True
                    if emit_event:
                        emit_event({"type": "token", "text": text})
                    yield {"type": "token", "text": text}
                if not has_content:
                    logger.warning("最终回答为空，使用回退消息")
                    if emit_event:
                        emit_event({"type": "token", "text": self._FALLBACK_MSG})
                    yield {"type": "token", "text": self._FALLBACK_MSG}
            else:
                resp = self.client.chat(
                    messages=final, model=self.chat_model,
                    stream=False, temperature=0.7,
                    max_tokens=conf.max_output_tokens,
                    reasoning_effort=conf.chat_reasoning_effort,
                )
                if not resp or not resp.strip():
                    logger.warning("最终回答为空，使用回退消息")
                    return self._FALLBACK_MSG
                return resp
        except Exception as e:
            logger.error(f"最终回答生成失败: {e}")
            if stream:
                yield {"type": "token", "text": "\n\n抱歉，生成最终回答时发生了错误。"}
            else:
                return "抱歉，生成最终回答时发生了错误。"

    # ─── Tool-call 循环 (流式) ─────────────────

    # ===== 流式工具调用主循环（生成器函数） =====
    def _run_tool_loop_stream(self, state: AgentState, force_retrieve: bool,
                               cancel_check: Optional[Callable[[], bool]] = None,
                               on_checkpoint: Optional[Callable[[str, dict], None]] = None,
                               drain_pending: Optional[Callable[[], list[dict]]] = None,
                               emit_event: Optional[Callable[[dict], None]] = None):
        """流式生成器: 逐 token 产出, 中间穿插 status 事件。

        与非流式版本的核心逻辑相同，但：
          - 使用 Python generator（yield）逐块返回  # 每次 yield 返回一小块数据
          - 产生 "token" 事件用于前端逐字展示  # 前端可以逐字显示 AI 的回答
          - 产生 "status" 事件用于前端显示"思考中"、"调用工具"、"工具完成"等状态  # 前端可以显示各种状态

        Yield 格式:
          {"type": "token", "text": "..."}  # 输出文本片段
          {"type": "status", "status": "thinking"}  # AI 正在思考
          {"type": "status", "status": "calling_tool", "tool": "search_knowledge_base", "args": [...]}  # AI 正在调工具
          {"type": "status", "status": "tool_result", "tool": "search_knowledge_base", "chunks": 5}  # 工具执行完成
        """
        tool_choice = "required" if force_retrieve else "auto"  # 设置工具调用策略：required 强制调用，auto 让 LLM 自己决定

        # 使用 for 循环（range 方式）替代 while，上限即为 max_iterations
        for it in range(state.max_iterations):  # 循环最多 max_iterations 次
            # ä¸­æ­æ£æ¥
            if cancel_check and cancel_check():
                logger.info("工具循环被中断")
                # 保存检查点，允许下次恢复
                if on_checkpoint and state.messages:
                    on_checkpoint("tools_completed", {
                        "iteration": it,
                        "model": self.chat_model,
                        "pending_calls": tool_calls if tool_calls else None,
                    })
                return
        
            accumulated_content = ""  # 用于累积本次 LLM 回复的文本内容
            tool_calls: List[dict] = []  # 用于存储 LLM 请求的工具调用列表

            # —— 通知前端开始思考 ——
            if emit_event: emit_event({"type": "status", "status": "thinking"})
            yield {"type": "status", "status": "thinking"}  # 发送状态事件给前端：AI 正在思考中

            # 发送前裁剪
            truncated_messages = self._truncate_messages(state.messages)  # 裁剪过长的消息，控制上下文窗口

            # 记录实际发送给 LLM 的输入（截断后）
            _log_input(truncated_messages, round=it, suffix="_sent")  # 记录实际发送的消息到日志

            # —— 1. 流式调用 LLM ——
            # 返回的是事件生成器：包含 "content"（文本 token）和 "tool_calls"（工具调用）
            try:  # 尝试调用 LLM
                events = self.client.chat_with_tools(  # 调用 LLM（带工具），返回事件生成器
                    messages=truncated_messages,  # 传入裁剪后的消息列表
                    model=self.chat_model,        # 指定模型
                    tools=registry.schemas,       # 传入可用工具的定义
                    tool_choice=tool_choice,      # 工具调用策略
                    stream=True,                  # 流式模式，逐块返回
                    temperature=0.7,              # 温度参数
                    max_tokens=conf.max_output_tokens,  # 最大输出 token
                    reasoning_effort=conf.chat_reasoning_effort,  # 推理努力程度
                )
                for ev in events:  # 遍历 LLM 返回的事件流
                    # 每次迭代检查中断
                    if cancel_check and cancel_check():
                        logger.info("token流被中断")
                        return
                    if ev["type"] == "content":  # 如果是文本内容事件
                        accumulated_content += ev["text"]  # 累积文本内容
                        if emit_event: emit_event({"type": "token", "text": ev["text"]})
                        yield {"type": "token", "text": ev["text"]}  # 把文本逐块发给前端
                    elif ev["type"] == "reasoning":  # 推理过程（如 DeepSeek R1 的思考链）
                        if emit_event: emit_event({"type": "reasoning", "text": ev["text"]})
                        yield {"type": "reasoning", "text": ev["text"]}
                    elif ev["type"] == "tool_calls":  # 如果是工具调用事件
                        tool_calls = ev["calls"]  # 提取工具调用列表
                        # 保存 awaiting_tools 检查点
                        if on_checkpoint:
                            on_checkpoint("awaiting_tools", {
                                "iteration": it,
                                "pending_calls": tool_calls,
                            })
                    elif ev["type"] == "finish" and ev.get("reason") == "length":
                        if accumulated_content.strip():
                            lr = getattr(self, "_length_retries", 0)
                            if lr < 3:
                                self._length_retries = lr + 1
                                state.messages.append({"role": "assistant", "content": accumulated_content})
                                state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                                accumulated_content = ""
                                tool_choice = "auto"
            except Exception as e:  # 如果流式调用出错
                logger.error(f"LLM tool 流式调用失败 (round {it}): {e}")
                # 保存检查点，让下次查询可以恢复已完成的工具结果
                if on_checkpoint and state.messages:
                    on_checkpoint("tools_completed", {
                        "iteration": it,
                        "model": self.chat_model,
                        "pending_calls": tool_calls if tool_calls else None,
                    })
                yield {"type": "token", "text": "\n\n抱歉，模型处理请求时发生了错误。"}
                return

            # —— 2. 终止条件：无工具调用，流式答案已全部吐出，直接结束 ——
            if not tool_calls:  # 如果 LLM 没有要求调用任何工具
                if not accumulated_content.strip():
                    # 空内容自动重试（最多 2 次）
                    retries = getattr(self, "_empty_retries", 0)
                    if retries < 2:
                        self._empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({retries+1}/2)")
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        if emit_event: emit_event({"type": "status", "status": "retrying"})
                        yield {"type": "status", "status": "retrying"}
                        continue
                return  # 终态: 无工具调用, 已流完答案，直接结束生成器

            logger.debug(f"tool-loop {it} LLM 请求 {len(tool_calls)} 个工具调用")
            state.add_assistant_response(accumulated_content, tool_calls)  # 把 LLM 的回复和工具调用记录到状态中

            import concurrent.futures  # 导入并发执行模块

            # —— 3. 单个工具调度（流式版本多返回 tool_info 用于前端展示） ——
            def _dispatch_task_stream(tc):  # 定义一个内部函数，负责执行单个工具（流式版本）
                import json as _json  # 导入 JSON 解析模块
                tool_info = {"tool": tc["name"]}  # 创建工具信息字典，包含工具名称
                # 解析参数，提取关键信息用于前端展示
                try:  # 尝试解析工具参数
                    _args = _json.loads(tc.get("arguments") or "{}")  # 将参数字符串解析为字典
                    if "queries" in _args:  # 如果参数中包含 queries 字段
                        tool_info["query"] = _args["queries"]  # 提取查询关键词，用于前端展示
                    if "filename" in _args:  # 如果参数中包含 filename 字段
                        tool_info["filename"] = _args["filename"]  # 提取文件名，用于前端展示
                    if "query" in _args:  # 如果参数中包含 query 字段
                        tool_info["query"] = [_args["query"]]  # 包装成列表格式
                except Exception:  # 如果解析失败
                    pass  # 忽略，不影响工具执行

                # 防重检测与单工具超限
                try:  # 尝试执行工具
                    res = registry.dispatch(  # 通过注册表调度工具
                        tc["name"], tc["arguments"],  # 工具名称和参数
                        ctx=ToolContext(  # 工具执行上下文
                            vector_store=self.vector_store,  # 向量存储
                            partition=state.partition,        # 知识库分区
                            data_store=self.data_store,       # 数据存储
                            session_id=state.partition or "",
                            subagent_manager=getattr(self, "subagent_manager", None),
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    # 工具结果持久化
                    if isinstance(res, str):
                        res = _persist_tool_result(state.partition or "", tc["name"], res)
                except Exception as e:  # 工具执行异常
                    logger.error(f"工具 {tc['name']} 异常: {e}", exc_info=True)
                    res = f"(系统提示: 执行工具 {tc['name']} 发生错误: {e}，请尝试其他策略)"  # 构造错误信息

                return tc["id"], tool_info, res  # 返回工具调用 ID、信息字典和执行结果

            # —— 4. 先通知前端即将调用的所有工具（带进度计数） ——
            _tool_total = len(tool_calls)
            for _tool_idx, tc in enumerate(tool_calls, start=1):
                 import json as _json
                 tmp_info = {"tool": tc["name"], "total": _tool_total}
                 try:
                     _args = _json.loads(tc.get("arguments") or "{}")
                     if "queries" in _args:
                         tmp_info["query"] = _args["queries"]
                     if "filename" in _args:
                         tmp_info["filename"] = _args["filename"]
                     if "query" in _args:
                         tmp_info["query"] = [_args["query"]]
                 except Exception:
                     pass
                 if emit_event: emit_event({"type": "status", "status": "calling_tool", **tmp_info})
                 yield {"type": "status", "status": "calling_tool", **tmp_info}

            # —— 5. 按并发安全性分批执行工具（共享线程池，避免反复创建开销） ——
            from .tools.registry import ToolRegistry
            batches = ToolRegistry.partition_tool_batches(tool_calls)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(tool_calls)
            ) as executor:
                for batch in batches:
                    futures = [executor.submit(_dispatch_task_stream, tc) for tc in batch]
                    for future in concurrent.futures.as_completed(futures):
                        tc_id, tool_info, result = future.result()
                        state.add_tool_result(tc_id, result)

                        import re as _re
                        if tool_info.get("tool") == "search_knowledge_base":
                            _cnt = len(_re.findall(r"【片段 \d+", result))
                            if _cnt:
                                tool_info["chunks"] = _cnt
                        elif tool_info.get("tool") == "web_search":
                            _cnt = len(_re.findall(r"\[搜索结果 \d+\]", result))
                            if _cnt:
                                tool_info["chunks"] = _cnt
                        if emit_event: emit_event({"type": "status", "status": "tool_result", **tool_info})
                        yield {"type": "status", "status": "tool_result", **tool_info}
                        if on_checkpoint:
                            on_checkpoint("tools_completed", {
                                "iteration": it,
                                "tool_name": tool_info.get("tool", ""),
                            })
            # —— 6. 提前退出检查：流式模式下 ——
            for tc in tool_calls:  # 遍历所有工具调用
                if tc["name"] == "ask_user_for_clarification":  # 如果是"向用户提问"工具
                    import json  # 导入 JSON 模块
                    try:  # 尝试解析问题
                        q = json.loads(tc.get("arguments", "{}")).get("question", "我需要更多信息。")  # 提取 LLM 想问用户的问题
                    except:  # 解析失败
                        q = "我需要您提供更多背景信息。"  # 使用默认文本
                    logger.debug("流式提前中断工具循环：LLM 需要澄清")
                    yield {"type": "token", "text": "\n\n" + q}  # 把问题作为文本输出给前端
                    return  # 终止生成器

            # 首轮过后不再强制调用工具
            tool_choice = "auto"  # 第一轮之后恢复为自动模式，让 LLM 自己决定

            # 中间注入：检查是否有子 Agent 结果（最多 5 轮，防止无限注入）
            _MAX_INJECTION_CYCLES = 5
            _injection_round = 0
            if drain_pending:
                pending = drain_pending()
                while pending and _injection_round < _MAX_INJECTION_CYCLES:
                    _injection_round += 1
                    for msg in pending:
                        state.messages.append(msg)
                        if msg.get("role") == "user":
                            logger.debug(f"中间注入 ({_injection_round}): {msg.get('content', '')[:60]}...")
                    pending = drain_pending()

        # ── 达上限: 用已收集的信息生成最终答案（共享 _finalize_answer） ──
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}, 利用已有信息生成最终回答")
        yield from self._finalize_answer(state.messages, stream=True, emit_event=emit_event)


# ===== 模块入口：直接运行时执行简单的测试 =====
if __name__ == "__main__":  # 如果直接运行这个文件（而不是被导入）
    rag = RAGSystem()  # 创建一个 RAGSystem 实例
    res = rag.generate_answer("你好", force_retrieve=False)  # 用这个实例生成一个简单回答
    print(res)  # 打印结果到控制台
