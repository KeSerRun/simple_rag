"""RAG agent: tool-calling 循环驱动 LLM 自主决策检索、拆解查询、生成最终答案。

流程:
  1. 构建 system message（身份 + 时间 + 风格 + 工作流 + 目标）
  2. 组装 messages: [system, ...history, user(query)]
  3. LLM 决定是否调工具 → 工具结果回灌 messages（循环）
  4. 无更多工具调用 → 输出最终答案

AgentState 封装循环中的 messages / 轮次 / 上下文参数。
"""
# ===== 导入标准库模块 =====
import hashlib
import json
import os  # 导入操作系统模块，用于文件路径操作（拼接路径、获取目录等）
import threading
from pathlib import Path

from typing import Callable, List, Optional

# —— 配置与日志 ——  （这两个是项目自己的基础模块）
from base.config import conf          # 全局配置（模型名、超时、token 限制等）
# conf 是一个全局配置对象，里面保存了所有模型名称、API 密钥、超时时间等配置项
from base.logger import logger, log_llm_input        # 结构化日志
# logger 是项目的日志工具，用于在控制台输出带时间戳和级别的日志信息

# —— RAG 核心组件 ——  （RAG 系统的三个核心模块）
from rag.vector_store import VectorStore  # 本地向量存储，用于语义搜索
# VectorStore 负责把文本转成向量，并支持根据语义相似度搜索最相关的内容
from base.llm_client import OpenAIClient      # OpenAI 兼容的 API 客户端（流式 / 非流式）
# OpenAIClient 封装了调用 OpenAI 或兼容 API（如阿里云通义千问）的细节，支持流式和非流式两种模式

# —— Agent 内部组件 ——  （Agent 自己的子模块）
from .context_builder import ContextBuilder  # 从 prompts 目录加载 identity / 风格模板
# ContextBuilder 负责从 prompts 文件夹读取"AI 身份设定"和"回答风格模板"
from .state import AgentState                # 工具循环的状态机（迭代计数、消息列表、工具调用记录）
# AgentState 负责管理 tool loop 的状态，包括已经轮了多少次、消息列表、调用了哪些工具等
from .tools.registry import ToolContext            # 工具执行时的上下文（向量库、分区、数据存储）
# ToolContext 是执行工具时传给工具的上下文对象，包含向量库、知识库分区、数据存储等信息
from .tools import registry                  # 全局工具注册表，管理所有可用工具的 schema 和 dispatch
# registry 是一个全局的工具注册表，记录了所有可用的工具（如搜索知识库、网络搜索等）
from .workflow import WorkflowRouter  # 路由引擎：根据用户问题匹配预设工作流
# WorkflowRouter 负责根据用户的问题内容匹配预设的工作流（比如股票查询走"金融分析"流程）

# ===== 全局路径和日志配置 =====
# 后端根目录（本项目 backend/ 目录的绝对路径）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 这行代码通过两次 dirname 从当前文件路径向上跳两级，得到 backend/ 目录的绝对路径
# 比如：文件在 backend/agent/rag_system.py → 得到 backend/


# ===== 日志记录辅助函数 =====


# ===== 字符数估算 =====

def _count_message_chars(m: dict) -> int:
    """返回一条消息的字符数。"""
    content = m.get("content", "") or ""
    return len(content) if isinstance(content, str) else len(str(content))


# ===== 工具结果持久化 =====

_TOOL_RESULTS_DIR = Path("json_store") / "tool_results"


