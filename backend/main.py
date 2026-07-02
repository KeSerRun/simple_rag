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


'''集成系统类，封装数据存储 + RAG_QA,提供统一的问答接口'''
class IntegratedSystem:
    def __init__(self):
        # 数据存储（用户/会话/历史 JSON 文件版）
        self.data_store = JSONFileStore()
        # 初始化 RAG_QA 问答系统
        self.rag_qa = RAGSystem()
        # 初始化向量存储
        self.vector_store = self.rag_qa.vector_store

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

            mode = "规则拼接" if len(compressed_qa) <= 3 else "LLM 摘要"

            # 生成摘要
            summary_text = ""
            if len(compressed_qa) <= 3:
                questions = [h.get('user', '') for h in compressed_qa if h.get('user')]
                if questions:
                    summary_text = "（历史摘要）用户之前的问题：" + "；".join(
                        q[:60] for q in questions if q
                    )
            else:
                summary_text = self._summarize_history(compressed_qa) or ""

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
                f"方式={mode}"
            )
        else:
            for h in raw:
                self._append_history_item(messages, h)

        return messages

    def _summarize_history(self, entries: list) -> str:
        """用 LLM 对历史对话做语义摘要。"""
        from rag.core.openai_client import OpenAIClient

        # 构建摘要 prompt
        turns = []
        for h in entries:
            u = h.get('user', '') or ''
            a = h.get('assistant', '') or ''
            if u:
                turns.append(f"用户：{u[:200]}")
            if a:
                turns.append(f"助手：{a[:200]}")
        if not turns:
            return ""
        text = "\n".join(turns)

        client = OpenAIClient(
            api_key=conf.openai_api_key, base_url=conf.openai_base_url,
            timeout=conf.openai_timeout, max_retries=conf.openai_max_retries,
        )
        try:
            resp = client.chat(
                messages=[{
                    "role": "system",
                    "content": "你是一个摘要助手。将以下对话浓缩为一段话（150字以内），"
                               "保留核心问题和关键结论，不要丢失重要数据和时间信息。"
                }, {
                    "role": "user",
                    "content": f"请摘要以下对话：\n\n{text}",
                }],
                model=conf.summary_model,
                stream=False,
                temperature=0.1,
                max_tokens=300,
            )
            return (resp or "").strip()
        except Exception as e:
            logger.warning(f"LLM 摘要失败，回退规则拼接: {e}")
            # 回退到规则拼接
            questions = [h.get('user', '')[:60] for h in entries if h.get('user')]
            if questions:
                return "用户之前的问题：" + "；".join(questions)
            return ""

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
        return ""

    def get_answer(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """处理用户查询,返回答案"""
        history = self.get_history(session_id)
        try:
            answer = self.rag_qa.generate_answer(
                question, stream=False, history=history, partition=partition, style=style,
            )
            logger.info(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            log_qa(partition, session_id, question, answer)
            return answer
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def answer_generator(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """流式返回答案的生成器"""
        history = self.get_history(session_id)
        answer_iter = self.rag_qa.generate_answer(
            question, stream=True, history=history, partition=partition, style=style,
        )
        ans = []
        for event in answer_iter:
            # 流式格式: {"type": "token", "text": "..."} 或 {"type": "status", ...}
            # yield 原始事件, 由 _sse_wrapper JSON 编码后传前端
            if event.get("type") == "token":
                ans.append(event.get("text", ""))
            yield event  # 传递原始事件, 不过滤
        answer = ''.join(ans)
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
