# ===== IntegratedSystem 类：集成系统核心类 =====
# 该类将数据存储和 RAG 问答能力封装在一起，对外提供统一的问答接口
# 包括：会话历史管理、任务追踪、风格切换检测、流式/非流式问答、CLI 命令分发

# ---- 导入 ----
from base.config import conf
from base.logger import logger, log_qa
if conf.storage_backend == 'sqlite':
    from storage import SQLiteStore as DataStore
else:
    from storage import JSONFileStore as DataStore
from agent import RAGSystem

from .checkpoint import CheckpointStore
from .subagent import SubagentManager
from .agent_loop import SessionManager
from .hooks import CompositeHook, LoggingHook

import uuid
import os
import sys
import re
import threading
from typing import Optional


class IntegratedSystem:
    """集成系统：封装数据存储 + RAG 问答能力，对外提供统一的问答和 CLI 接口。"""

    # ─── 类常量（任务追踪相关） ─────────────────
    TASK_OVERLAP_RATIO = 0.2       # 话题关联关键词重叠比例阈值

    def __init__(self):
        """初始化集成系统：数据存储、RAG 问答引擎、向量库、会话状态。"""
        self.data_store = DataStore()
        self.rag_qa = RAGSystem(data_store=self.data_store)
        self.vector_store = self.rag_qa.vector_store
        self.session_last_style: dict[str, str] = {}
        # 生成取消事件：key=session_id, value=Event（set 时中断当前生成）
        self._cancel_events: dict[str, threading.Event] = {}
        # 检查点存储（内存中，支持会话恢复）
        self.checkpoints = CheckpointStore()
        # 子 Agent 管理器
        self.subagent_manager = SubagentManager(max_concurrent=4)
        # 将 subagent_manager 注入 RAGSystem，使其能传递给 ToolContext
        self.rag_qa.subagent_manager = self.subagent_manager
        # 会话管理器（AgentLoop 实例池）
        self.session_manager = SessionManager()
        # 钩子系统
        self.hooks = CompositeHook()
        self.hooks.add(LoggingHook())

    def cancel_generation(self, session_id: str):
        """中断指定会话的正在进行的生成。"""
        event = self._cancel_events.get(session_id)
        if event:
            event.set()
            logger.info(f"已发送中断信号: session={session_id}")

    def _is_cancelled(self, session_id: str) -> bool:
        """检查指定会话是否被要求中断。"""
        event = self._cancel_events.get(session_id)
        return event is not None and event.is_set()

    # ═══════════════════════════════════════════════
    # 目标管理（基于 nanobot sustained_goal 模式）
    # ═══════════════════════════════════════════════

    GOAL_KEY = "_active_goal"

    def set_goal(self, session_id: str, goal: str) -> None:
        """设置会话的持续目标。"""
        self.session_manager.set_metadata(session_id, self.GOAL_KEY, {
            "goal": goal,
            "status": "active",
        })
        logger.info(f"目标已设置: session={session_id[:8]} goal={goal[:40]}")

    def complete_goal(self, session_id: str) -> None:
        """完成当前目标。"""
        self.session_manager.set_metadata(session_id, self.GOAL_KEY, {
            "goal": "",
            "status": "completed",
        })
        logger.info(f"目标已完成: session={session_id[:8]}")

    def get_goal_line(self, session_id: str) -> str:
        """获取供注入 system prompt 的目标文本。"""
        data = self.session_manager.get_metadata(session_id, self.GOAL_KEY)
        if data and data.get("status") == "active" and data.get("goal"):
            return f"\n当前目标：{data['goal']}"
        return ""

    # ═══════════════════════════════════════════════
    # 历史记录管理
    # ═══════════════════════════════════════════════

    def get_history(self, session_id):
        """读取会话历史并展开为 LLM 输入格式。

        history.json 中两种条目:
          - {type: 'qa', user, assistant}       → user / assistant 两条消息
          - {type: 'event', event_type, files}  → 单条 <operation：...> user 消息
        规则:
          - max_history_length: 硬截断窗口，超过时丢弃最早的 QA
          - max_history_chars: 字符数超限时压缩早期对话（保留最近 2 轮）
        """
        raw = self.data_store.get_session_history(session_id) or []

        # 检查点恢复：如果存在未完成的检查点，将之前的工具执行结果注入历史
        cp = self.checkpoints.load(session_id)
        if cp and cp.phase in ("awaiting_tools", "tools_completed"):
            from .checkpoint import restore_messages
            restored = restore_messages(cp)
            if restored:
                logger.info(f"恢复检查点: phase={cp.phase}, {len(restored)} 条消息注入历史")
                # 将恢复的消息作为合成 qa 条目插入历史
                if restored:
                    raw.append({
                        "type": "qa",
                        "user": "(系统：检测到上轮对话被中断，以下为已完成的工具执行结果)",
                        "assistant": f"[系统已恢复 {len(restored)} 条工具执行结果]",
                    })
            # 清除检查点（避免重复恢复）
            self.checkpoints.clear(session_id)

        if not raw:
            return []
        messages = []

        # 1) 硬截断: 按轮次截取最近 N 条 QA（安全阀）
        qa_entries = [h for h in raw if h.get('type') != 'event']
        if len(qa_entries) > conf.max_history_length:
            discard = len(qa_entries) - conf.max_history_length
            discard_ids = {id(h) for h in qa_entries[:discard]}
            raw = [h for h in raw if id(h) not in discard_ids]
            logger.info(f"历史截断: 丢弃前 {discard} 轮, 保留最近 {conf.max_history_length} 轮")

        # 2) 全部转为 messages
        for h in raw:
            self._append_history_item(messages, h)

        # 3) nanobot 模式：Token 预算压缩
        qa_entries = [h for h in raw if h.get('type') != 'event']
        budget = conf.context_window_tokens - conf.max_output_tokens - 1024
        target = int(budget * conf.consolidation_ratio)
        estimated = self._estimate_tokens(messages)

        if estimated > budget and len(qa_entries) > 2:
            # 计算需要释放的 token 量
            need_to_free = estimated - target
            # 找到 user-turn 边界
            boundary = self._pick_consolidation_boundary(qa_entries, estimated, target)
            if boundary:
                compressed_qa = qa_entries[:boundary]
                remaining_qa = qa_entries[boundary:]

                # LLM 摘要压缩
                summary_text = self._build_consolidated_summary(compressed_qa)

                archive_id = self.data_store.insert_archive(
                    session_id=session_id,
                    summary=summary_text,
                    turns=[
                        {"user": h.get("user", ""), "assistant": h.get("assistant", ""),
                         "timestamp": h.get("timestamp", "")}
                        for h in compressed_qa
                    ],
                )

                # 重新构建 messages：摘要 + 剩余
                messages.clear()
                if summary_text:
                    messages.append({'role': 'user', 'content': summary_text})
                # 重新追加剩余条目
                remaining_raw = [h for h in raw if h.get('type') == 'event' or h in remaining_qa]
                # 用 index 来判断
                qa_ids = {id(h) for h in compressed_qa}
                remaining_raw = [h for h in raw if id(h) not in qa_ids]
                for h in remaining_raw:
                    self._append_history_item(messages, h)

                after_tokens = self._estimate_tokens(messages)
                logger.info(
                    f"Token 预算压缩: "
                    f"压缩前 {len(compressed_qa)} 轮/{estimated} token, "
                    f"压缩后 {after_tokens} token, "
                    f"节省 {estimated - after_tokens} token, "
                    f"归档={archive_id}"
                )

        return messages

    @staticmethod
    def _append_history_item(messages: list, h: dict):
        """将一条 history 条目追加到 messages。"""
        if h.get('type') == 'event':
            tag = IntegratedSystem._event_to_tag(
                h.get('event_type', ''), h.get('files', [])
            )
            if tag:
                messages.append({'role': 'user', 'content': tag})
        else:
            messages.append({'role': 'user', 'content': h.get('user', '')})
            messages.append({'role': 'assistant', 'content': h.get('assistant', '')})

    @staticmethod
    def _event_to_tag(event_type: str, files: list) -> str:
        """事件 → <operation：...> 文本, 供 LLM 感知用户最近操作"""
        if event_type == 'delete_all':
            return "<operation：clear all uploaded files>"
        if not files:
            return ""
        head = files[:3]
        suffix = "等" if len(files) > 3 else ""
        if event_type == 'upload':
            return f"<operation：upload files: {', '.join(head)}{suffix}>"
        if event_type == 'delete':
            return f"<operation：delete files: {', '.join(head)}{suffix}>"
        if event_type == 'style_change':
            new_style = files[0] if files else 'default'
            return f"<operation：switch answer style to {new_style}>"
        return ""

    # ── nanobot 式 token 预算与边界计算 ──────────

    @staticmethod
    def _estimate_tokens(messages: list) -> int:
        """估算消息列表的 token 数（1 token ≈ 2 中文字符 / 4 英文字符）。"""
        total = 0
        for m in messages:
            text = str(m.get("content", "") or "")
            if text:
                # 粗略估计：中文为主
                total += len(text) // 2
        return total

    @staticmethod
    def _pick_consolidation_boundary(qa_entries: list, estimated: int, target: int) -> int | None:
        """从最早的消息开始，找到满足释放需求的 user-turn 边界。"""
        need_to_free = estimated - target
        if need_to_free <= 0:
            return None
        accumulated = 0
        for i, entry in enumerate(qa_entries[:-2]):  # 保留最近 2 轮
            text = (entry.get('user', '') or '') + (entry.get('assistant', '') or '')
            accumulated += len(text) // 2  # char → token 粗略
            if accumulated >= need_to_free:
                return i + 1  # 返回边界索引
        return len(qa_entries) - 2  # 至少保留 2 轮

    def _build_consolidated_summary(self, compressed_qa: list) -> str:
        """用 LLM 对早期对话生成摘要（nanobot 模式）。失败时回退到简单拼接。"""
        try:
            user_msgs = [h.get('user', '')[:200] for h in compressed_qa if h.get('user')]
            if not user_msgs:
                return ""
            # 用 LLM 生成摘要
            prompt = (
                "以下是用户之前提出的问题和回答记录。请用简洁的语言总结用户关心的话题和已获取的信息。"
                "只输出总结本身，不要附加说明。\n\n"
                + "\n".join(f"- 用户: {q}" for q in user_msgs)
            )
            # 使用已有的 LLM 客户端
            if not hasattr(self, '_summary_client'):
                from rag.llm_client import OpenAIClient
                self._summary_client = OpenAIClient(
                    api_key=conf.openai_api_key,
                    base_url=conf.openai_base_url,
                )
            resp = self._summary_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=conf.chat_model,
                stream=False,
                temperature=0.3,
                max_tokens=500,
            )
            summary = resp.strip() if resp else ""
            if summary:
                return f"[对话历史摘要]\n{summary}\n(如需查阅完整历史，可调用 read_archive 工具)"
        except Exception as e:
            logger.warning(f"LLM 摘要生成失败，回退到简单拼接: {e}")

        # 回退：简单拼接用户问题
        qs = "；".join(h.get('user', '')[:60] for h in compressed_qa if h.get('user'))
        return f"（历史摘要：用户之前的问题——{qs}。如需查阅完整历史，请调用 read_archive 工具。）"

    # ═══════════════════════════════════════════════
    # 风格切换检测
    # ═══════════════════════════════════════════════

    def _check_style_change(self, session_id: str, style: Optional[str]) -> None:
        """检测 style 切换，记录事件到历史。"""
        prev = self.session_last_style.get(session_id)
        if prev is not None and prev != style:
            self.data_store.insert_session_event(session_id, 'style_change', [str(style or 'default')])
            logger.info(f"style 切换: {prev} → {style or 'default'}")
        self.session_last_style[session_id] = style or 'default'

    # ═══════════════════════════════════════════════
    # CLI 命令分发
    # ═══════════════════════════════════════════════

    def run_agent(self, session_id, question, partition: str = None, style: Optional[str] = None, stream=False):
        """使用 AgentLoop 状态机处理用户查询。

        替代 get_answer / answer_generator 的新入口。
        调用方（API）已持有会话锁。
        """
        # 注入持续目标
        from .tools._infra_handlers import _get_goal_line
        goal_line = _get_goal_line(session_id)
        if goal_line:
            question = question + goal_line

        if stream:
            return self._run_agent_stream(session_id, question, partition, style)

        # 非流式
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)
        wf_name = self.rag_qa.workflow_router.match(question)

        try:
            answer = self.rag_qa.generate_answer(
                question,
                stream=False,
                history=history,
                partition=partition,
                style=style,
            )
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            log_qa(partition, session_id, question, answer)
            return answer

        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def _run_agent_stream(self, session_id, question, partition=None, style=None):
        """流式版本的 run_agent。"""
        # 准备工作
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)
        logger.debug(f"会话 session={session_id}")

        # 注册取消事件
        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event

        def is_cancelled():
            return cancel_event.is_set()

        def drain_pending() -> list[dict]:
            """æ£æ¥å¹¶æ ¼å¼åå­ Agent ç»æã"""
            results = self.subagent_manager.drain_results(session_id)
            msgs = []
            for r in results:
                if r.success and r.content:
                    content = f"[å­ä»»å¡ {r.task_id} å®æ]\n{r.content[:500]}"
                    msgs.append({"role": "user", "content": content})
                    logger.info(f"ä¸­é´æ³¨å¥å­ Agent: {r.task_id}")
            return msgs

        def save_cp(phase: str, payload: dict):
                """ä¿å­æ£æ¥ç¹ã"""
                from .checkpoint import Checkpoint
                cp = Checkpoint(
                    phase=phase,
                    iteration=payload.get("iteration", 0),
                    model=getattr(self.rag_qa, "chat_model", ""),
                    pending_calls=payload.get("pending_calls"),
                    completed_results=payload.get("completed_results"),
                )
                self.checkpoints.save(session_id, cp)

        try:
            answer_iter = self.rag_qa.generate_answer(
                question,
                stream=True,
                history=history,
                partition=partition,
                style=style,
                cancel_check=is_cancelled,
                on_checkpoint=save_cp,
                drain_pending=drain_pending,
            )
            ans = []
            for event in answer_iter:
                if is_cancelled():
                    yield {"type": "status", "status": "cancelled"}
                    logger.info(f"生成被中断: session={session_id}")
                    return
                if event.get("type") == "token":
                    ans.append(event.get("text", ""))
                yield event
            answer = ''.join(ans)
        finally:
            self._cancel_events.pop(session_id, None)

        # 更新任务
        wf_name = self.rag_qa.workflow_router.match(question)
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        logger.debug(f"回答成功 len={len(answer)}")

    def run_cli(self, args):
        """CLI entry point - æ ¹æ® args.command ååå°å¯¹åºæä½ã"""
        if hasattr(args, "session") and args.session:
            session_id = args.session
        else:
            session_id = "cli-" + str(uuid.uuid4())[:8]
        partition = args.partition if hasattr(args, "partition") and args.partition else session_id

        if args.command == "query":
            print(end="", flush=True)
            if getattr(args, "stream", False):
                for event in self.answer_generator(session_id, args.question, partition=partition):
                    if event.get("type") == "token":
                        print(event.get("text", ""), end="", flush=True)
                print()
            else:
                answer = self.get_answer(session_id, args.question, partition=partition)
                print(answer)

        elif args.command == "upload":
            if not os.path.exists(args.path):
                print("path not found:", args.path)
                sys.exit(1)
            if os.path.isfile(args.path):
                name = os.path.basename(args.path)
                self.data_store.insert_session_event(session_id, 'upload', [name])
                self.vector_store.store_documents_from_dir(args.path, partition=partition)
                print("uploaded:", name)
            elif os.path.isdir(args.path):
                self.vector_store.store_documents_from_dir(args.path, partition=partition)
                print("uploaded from dir:", args.path)

        elif args.command == "chat":
            print("Interactive mode. Type /exit to quit.")
            while True:
                try:
                    q = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not q:
                    continue
                if q == "/exit":
                    break
                try:
                    answer = self.get_answer(session_id, q, partition=partition)
                    print(answer)
                except Exception as e:
                    print("error:", e)

        elif args.command == "info":
            print(f"session:     {session_id}")
            print(f"partition:   {partition}")
            docs = self.vector_store.get_documents_by_partition(partition=partition)
            print(f"documents:   {len(docs)}")
            history = self.data_store.get_session_history(session_id)
            print(f"history:     {len(history or [])} rounds")
