"""IntegratedSystem: 集成数据存储 + RAG 问答能力，对外提供统一的问答和 CLI 接口。

包括：会话历史管理、风格切换检测、流式/非流式问答、CLI 命令分发。
"""

from base.config import conf
from base.logger import logger, log_qa
from storage import JSONFileStore as DataStore
from agent import RAGSystem

from .checkpoint import CheckpointStore
from .session import SessionLockManager

import uuid
import re
import threading
from typing import Optional

# ── 集成系统 ──


class IntegratedSystem:
    """集成数据存储 + RAG 问答能力，对外提供统一问答和 CLI 入口。"""

    def __init__(self):
        """初始化集成系统。

        创建数据存储、RAG 问答引擎、向量库和会话状态管理。
        """
        self.data_store = DataStore()
        self.rag_qa = RAGSystem(data_store=self.data_store)
        self.vector_store = self.rag_qa.vector_store
        self.session_last_style: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self.checkpoints = CheckpointStore(data_store=self.data_store)
        self.session_manager = SessionLockManager()

    def cancel_generation(self, session_id: str) -> None:
        """中断指定会话的正在进行的生成。

        Args:
            session_id: 要中断的会话 ID。
        """
        event = self._cancel_events.get(session_id)
        if event:
            event.set()
            logger.info(f"已发送中断信号: session={session_id}")

    def _is_cancelled(self, session_id: str) -> bool:
        """检查指定会话是否被要求中断。

        Args:
            session_id: 会话 ID。

        Returns:
            如果该会话已被标记为中断，返回 True。
        """
        event = self._cancel_events.get(session_id)
        return event is not None and event.is_set()



    # ── 会话历史管理 ──

    def get_history(self, session_id):
        """读取会话历史并展开为 LLM 输入格式。

        history.json 中两种条目:
          - {type: 'qa', user, assistant}       → user / assistant 两条消息
          - {type: 'event', event_type, files}  → 单条 <operation：...> user 消息

        规则:
          - max_history_length: 硬截断窗口，超过时丢弃最早的 QA
          - max_history_chars: 字符数超限时压缩早期对话（保留最近 2 轮）

        Args:
            session_id: 会话 ID。

        Returns:
            LLM 输入格式的消息列表。
        """
        raw = self.data_store.get_session_history(session_id) or []

        cp = self.checkpoints.load(session_id)
        restored_msgs = []
        if cp and cp.phase in ("awaiting_tools", "tools_completed", "final_response"):
            from .checkpoint import restore_messages
            restored_msgs = restore_messages(cp)
            if restored_msgs:
                logger.info(f"恢复检查点: phase={cp.phase}, {len(restored_msgs)} 条消息")
            self.checkpoints.clear(session_id)

        if not raw:
            messages = []
            for m in restored_msgs:
                messages.append(m)
            return messages
        messages = []

        qa_entries = [h for h in raw if h.get('type') != 'event']
        if len(qa_entries) > conf.max_history_length:
            discard = len(qa_entries) - conf.max_history_length
            discard_ids = {id(h) for h in qa_entries[:discard]}
            raw = [h for h in raw if id(h) not in discard_ids]
            logger.info(f"历史截断: 丢弃前 {discard} 轮, 保留最近 {conf.max_history_length} 轮")

        for h in raw:
            self._append_history_item(messages, h)

        if restored_msgs:
            messages.extend(restored_msgs)

        qa_entries = [h for h in raw if h.get('type') != 'event']
        _BUDGET_MARGIN = 1024
        budget = conf.context_window_chars - conf.max_output_chars - _BUDGET_MARGIN
        target = int(budget * conf.consolidation_ratio)
        estimated_chars = self._estimate_chars(messages)

        if estimated_chars > budget and len(qa_entries) > 2:
            boundary = self._pick_consolidation_boundary(qa_entries, estimated_chars, target)
            if boundary:
                compressed_qa = qa_entries[:boundary]
                remaining_qa = qa_entries[boundary:]

                summary_text = self._build_consolidated_summary(compressed_qa)

                archive_id = self.data_store.insert_archive(
                    session_id=session_id,
                    summary=summary_text,
                    turns=[
                        {
                            "user": q,
                            "assistant": a,
                            "timestamp": h.get("timestamp", ""),
                        }
                        for h in compressed_qa
                        for q, a in [self._extract_qa_from_entry(h)]
                    ],
                )

                messages.clear()
                if summary_text:
                    messages.append({'role': 'user', 'content': summary_text})
                qa_ids = {id(h) for h in compressed_qa}
                remaining_raw = [h for h in raw if id(h) not in qa_ids]
                for h in remaining_raw:
                    self._append_history_item(messages, h)
                if restored_msgs:
                    messages.extend(restored_msgs)

                after_chars = self._estimate_chars(messages)
                logger.info(
                    f"字符预算压缩: "
                    f"压缩前 {len(compressed_qa)} 轮/{estimated_chars} chars, "
                    f"压缩后 {after_chars} chars, "
                    f"节省 {estimated_chars - after_chars} chars, "
                    f"归档={archive_id}"
                )

        logger.debug(f"get_history: raw={len(raw)} 条, 总字符 ~{estimated_chars}, "
                     f"返回 {len(messages)} 条消息")

        return messages


    # ── 历史辅助方法 ──

    @staticmethod
    def _append_history_item(messages: list, h: dict) -> None:
        """将一条 history 条目追加到 messages。

        Args:
            messages: 目标消息列表（会就地修改）。
            h: history 条目字典，支持 'turn'、'event' 和 'qa' 三种类型。
        """
        if h.get('type') == 'turn':
            turn_msgs = h.get('messages', [])
            for m in turn_msgs:
                messages.append(m)
        elif h.get('type') == 'event':
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
        """将事件转换为 <operation：...> 文本，供 LLM 感知用户最近操作。

        Args:
            event_type: 事件类型（如 'delete_all'、'upload'、'delete'、'style_change'）。
            files: 事件涉及的文件列表。

        Returns:
            格式化的操作描述字符串，无匹配时返回空字符串。
        """
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


    @staticmethod
    def _extract_qa_from_entry(h: dict) -> tuple:
        """从 history 条目中提取用户问题与助手回答（兼容 qa/turn 两种格式）。

        Args:
            h: history 条目字典。

        Returns:
            (user_question, assistant_answer) 的元组。
        """
        if h.get('type') == 'turn':
            msgs = h.get('messages', [])
            user_q = ""
            assistant_a = ""
            for m in msgs:
                if m.get('role') == 'user' and isinstance(m.get('content'), str):
                    user_q = m['content']
                elif m.get('role') == 'assistant' and isinstance(m.get('content'), str):
                    assistant_a = m['content']
            return user_q, assistant_a
        return h.get('user', ''), h.get('assistant', '')

    @staticmethod
    def _estimate_chars(messages: list) -> int:
        """返回消息列表的总字符数。

        Args:
            messages: 消息字典列表。

        Returns:
            所有消息 content 字段的总字符数。
        """
        total = 0
        for m in messages:
            text = str(m.get("content", "") or "")
            if text:
                total += len(text)
        return total

    @staticmethod
    def _pick_consolidation_boundary(qa_entries: list, estimated: int, target: int) -> int | None:
        """从最早的消息开始，找到满足释放需求的 user-turn 边界。

        Args:
            qa_entries: 历史 QA 条目列表。
            estimated: 当前消息总字符数。
            target: 目标字符数上限。

        Returns:
            边界索引（要压缩的条目数），None 表示无需压缩。
        """
        need_to_free = estimated - target
        if need_to_free <= 0:
            return None
        try:
            accumulated = 0
            for i, entry in enumerate(qa_entries[:-2]):
                q, a = IntegratedSystem._extract_qa_from_entry(entry)
                text = (q or '') + (a or '')
                accumulated += len(text)
                if accumulated >= need_to_free:
                    return i + 1
        except Exception:
            pass
        return len(qa_entries) - 2

    def _build_consolidated_summary(self, compressed_qa: list) -> str:
        """用 LLM 对早期对话生成摘要。失败时回退到简单拼接。

        Args:
            compressed_qa: 需要压缩的历史 QA 条目列表。

        Returns:
            摘要文本字符串，失败时返回空字符串。
        """
        try:
            turns = []
            for h in compressed_qa:
                q, a = self._extract_qa_from_entry(h)
                if q or a:
                    turns.append(f"用户: {q[:300]}" if q else "(无问题)")
                    if a:
                        turns.append(f"助手: {a[:300]}")
            if not turns:
                return ""
            prompt = (
                "请用中文总结以下对话中用户的核心问题和已获取的关键信息。"
                "只输出总结本身，不要附加说明。\n\n"
                + "\n".join(turns)
            )
            if not hasattr(self, '_summary_client'):
                from base.llm_client import OpenAIClient
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

        qs = "；".join(
            self._extract_qa_from_entry(h)[0][:60]
            for h in compressed_qa if self._extract_qa_from_entry(h)[0]
        )
        return f"（历史摘要：用户之前的问题——{qs}。如需查阅完整历史，请调用 read_archive 工具。）"


    def _check_style_change(self, session_id: str, style: Optional[str]) -> None:
        """检测 style 切换，记录事件到历史。

        Args:
            session_id: 会话 ID。
            style: 新的回答风格名称。
        """
        prev = self.session_last_style.get(session_id)
        if prev is not None and prev != style:
            self.data_store.insert_session_event(session_id, 'style_change', [str(style or 'default')])
            logger.info(f"style 切换: {prev} → {style or 'default'}")
        self.session_last_style[session_id] = style or 'default'


    # ── 问答入口 ──

    def run_agent(self, session_id, question, partition: str = None, style: Optional[str] = None, stream=False, workflow: Optional[str] = None):
        """处理用户查询，返回答案（非流式）或事件生成器（流式）。

        调用方（API）已持有会话锁。

        Args:
            session_id: 会话 ID。
            question: 用户问题。
            partition: 知识库分区（用户名）。
            style: 回答风格。
            stream: 是否流式。
            workflow: 工作流名称（None 为自动识别）。

        Returns:
            非流式模式返回答案字符串；流式模式返回事件生成器。
        """
        if stream:
            return self._run_agent_stream(session_id, question, partition, style, workflow=workflow)

        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        try:
            answer = self.rag_qa.generate_answer(
                question,
                stream=False,
                history=history,
                partition=partition,
                session_id=session_id,
                style=style,
                workflow_name=workflow,
                data_store=self.data_store,
            )
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            log_qa(partition, session_id, question, answer)
            return answer

        log_qa(partition, session_id, question, answer)
        return answer


    def _run_agent_stream(self, session_id, question, partition=None, style=None, workflow=None):
        """流式版本的 run_agent，使用线程安全队列传递事件。

        Args:
            session_id: 会话 ID。
            question: 用户问题。
            partition: 知识库分区（用户名）。
            style: 回答风格。
            workflow: 工作流名称。

        Yields:
            事件字典，与 _run_tool_loop_stream 的 yield 格式相同：
            - {"type": "token", "text": "..."}
            - {"type": "status", "status": "..."}
            - {"type": "reasoning", "text": "..."}
        """
        self._check_style_change(session_id, style)
        logger.debug(f"会话 session={session_id}")

        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event

        def is_cancelled():
            return cancel_event.is_set()

        def save_cp(phase: str, payload: dict):
            from .checkpoint import Checkpoint
            cp = Checkpoint(
                phase=phase,
                iteration=payload.get("iteration", 0),
                model=getattr(self.rag_qa, "chat_model", ""),
                pending_calls=payload.get("pending_calls"),
                completed_results=payload.get("completed_results"),
            )
            self.checkpoints.save(session_id, cp)

        import queue as _queue
        session_queue = _queue.Queue()
        _DONE = object()

        def _worker():
            try:
                gen = self.rag_qa.generate_answer(
                    query=question,
                    stream=True,
                    history=self.get_history(session_id),
                    partition=partition,
                    session_id=session_id,
                    style=style,
                    workflow_name=workflow,
                    cancel_check=is_cancelled,
                    on_checkpoint=save_cp,
                    emit_event=session_queue.put,
                    data_store=self.data_store,
                )
                for _ in gen:
                    pass
            except Exception as e:
                logger.error(f"生成回答异常: {e}")
                session_queue.put({"type": "status", "status": "error", "error": str(e)})
            finally:
                session_queue.put(_DONE)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        ans = []
        try:
            while True:
                try:
                    ev = session_queue.get(timeout=1)
                except _queue.Empty:
                    if is_cancelled():
                        yield {"type": "status", "status": "cancelled"}
                        logger.info(f"生成被中断: session={session_id}")
                        return
                    if not t.is_alive():
                        logger.warning(f"工作线程已退出，session={session_id}")
                        break
                    continue
                if ev is _DONE:
                    break
                if is_cancelled():
                    yield {"type": "status", "status": "cancelled"}
                    logger.info(f"生成被中断: session={session_id}")
                    return
                if ev.get("type") == "token":
                    ans.append(ev.get("text", ""))
                yield ev
        finally:
            self._cancel_events.pop(session_id, None)
            t.join(timeout=2)

        answer = ''.join(ans)
        log_qa(partition, session_id, question, answer)
        logger.debug(f"回答成功 len={len(answer)}")


