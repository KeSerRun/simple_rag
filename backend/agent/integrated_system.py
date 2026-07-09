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
    TASK_MAX_STALE_TURNS = 5       # 任务最大过期轮数
    TASK_MAX_SHORT = 3             # 短期任务最大活跃数
    TASK_MAX_SHORT_HIST = 20       # 短期任务总历史上限
    TASK_MAX_LONG = 10             # 长期任务上限
    TASK_OVERLAP_RATIO = 0.2       # 话题关联关键词重叠比例阈值

    def __init__(self):
        """初始化集成系统：数据存储、RAG 问答引擎、向量库、会话状态。"""
        self.data_store = DataStore()
        self.rag_qa = RAGSystem(data_store=self.data_store)
        self.vector_store = self.rag_qa.vector_store
        self.session_last_style: dict[str, str] = {}
        self.session_tasks: dict[str, dict] = {}
        self.session_turn: dict[str, int] = {}
        # 生成取消事件：key=session_id, value=Event（set 时中断当前生成）
        self._cancel_events: dict[str, threading.Event] = {}
        # 检查点存储（内存中，支持会话恢复）
        self.checkpoints = CheckpointStore()
        # 子 Agent 管理器
        self.subagent_manager = SubagentManager(max_concurrent=4)
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

        # 1) 硬截断: 按轮次截取最近 N 条 QA
        qa_entries = [h for h in raw if h.get('type') != 'event']
        if len(qa_entries) > conf.max_history_length:
            discard = len(qa_entries) - conf.max_history_length
            discard_ids = {id(h) for h in qa_entries[:discard]}
            raw = [h for h in raw if id(h) not in discard_ids]
            logger.info(f"历史截断: 丢弃前 {discard} 轮, 保留最近 {conf.max_history_length} 轮")

        # 2) 字符数压缩: 超过上限时压缩早期对话
        qa_entries2 = [h for h in raw if h.get('type') != 'event']
        total_chars = sum(
            len(h.get('user', '') or '') + len(h.get('assistant', '') or '')
            for h in qa_entries2
        )
        if total_chars > conf.max_history_chars and len(qa_entries2) > 2:
            keep = 2
            compressed_qa = qa_entries2[:-keep]
            compressed_ids = {id(h) for h in compressed_qa}
            remaining_raw = [h for h in raw if id(h) not in compressed_ids]

            archive_id = self.data_store.insert_archive(
                session_id=session_id,
                summary="用户的问题：" + "；".join(
                    h.get('user', '')[:60] for h in compressed_qa if h.get('user')
                ),
                turns=[
                    {
                        "user": h.get("user", ""),
                        "assistant": h.get("assistant", ""),
                        "timestamp": h.get("timestamp", ""),
                    }
                    for h in compressed_qa
                ],
            )
            summary_text = (
                f"（历史摘要 #{archive_id}：用户之前的问题："
                + "；".join(h.get('user', '')[:60] for h in compressed_qa if h.get('user'))
                + "。如需查阅完整历史，请调用 read_archive 工具。）"
            )
            if summary_text:
                messages.append({'role': 'user', 'content': summary_text})
            for h in remaining_raw:
                self._append_history_item(messages, h)

            after_chars = sum(len(m.get('content', '') or '') for m in messages)
            logger.info(
                f"历史压缩触发: "
                f"压缩前 {len(compressed_qa)} 轮/{total_chars} 字符, "
                f"压缩后 {after_chars} 字符, "
                f"节省 {total_chars - after_chars} 字符, "
                f"归档={archive_id}"
            )
        else:
            for h in raw:
                self._append_history_item(messages, h)

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
    # 会话任务追踪
    # ═══════════════════════════════════════════════

    @staticmethod
    def _task_keywords(text: str) -> set:
        """提取文本中的关键词用于话题关联判定。"""
        return set(re.findall(r'[\w一-鿿]+', text.lower()))

    @staticmethod
    def _is_related_to(q_words: set, task_desc: str) -> bool:
        """新问题与任务描述是否属于同一话题。"""
        t_words = IntegratedSystem._task_keywords(task_desc)
        if not q_words or not t_words:
            return True
        overlap = q_words & t_words
        return len(overlap) / max(len(t_words), 1) >= IntegratedSystem.TASK_OVERLAP_RATIO

    def _load_session_tasks(self, session_id: str) -> tuple[list[str], list[str]]:
        """读取会话中状态为 active 的短期/长期任务描述。"""
        tasks = self.session_tasks.get(session_id)
        if tasks is None:
            tasks = self.data_store.get_session_tasks(session_id)
            self.session_tasks[session_id] = tasks
        short = [t["desc"] for t in tasks.get("short", []) if t.get("status") == "active"]
        long_ = [t["desc"] for t in tasks.get("long", []) if t.get("status") == "active"]
        return short, long_

    def _save_session_tasks(self, session_id: str, short: list[dict], long_: list[dict]):
        """保存会话任务列表。"""
        tasks = {"short": short, "long": long_}
        self.session_tasks[session_id] = tasks
        self.data_store.save_session_tasks(session_id, tasks)

    def _extract_task_from_query(self, question: str, wf_name: str = None) -> str:
        """从用户问题中提取短期任务描述。"""
        if wf_name:
            wf_display = {"USstocks": "美股分析"}
            return wf_display.get(wf_name, wf_name)
        q = question.strip().rstrip("？?。.!！")
        return q[:40] + ("…" if len(q) > 40 else "")

    def _get_turn(self, session_id: str) -> int:
        """获取并递增会话轮次。"""
        self.session_turn.setdefault(session_id, 0)
        self.session_turn[session_id] += 1
        return self.session_turn[session_id]

    def _update_tasks(self, session_id: str, question: str, wf_name: str = None):
        """更新会话任务：检测完成/切换，管理状态生命周期。"""
        turn = self._get_turn(session_id)
        tasks = self.session_tasks.get(session_id, {"short": [], "long": []})
        raw_short: list[dict] = tasks.get("short", [])
        raw_long: list[dict] = tasks.get("long", [])
        current_desc = self._extract_task_from_query(question, wf_name)
        q_words = self._task_keywords(question)

        def _task_active(t: dict) -> bool:
            """判定任务与新问题是否同属一个话题（关键词重叠 或 同 workflow）。"""
            if t["status"] != "active":
                return False
            if wf_name and t.get("workflow") == wf_name:
                return True
            if self._is_related_to(q_words, t["desc"]):
                return True
            return False

        # ── 1. 关闭已无关的旧任务 ────────────────────
        for t in raw_short:
            if t["status"] != "active":
                continue
            if _task_active(t):
                t["last_active_turn"] = turn
            else:
                if turn - t.get("last_active_turn", t["turn"]) > self.TASK_MAX_STALE_TURNS:
                    logger.info(f"任务超期: '{t['desc']}' ({self.TASK_MAX_STALE_TURNS}轮未引用)")
                else:
                    logger.info(f"任务完成: '{t['desc']}' (话题切换)")
                t["status"] = "superseded"

        # ── 2. 更新短期任务 ──────────────────────────
        existing = [t for t in raw_short if t["desc"] == current_desc and t["status"] == "active"]
        others = [t for t in raw_short if t["desc"] != current_desc]

        if existing:
            existing[0]["last_active_turn"] = turn
            active_tasks = existing
        else:
            new_task = {
                "desc": current_desc,
                "status": "active",
                "turn": turn,
                "last_active_turn": turn,
                "workflow": wf_name,
            }
            active_tasks = [new_task]

        active_part = (active_tasks + [t for t in others if t["status"] == "active"])[:self.TASK_MAX_SHORT]
        inactive_part = [t for t in raw_short if t["status"] != "active"]
        new_short = (active_part + inactive_part)[:self.TASK_MAX_SHORT_HIST]

        # ── 3. 长期任务：同一 desc 再次出现时提升 ────
        long_descs = {t["desc"] for t in raw_long}
        if current_desc not in long_descs:
            hist_descs = {t["desc"] for t in raw_short} | {
                t["desc"] for t in self.session_tasks.get(session_id, {}).get("short", [])
            }
            if current_desc in hist_descs:
                raw_long.append({
                    "desc": current_desc,
                    "status": "active",
                    "turn": turn,
                    "last_active_turn": turn,
                    "workflow": wf_name,
                })
                logger.info(f"提升为长期任务: '{current_desc}'")

        for t in raw_long:
            if t["status"] != "active":
                continue
            if turn - t.get("last_active_turn", t["turn"]) > self.TASK_MAX_STALE_TURNS * 2:
                t["status"] = "superseded"
                logger.info(f"长期任务过期: '{t['desc']}'")

        self._save_session_tasks(session_id, new_short, raw_long[:self.TASK_MAX_LONG])

    # ═══════════════════════════════════════════════
    # 问答接口（非流式 / 流式）
    # ═══════════════════════════════════════════════

    def get_answer(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """处理用户查询，返回完整答案（非流式）。"""
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        wf_name = self.rag_qa.workflow_router.match(question)
        short_tasks, long_tasks = self._load_session_tasks(session_id)
        logger.debug(f"会话任务 session={session_id} 短期={short_tasks} 长期={long_tasks}")

        try:
            answer = self.rag_qa.generate_answer(
                question,
                stream=False,
                history=history,
                partition=partition,
                style=style,
                short_term_tasks=short_tasks,
                long_term_tasks=long_tasks,
            )
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            log_qa(partition, session_id, question, answer)
            return answer

        self._update_tasks(session_id, question, wf_name)
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def answer_generator(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """流式返回答案的生成器（支持中断）。"""
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        wf_name = self.rag_qa.workflow_router.match(question)
        short_tasks, long_tasks = self._load_session_tasks(session_id)
        logger.debug(f"会话任务 session={session_id} 短期={short_tasks} 长期={long_tasks}")

        # 注册取消事件
        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event

        def is_cancelled():
            return cancel_event.is_set()

        try:
            answer_iter = self.rag_qa.generate_answer(
                question,
                stream=True,
                history=history,
                partition=partition,
                style=style,
                short_term_tasks=short_tasks,
                long_term_tasks=long_tasks,
                cancel_check=is_cancelled,
                on_checkpoint=save_cp,
                drain_pending=drain_pending,
            )
            ans = []
            for event in answer_iter:
                if is_cancelled():
                    # 中断：清除已累积的内容，不保存历史
                    yield {"type": "status", "status": "cancelled"}
                    logger.info(f"生成被中断: session={session_id}")
                    return
                if event.get("type") == "token":
                    ans.append(event.get("text", ""))
                yield event
            # å¦æçæè¢«ä¸­æ­ï¼ä¸ä¿å­åå²
            if is_cancelled():
                yield {"type": "status", "status": "cancelled"}
                return
            answer = ''.join(ans)
        finally:
            # 清理取消事件
            self._cancel_events.pop(session_id, None)

        self._update_tasks(session_id, question, wf_name)
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        logger.debug(f"回答成功 len={len(answer)}")

    # ═══════════════════════════════════════════════
    # CLI 命令分发
    # ═══════════════════════════════════════════════

    def run_agent(self, session_id, question, partition: str = None, style: Optional[str] = None, stream=False):
        """使用 AgentLoop 状态机处理用户查询。

        替代 get_answer / answer_generator 的新入口。
        调用方（API）已持有会话锁。
        """
        if stream:
            return self._run_agent_stream(session_id, question, partition, style)

        # 非流式
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)
        wf_name = self.rag_qa.workflow_router.match(question)
        short_tasks, long_tasks = self._load_session_tasks(session_id)

        try:
            answer = self.rag_qa.generate_answer(
                question,
                stream=False,
                history=history,
                partition=partition,
                style=style,
                short_term_tasks=short_tasks,
                long_term_tasks=long_tasks,
            )
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            log_qa(partition, session_id, question, answer)
            return answer

        self._update_tasks(session_id, question, wf_name)
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def _run_agent_stream(self, session_id, question, partition=None, style=None):
        """流式版本的 run_agent。"""
        # 准备工作
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)
        short_tasks, long_tasks = self._load_session_tasks(session_id)
        logger.debug(f"会话任务 session={session_id} 短期={short_tasks} 长期={long_tasks}")

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
                    content = f"[å­ä»»å¡ {{r.task_id}} å®æ]\n{{r.content[:500]}}"
                    msgs.append({"role": "user", "content": content})
                    logger.info(f"ä¸­é´æ³¨å¥å­ Agent: {{r.task_id}}")
            return msgs


        try:
            answer_iter = self.rag_qa.generate_answer(
                question,
                stream=True,
                history=history,
                partition=partition,
                style=style,
                short_term_tasks=short_tasks,
                long_term_tasks=long_tasks,
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
        self._update_tasks(session_id, question, wf_name)
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