def _persist_tool_result(session_id: str, tool_name: str, content: str) -> str:
    """将过长的工具结果写入文件，返回引用字符串。"""
    if len(content) <= conf.persist_threshold:
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

        preview = content[:conf.preview_chars].replace("\n", " ")
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
    """RAG 系统核心入口，管理 LLM 客户端、向量库、工具注册表和工作流路由。

    整体流程:
      generate_answer(query)
        └─ _build_system_message()    → system prompt（身份 + 时间 + 风格）
        └─ Workflow 注入              → 指定工作流或 Auto 摘要
        └─ AgentState 初始化          → 封装 messages、分区、迭代限制
        └─ _run_tool_loop()           → 非流式：工具循环直到 LLM 不再调用工具
           └─ 循环内：LLM → tool_calls → 并发执行 → 结果回灌 → 重复
           └─ 达上限时：保存中断状态，用户可回复「继续」恢复
        └─ _run_tool_loop_stream()    → 流式：同上 + 逐 token yield + status 事件
    """

    # ===== 构造函数：初始化 RAG 系统的所有组件 =====
    def __init__(
        self,
        chat_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        prompts_dir: Optional[str] = None,
        prompts_dirs: Optional[List[str]] = None,
        data_store: Optional[object] = None,
    ):
        # —— 模型配置 ——
        self.chat_model = chat_model or conf.chat_model
        self.embedding_model = embedding_model or conf.openai_embedding_model
        self.embedding_dim = embedding_dim or conf.openai_embedding_dim
        self.data_store = data_store

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
        session_id: str = "default",
        style: Optional[str] = None,
        workflow_name: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_checkpoint: Optional[Callable[[str, dict], None]] = None,
        drain_pending: Optional[Callable[[], list[dict]]] = None,
        emit_event: Optional[Callable[[dict], None]] = None,
        data_store: Optional[object] = None,
    ):
        """生成答案的顶层入口。

        参数:
          query           : 用户当前问题
          force_retrieve  : 是否强制 LLM 必须调用检索工具
          stream          : 是否启用流式输出
          history         : 历史对话列表
          partition       : 知识库分区
          style           : 回答风格模板名称
          workflow_name   : 工作流名称（None=Auto）
          cancel_check    : 可选的中断检测函数
        """
        # 每次对话前检查 config.ini 是否被修改，自动热重载（hash 比对，无 I/O 开销）
        conf.reload_if_changed()
        # 重置重复外部查询计数（nanobot 模式）
        from .tools import registry as _reg
        _reg.reset_external_lookup_counts()
        logger.debug(f"收到用户查询: {query} (style={style})")

        # —— 第零步：检测是否要继续上次中断的工具循环 ——
        interrupted = self._load_interrupted_state(session_id)
        if interrupted and self._is_continue_request(query):
            logger.info(f"检测到继续请求，恢复中断的工具循环: session={session_id}")
            self._clear_interrupted_state(session_id)
            saved_system_msg = interrupted.get("system_msg", "")
            saved_messages = interrupted.get("messages", [])
            restored_messages = [{"role": "system", "content": saved_system_msg}]
            for m in saved_messages:
                if m.get("role") != "system":
                    restored_messages.append(m)
            restored_messages.append({
                "role": "user",
                "content": "继续之前的任务，不要重新开始，基于已有工具结果继续工作。可继续调用所需工具。",
            })
            state = AgentState(
                messages=restored_messages,
                partition=partition,
                session_id=session_id,
                style=style,
                max_iterations=conf.max_tool_iter,
            )
            return self._run_tool_loop(state, saved_system_msg, force_retrieve,
                on_checkpoint=on_checkpoint, data_store=data_store, save_start=len(state.messages) - 1)

        # —— 第一步：组装 system message ——
        system_msg = self._build_system_message(  # 调用内部方法构建系统提示消息
            style=style,                        # 传入回答风格
        )

        # ── Workflow 注入（支持指定或自动匹配） ──────
        wf_name = workflow_name if workflow_name and workflow_name != "__auto__" else None
        if wf_name:
            # 指定了工作流：加载完整内容替换摘要
            wf_content = self.workflow_router.get_workflow_content(wf_name)
            if wf_content:
                system_msg += f"\n\n---\n# 工作流: {wf_name}\n{wf_content}"
                logger.info(f"工作流已加载: {wf_name}")
            else:
                logger.warning(f"工作流 '{wf_name}' 未找到")
        else:
            # Auto 模式：注入所有工作流摘要，LLM 通过 read_workflow 按需加载
            wf_summaries = self.workflow_router.get_workflow_summaries()
            if wf_summaries:
                system_msg += (
                    f"\n\n---\n# 工作流\n"
                    f"{wf_summaries}\n"
                    f"如需加载完整工作流指令，请调用 read_workflow 工具。"
                )

        # 注入当前活跃目标
        if data_store and session_id:
            from .tools._infra_handlers import _get_goal_line
            goal_line = _get_goal_line(session_id, data_store)
            if goal_line:
                system_msg += goal_line
                logger.debug(f"注入活跃目标: session={session_id[:8]}")

        logger.debug(f"system_msg 长度: {len(system_msg)} 字符")

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
            session_id=session_id,     # 传入会话 ID
            style=style,              # 传入回答风格
            max_iterations=max_iter,      # 传入最大迭代次数
        )
        # 记录工具循环开始前的消息数，用于保存时排除已持久化的历史
        # -1 是为了保留当前轮的用户问题（它在 state.messages 末尾）
        _save_start = len(state.messages) - 1

        # —— 第五步：分发到流式或非流式执行路径 ——
        if stream:
            return self._run_tool_loop_stream(
                state, force_retrieve,
                cancel_check=cancel_check,
                on_checkpoint=on_checkpoint,
                drain_pending=drain_pending,
                emit_event=emit_event,
                data_store=data_store,
                save_start=_save_start,
            )

        return self._run_tool_loop(state, system_msg, force_retrieve, on_checkpoint=on_checkpoint, data_store=data_store, save_start=_save_start)

    # ─── 上下文治理 ───────────────────────────

    def _govern_context(self, messages: List[dict]) -> List[dict]:
        """上下文治理流水线：在每次调用 LLM 前清理消息列表。

        3 步治理：
          1. 补充缺失 tool_result（有 tool_calls 但没有结果的，中断恢复场景）
          2. 预算控制：截断超过上限的工具结果
          3. 历史裁剪：按字符预算从最早的消息开始丢弃
        """
        governed = list(messages)

        # ── 1. Backfill：补充缺失的 tool_result ──
        # 中断恢复场景：assistant 有 tool_calls 但没有对应的 tool 消息，
        # 注入合成结果防止 LLM 以为工具还没执行
        backfill_needed = {}
        for m in governed:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else ""
                    if tc_id:
                        backfill_needed[tc_id] = tc

        for m in governed:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                backfill_needed.pop(m["tool_call_id"], None)

        for tc_id, tc in backfill_needed.items():
            tc_name = tc.get("name", "") if isinstance(tc, dict) else ""
            governed.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"(工具 {tc_name} 在上一轮执行后被中断，结果不可用。请根据已有信息继续。)",
            })

        logger.debug(f"_govern_context: 输入 {len(messages)} 条消息, "
                     f"backfill={len(backfill_needed)} 条")

        # ── 2. Tool Result Budget：单个工具结果上限 ──
        MAX_TOOL_CHARS = conf.max_tool_result_chars
        for i, m in enumerate(governed):
            if m.get("role") == "tool":
                content = m.get("content", "") or ""
                if len(content) > MAX_TOOL_CHARS:
                    truncated = content[:MAX_TOOL_CHARS]
                    governed[i] = dict(m)
                    governed[i]["content"] = truncated + "\n\n...(工具结果过长，已截断)..."
                    logger.debug(f"工具结果预算截断: {len(content)} → {MAX_TOOL_CHARS} 字符")

        # ── 3. 调用截断方法做最终裁剪 ──
        return self._truncate_messages(governed)

    # ===== 上下文窗口裁剪 =====
    def _truncate_messages(self, messages: List[dict]) -> List[dict]:
        """按字符预算裁剪消息。保留首尾，从最早的消息开始丢弃整轮对话。
        
        thresholds: conf.context_window_chars 的 context_input_ratio。
        丢弃策略：从最早的非 system 消息开始，按整轮（assistant + 后续的 tool）丢弃，
        保留最近的对话轮次完整。
        """
        budget = int(conf.context_window_chars * conf.context_input_ratio)
        total = sum(_count_message_chars(m) for m in messages)
        if total <= budget:
            return messages
        
        logger.warning(
            f"上下文超预算: ~{total_chars} chars > {budget} "
            f"(context_window_chars={conf.context_window_chars}), 裁剪最早的消息..."
        )
        
        # system 单独保留，不参与裁剪
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        rest = messages[1:] if system_msg else messages[:]
        last_msg = rest[-1]  # 最后一条始终保留
        
        keep = rest[:-1]
        
        while keep:
            total_chars = sum(_count_message_chars(m) for m in keep)
            if system_msg:
                total_chars += _count_message_chars(system_msg)
            total_chars += _count_message_chars(last_msg)
            if total_chars <= budget:
                break
            dropped = keep.pop(0)
            if dropped.get("role") == "assistant":
                while keep and keep[0].get("role") == "tool":
                    keep.pop(0)
        
        result = []
        if system_msg:
            result.append(system_msg)
        result.extend(keep)
        after_chars = sum(_count_message_chars(m) for m in result)
        if total > 0:
            logger.debug(f"裁剪后: ~{after_chars} chars ({int((1-after_chars/total)*100)}% 压缩)")
        return result
    # ─── Tool-call 循环 (非流式) ─────────────────

    def _save_turn_messages(self, session_id: str, messages: list, data_store: Optional[object] = None, start: int = 0):
        """保存本轮完整消息序列（含工具调用和结果）到历史记录。

        跳过 system 消息（由后续回合重建）和 start 之前的消息（已持久化的历史），
        只保存本轮新增的 user / assistant / tool 消息。
        """
        if not data_store or not session_id:
            return
        try:
            # 跳过 system 消息和 start 之前的已持久化历史
            turn_msgs = [m for m in messages[start:] if m.get("role") != "system"]
            if not turn_msgs:
                return
            data_store.insert_session_turn(session_id, turn_msgs)
            logger.debug(f"已保存完整对话回合: session={session_id[:8]}, {len(turn_msgs)} 条消息")
        except Exception as e:
            logger.warning(f"保存完整对话回合失败: {e}")

    # ===== 非流式工具调用主循环 =====
    def _run_tool_loop(self, state: AgentState, system_msg: str, force_retrieve: bool,
                       on_checkpoint: Optional[Callable[[str, dict], None]] = None,
                       data_store: Optional[object] = None,
                       save_start: int = 0) -> str:
        """非流式工具调用主循环。

        循环逻辑（LLM 驱动的工具调用循环）：
          1. LLM 收到完整的 messages（含历史和之前的工具结果）
          2. LLM 决定调用哪些工具 → 返回 tool_calls 列表
          3. 如果 tool_calls 为空：LLM 已准备好最终答案，直接返回
          4. 如果 tool_calls 包含 ask_user_for_clarification：提前终止，返回澄清问题
          5. 否则：并发执行所有工具调用（ThreadPoolExecutor），结果写回 state.messages
          6. 回到步骤 1，直到达到 max_iterations

        达上限处理：
          - 保存中断状态，返回提示文本让用户选择「继续」
        """
        tool_choice = "required" if force_retrieve else "auto"
        _empty_retries = 0
        _length_retries = 0

        # while 循环直到 should_continue() 返回 False（达上限或主动 break）
        while state.should_continue():  # 检查是否应该继续循环（没达到上限且没有被终止）

            # 发送前裁剪（避免上下文窗口溢出）
            truncated_messages = self._govern_context(state.messages)  # 上下文治理：去孤/压缩/裁剪

            # 记录每轮发送给 LLM 的输入日志
            log_llm_input(truncated_messages, round=state.iteration, suffix="_sent")

            # —— 1. 调用 LLM ——
            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"非流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:
                resp = self.client.chat_with_tools(  # 调用 LLM（带工具）
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
                    retries = _empty_retries
                    if retries < 2:
                        _empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({_empty_retries}/2)")
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        continue
                length_retries = _length_retries
                if resp.get("finish_reason") == "length" and content and length_retries < 3:
                    _length_retries = length_retries + 1
                    logger.warning(f"LLM 响应被截断 (length), 自动续写 ({_length_retries}/3)")
                    state.messages.append({"role": "assistant", "content": content})
                    state.messages.append({"role": "user", "content": "继续，不要重复已写过的内容。"})
                    continue
                # 正常完成：保存完整消息到历史
                state.messages.append({"role": "assistant", "content": content})
                self._save_turn_messages(state.session_id, state.messages, data_store, start=save_start)
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
                            session_id=state.session_id,
                            subagent_manager=getattr(self, "subagent_manager", None),
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    # 工具结果持久化：过长结果写入文件
                    if isinstance(res, str):
                        res = _persist_tool_result(state.session_id, tc["name"], res)
                    logger.debug(f"工具 {tc['name']} 完成: result_len={len(res)} chars")
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
                    except Exception:
                        q = "我需要您提供更多背景信息。"
                    logger.debug("提前中断工具循环：LLM 需要澄清")
                    return q

            # 首轮过后不再强制 tool_choice
            tool_choice = "auto"

        # ── 达上限: 保存状态让用户选择继续 ──────────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}")
        state.tool_exhausted = True
        state.system_msg = system_msg
        self._save_interrupted_state(state)
        return self._TOOL_EXHAUSTED_MSG

    # ─── 工具循环达上限恢复机制 ────────────────

    _TOOL_EXHAUSTED_MSG = (
        "[tool_exhausted] 本任务需要多轮工具调用，但已达单次上限。\n"
        "如需继续，请回复「继续」（将重置计数，基于当前进度继续）。\n"
        "如果已有信息足够，直接说出你的最终答案即可。"
    )

    _INTERRUPT_TAG = "_interrupted_tool_loop"

    def _save_interrupted_state(self, state):
        """保存被中断的工具循环状态到 data_store。"""
        try:
            if self.data_store:
                import json
                tasks = self.data_store.get_session_tasks(state.session_id) or {}
                tasks[self._INTERRUPT_TAG] = {
                    "messages": state.messages,
                    "system_msg": state.system_msg,
                }
                self.data_store.save_session_tasks(state.session_id, tasks)
        except Exception as e:
            logger.warning(f"保存中断状态失败: {e}")

    def _load_interrupted_state(self, session_id: str) -> dict | None:
        """读取被中断的工具循环状态。"""
        try:
            if self.data_store:
                tasks = self.data_store.get_session_tasks(session_id) or {}
                return tasks.get(self._INTERRUPT_TAG)
        except Exception:
            pass
        return None

    def _clear_interrupted_state(self, session_id: str):
        """清除已恢复的中断状态。"""
        try:
            if self.data_store:
                tasks = self.data_store.get_session_tasks(session_id) or {}
                tasks.pop(self._INTERRUPT_TAG, None)
                self.data_store.save_session_tasks(session_id, tasks)
        except Exception as e:
            logger.warning(f"清除中断状态失败: {e}")

    @staticmethod
    def _is_continue_request(query: str) -> bool:
        """检测用户是否要求继续工具循环。"""
        q = query.strip().lower()
        return q in ("继续", "continue", "继续做", "接着做", "继续完成", "好，继续", "继续吧")

    # ─── 共享：最终答案生成（非流式 + 流式复用） ─────────

    # ─── Tool-call 循环 (流式) ─────────────────

    # ===== 流式工具调用主循环（生成器函数） =====
    def _run_tool_loop_stream(self, state: AgentState, force_retrieve: bool,
                               cancel_check: Optional[Callable[[], bool]] = None,
                               on_checkpoint: Optional[Callable[[str, dict], None]] = None,
                               drain_pending: Optional[Callable[[], list[dict]]] = None,
                               emit_event: Optional[Callable[[dict], None]] = None,
                               data_store: Optional[object] = None,
                               save_start: int = 0):
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
        tool_choice = "required" if force_retrieve else "auto"
        _empty_retries = 0
        _length_retries = 0

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
            truncated_messages = self._govern_context(state.messages)  # 上下文治理：去孤/压缩/裁剪

            # 记录实际发送给 LLM 的输入（截断后）
            log_llm_input(truncated_messages, round=it, suffix="_sent")  # 记录实际发送的消息到日志

            # —— 1. 流式调用 LLM ——
            total_chars = sum(len(str(m.get("content", "") or "")) for m in truncated_messages)
            logger.debug(f"流式 LLM 调用: msg_count={len(truncated_messages)}, "
                         f"total_chars={total_chars}, iteration={state.iteration}")
            logger.info(f"→ LLM 输入上下文字符数: {total_chars} chars ({len(truncated_messages)} 条消息)")
            try:  # 尝试调用 LLM
                events = self.client.chat_with_tools(  # 调用 LLM（带工具），返回事件生成器
                    messages=truncated_messages,  # 传入裁剪后的消息列表
                    model=self.chat_model,        # 指定模型
                    tools=registry.schemas,       # 传入可用工具的定义
                    tool_choice=tool_choice,      # 工具调用策略
                    stream=True,                  # 流式模式，逐块返回
                    temperature=0.7,              # 温度参数
                    max_tokens=conf.max_output_tokens,  # 最大输出字符
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
                            lr = _length_retries
                            if lr < 3:
                                _length_retries = lr + 1
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
                    retries = _empty_retries
                    if retries < 2:
                        _empty_retries = retries + 1
                        logger.warning(f"LLM 返回空内容, 自动重试 ({_empty_retries}/2)")
                        state.messages.append({"role": "user", "content": "请直接回答用户的问题，不要使用工具。"})
                        if emit_event: emit_event({"type": "status", "status": "retrying"})
                        yield {"type": "status", "status": "retrying"}
                        continue
                # 正常完成：保存完整消息到历史
                state.messages.append({"role": "assistant", "content": accumulated_content})
                self._save_turn_messages(state.session_id, state.messages, data_store, start=save_start)
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
                            session_id=state.session_id,
                            subagent_manager=getattr(self, "subagent_manager", None),
                            workflow_router=getattr(self, "workflow_router", None),
                        )
                    )
                    # 工具结果持久化
                    if isinstance(res, str):
                        res = _persist_tool_result(state.session_id, tc["name"], res)
                    logger.debug(f"流式工具 {tc['name']} 完成: result_len={len(res)} chars")
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
                    except Exception:  # 解析失败
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

        # ── 达上限: 保存中断状态，让用户选择继续 ─────
        logger.warning(f"tool-loop 达到上限 {state.max_iterations}")
        state.system_msg = state.messages[0]["content"] if state.messages else ""
        self._save_interrupted_state(state)
        # 流式输出提示文本
        for ch in self._TOOL_EXHAUSTED_MSG:
            if emit_event:
                emit_event({"type": "token", "text": ch})
            yield {"type": "token", "text": ch}
        return  # 不保存本轮，用户说"继续"后恢复

