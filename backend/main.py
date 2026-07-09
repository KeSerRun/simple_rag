# ===== 主入口：解析命令行参数并执行 =====
# main 函数只负责：
#   1. 解析命令行参数（argparse）
#   2. 创建 IntegratedSystem 实例
#   3. 将控制权交给 run_cli 执行对应命令
#
# 所有业务逻辑（问答、历史管理、任务追踪、CLI 分发等）
# 均在 agent/integrated_system.py 的 IntegratedSystem 类中实现。

import argparse
import sys

from agent import IntegratedSystem


def build_parser():
    """构建命令行参数解析器。"""
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


def main():
    """主函数：解析参数 → 创建系统 → 执行命令。"""
    system = IntegratedSystem()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    system.run_cli(args)


if __name__ == "__main__":
    main()
