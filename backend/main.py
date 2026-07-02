# 导入配置类
from base.config import conf
# 导入日志
from base.logger import logger, log_qa
# 导入 JSON 持久化存储
from storage import JSONFileStore
# 导入 RAG_QA 问答系统类
from agent import RAGSystem
# 导入 uuid 模块用于生成唯一标识符
from typing import Optional
import uuid
import argparse
import os
import sys
import re


'''集成系统类，封装数据存储 + RAG_QA,提供统一的问答接口'''
class IntegratedSystem:
    def __init__(self):
        self.data_store = JSONFileStore()
        self.rag_qa = RAGSystem(data_store=self.data_store)
        self.vector_store = self.rag_qa.vector_store
        # 追踪每个会话当前使用的 style（用于检测切换）
        self.session_last_style: dict[str, str] = {}
        # 追踪每个会话的短期/长期任务
        self.session_tasks: dict[str, dict] = {}  # {session_id: {"short": [...], "long": [...]}}
        # 会话轮次计数器（用于任务时效判断）
        self.session_turn: dict[str, int] = {}

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
        if not raw:
            return []
        messages = []

        # 1) 硬截断: 按轮次截取最近 N 条 QA
        qa_entries = [h for h in raw if h.get('type') != 'event']
        if len(qa_entries) > conf.max_history_length:
            # 找出哪些 QA 被截断
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

            # 归档：将压缩掉的轮次存入归档，供 LLM 通过 read_archive 工具回溯
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
            summary_text = f"（历史摘要 #{archive_id}：用户之前的问题：" + "；".join(
                h.get('user', '')[:60] for h in compressed_qa if h.get('user')
            ) + "。如需查阅完整历史，请调用 read_archive 工具。）"

            if summary_text:
                messages.append({'role': 'user', 'content': summary_text})

            for h in remaining_raw:
                self._append_history_item(messages, h)

            # 压缩后字符数
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

    def _check_style_change(self, session_id: str, style: Optional[str]) -> None:
        """检测 style 切换，记录事件到历史。"""
        prev = self.session_last_style.get(session_id)
        if prev is not None and prev != style:
            self.data_store.insert_session_event(session_id, 'style_change', [str(style or 'default')])
            logger.info(f"style 切换: {prev} → {style or 'default'}")
        self.session_last_style[session_id] = style or 'default'

    # ─── 会话任务追踪 ───────────────────────────────

    TASK_MAX_STALE_TURNS = 5  # 超过 N 轮未被引用的任务标记为 superseded
    TASK_MAX_SHORT = 3        # 短期活跃任务上限
    TASK_MAX_SHORT_HIST = 20  # 短期任务总历史上限（含已关闭）
    TASK_MAX_LONG = 10        # 长期任务上限
    TASK_OVERLAP_RATIO = 0.2  # 话题关联判定阈值

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
        tasks = self.session_tasks.get(session_id, {"short": [], "long": []})
        short = [t["desc"] for t in tasks.get("short", []) if t.get("status") == "active"]
        long_ = [t["desc"] for t in tasks.get("long", []) if t.get("status") == "active"]
        return short, long_

    def _save_session_tasks(self, session_id: str, short: list[dict], long_: list[dict]):
        """保存会话任务列表。"""
        self.session_tasks[session_id] = {"short": short, "long": long_}

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
            # 同 workflow → 相关
            if wf_name and t.get("workflow") == wf_name:
                return True
            # 关键词重叠 → 相关
            if self._is_related_to(q_words, t["desc"]):
                return True
            return False

        # ── 1. 关闭已无关的旧任务 ────────────────────
        for t in raw_short:
            if t["status"] != "active":
                continue
            if _task_active(t):
                # 仍相关 → 刷新活跃轮次
                t["last_active_turn"] = turn
            else:
                # 话题切换 或 超期
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
                "desc": current_desc, "status": "active",
                "turn": turn, "last_active_turn": turn,
                "workflow": wf_name,
            }
            active_tasks = [new_task]

        # active 在前（不超过上限），已关闭的在后面（用于历史提升判断）
        active_part = (active_tasks + [t for t in others if t["status"] == "active"])[:self.TASK_MAX_SHORT]
        inactive_part = [t for t in raw_short if t["status"] != "active"]
        new_short = (active_part + inactive_part)[:self.TASK_MAX_SHORT_HIST]

        # ── 3. 长期任务：同一 desc 再次出现时提升 ────
        long_descs = {t["desc"] for t in raw_long}
        if current_desc not in long_descs:
            # 检查在历史短期中是否曾出现过（不是当前轮）
            hist_descs = {t["desc"] for t in raw_short} | {
                t["desc"] for t in self.session_tasks.get(session_id, {}).get("short", [])
            }
            if current_desc in hist_descs:
                raw_long.append({
                    "desc": current_desc, "status": "active",
                    "turn": turn, "last_active_turn": turn,
                    "workflow": wf_name,
                })
                logger.info(f"提升为长期任务: '{current_desc}'")

        # 长期任务也做超时检测
        for t in raw_long:
            if t["status"] != "active":
                continue
            if turn - t.get("last_active_turn", t["turn"]) > self.TASK_MAX_STALE_TURNS * 2:
                t["status"] = "superseded"
                logger.info(f"长期任务过期: '{t['desc']}'")

        self._save_session_tasks(session_id, new_short, raw_long[:self.TASK_MAX_LONG])

    def get_answer(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """处理用户查询,返回答案"""
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        # Workflow 路由检测（用于任务提取）
        wf_name = self.rag_qa.workflow_router.match(question)
        short_tasks, long_tasks = self._load_session_tasks(session_id)

        try:
            answer = self.rag_qa.generate_answer(
                question, stream=False, history=history,
                partition=partition, style=style,
                short_term_tasks=short_tasks,
                long_term_tasks=long_tasks,
            )
            logger.info(f"回答成功 len={len(answer)}")
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
        """流式返回答案的生成器"""
        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        wf_name = self.rag_qa.workflow_router.match(question)
        short_tasks, long_tasks = self._load_session_tasks(session_id)

        answer_iter = self.rag_qa.generate_answer(
            question, stream=True, history=history,
            partition=partition, style=style,
            short_term_tasks=short_tasks,
            long_term_tasks=long_tasks,
        )
        ans = []
        for event in answer_iter:
            if event.get("type") == "token":
                ans.append(event.get("text", ""))
            yield event
        answer = ''.join(ans)

        self._update_tasks(session_id, question, wf_name)
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        logger.info(f"回答成功 len={len(answer)}")

# -- replaced by run_cli --

    def run_cli(self, args):
        """CLI entry point"""
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


def build_parser():
    p = argparse.ArgumentParser(description="RAG CLI")
    sp = p.add_subparsers(dest="command")

    q = sp.add_parser("query", help="ask a question")
    q.add_argument("question", help="question text")
    q.add_argument("--stream", action="store_true", help="stream output")

    u = sp.add_parser("upload", help="upload document(s)")
    u.add_argument("path", help="file or directory path")

    c = sp.add_parser("chat", help="interactive chat mode")

    i = sp.add_parser("info", help="show session info")

    for sub in [q, u, c, i]:
        sub.add_argument("--session", help="session id")
        sub.add_argument("--partition", help="partition/user id")

    return p


if __name__ == "__main__":
    system = IntegratedSystem()
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    system.run_cli(args)
