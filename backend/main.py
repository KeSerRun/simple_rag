# 导入配置类
from base.config import conf
# 导入日志
from base.logger import logger, log_qa
# 导入 JSON 持久化存储
from storage import JSONFileStore
# 导入 RAG_QA 问答系统类
from rag_qa import RAGSystem
# 导入 uuid 模块用于生成唯一标识符
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
        # 会话级上传文件追踪（内存）
        self.session_files = {}

    def get_history(self, session_id):
        # 获取会话历史记录,供 RAG_QA 生成答案时参考
        history = self.data_store.get_session_history(session_id)
        # 限制历史记录长度,避免过长的历史影响模型性能
        if history and len(history) > conf.max_history_length:
            history = history[-conf.max_history_length:]
        # 格式化历史记录为模型输入的格式
        history = [[{'role': 'user', 'content': h['user']},
                    {'role': 'assistant', 'content': h['assistant']}] for h in (history or [])]
        # 展开为单层列表
        history = [item for sublist in history for item in sublist]

        # 注入上传文件上下文
        upload_ctx = self.get_upload_context(session_id)
        if upload_ctx:
            history.insert(0, {'role': 'user', 'content': upload_ctx})
        return history

    def record_upload(self, session_id, filenames):
        """记录会话上传的文件名"""
        if session_id not in self.session_files:
            self.session_files[session_id] = []
        self.session_files[session_id].extend(filenames)

    def get_upload_context(self, session_id):
        """生成 <operation：upload files: ...> 上下文标签"""
        files = self.session_files.get(session_id, [])
        if not files:
            return None
        # 去重保序
        seen = set()
        unique = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        if len(unique) > 3:
            return f"<operation：upload files: {', '.join(unique[:3])}等>"
        return f"<operation：upload files: {', '.join(unique)}>"

    def get_answer(self, session_id, question, partition: str = None):
        """处理用户查询,返回答案"""
        history = self.get_history(session_id)
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer = self.rag_qa.generate_answer(question, stream=False, history=history, partition=partition)
        logger.info(f"生成的回答: {answer}")
        # 将会话历史记录存储,记录 session_id 以关联同一会话的问答对
        self.data_store.insert_session_history(session_id, question, answer)
        log_qa(partition, session_id, question, answer)
        return answer

    def answer_generator(self, session_id, question, partition: str = None):
        """流式返回答案的生成器"""
        history = self.get_history(session_id)
        logger.info(f"收到查询: {question}")
        # 使用 RAG_QA 生成答案
        answer_iter = self.rag_qa.generate_answer(question, stream=True, history=history, partition=partition)
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
        session_id = args.session or "cli-" + str(abs(hash(args.question)) % 100000) if hasattr(args, "question") else "cli-" + str(uuid.uuid4())[:8]
        if hasattr(args, "session") and args.session:
            session_id = args.session
        elif not hasattr(args, "session") or not args.session:
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
                self.record_upload(session_id, [name])
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
