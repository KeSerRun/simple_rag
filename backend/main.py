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
        最末若干条按 max_history_length 截取。
        """
        raw = self.data_store.get_session_history(session_id) or []
        if raw and len(raw) > conf.max_history_length:
            raw = raw[-conf.max_history_length:]
        messages = []
        for h in raw:
            if h.get('type') == 'event':
                tag = self._event_to_tag(h.get('event_type', ''), h.get('files', []))
                if tag:
                    messages.append({'role': 'user', 'content': tag})
            else:
                # 兼容老数据 (无 type 字段) 和 type='qa'
                messages.append({'role': 'user', 'content': h.get('user', '')})
                messages.append({'role': 'assistant', 'content': h.get('assistant', '')})
        return messages

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
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer = self.rag_qa.generate_answer(
            question, stream=False, history=history, partition=partition, style=style,
        )
        logger.info(f"生成的回答: {answer}")
        # 将会话历史记录存储,记录 session_id 以关联同一会话的问答对
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def answer_generator(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """流式返回答案的生成器"""
        history = self.get_history(session_id)
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer_iter = self.rag_qa.generate_answer(
            question, stream=True, history=history, partition=partition, style=style,
        )
        ans = []
        for chunk in answer_iter:
            # generater() 每次 yield 的是累积 token 列表,取最新增量
            ans = chunk
            yield chunk[-1]
        answer = ''.join(ans)
        logger.info(f"生成的回答: {answer}")
        # 将会话历史记录存储
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)

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
                for token in self.answer_generator(session_id, args.question, partition=partition):
                    print(token, end="", flush=True)
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
