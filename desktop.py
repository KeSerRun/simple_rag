# ── 桌面客户端入口 ──────────────────────────────────────────────
"""
PyWebView 桌面客户端 —— 将 FastAPI Web 应用包装为原生 Windows 窗口。

用法:
    python desktop.py               # 开发模式运行
    # 或打包后双击 rag-simple.exe

依赖:
    pip install pywebview
"""

from __future__ import annotations

import os
import sys
import time
import threading
import urllib.request
import urllib.error


# ═══════════════════════════════════════════════════════════════
# PyInstaller 静态导入 —— 确保打包时分析器能追踪到所有模块
# ═══════════════════════════════════════════════════════════════
if False:
    # 仅用于 PyInstaller 依赖追踪，实际运行时永不执行
    import app as _                      # noqa: F401
    import api.auth as _                # noqa: F401
    import api.documents as _           # noqa: F401
    import api.history as _             # noqa: F401
    import api.query as _               # noqa: F401
    import api.sessions as _            # noqa: F401
    import api.admin.dashboard as _     # noqa: F401
    import base.config as _             # noqa: F401
    import agent.loop as _              # noqa: F401
    import agent.integrate as _         # noqa: F401
    import rag.vector_store as _        # noqa: F401
    import rag.pdf_parser as _          # noqa: F401
    import storage.json_store as _      # noqa: F401


# ── 路径处理 ────────────────────────────────────────────────────


def get_base_dir() -> str:
    """获取项目根目录（开发模式用 __file__，打包后用 exe 目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def ensure_workdir():
    """切换到项目根目录，确保 config.ini / data 能正确加载。"""
    base = get_base_dir()
    target = os.path.abspath(base)
    if os.path.abspath(os.getcwd()) != target:
        os.chdir(target)


# ── 后端管理 ────────────────────────────────────────────────────

BACKEND_URL = "http://127.0.0.1:11000"
BACKEND_PORT = 11000
_HEALTH_URL = f"{BACKEND_URL}/api/health"


def start_backend():
    """在后台线程中启动 uvicorn 服务器。"""
    import uvicorn

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=BACKEND_PORT,
        log_level="warning",
        access_log=False,
    )


def wait_for_server(url: str = _HEALTH_URL, timeout: float = 30) -> bool:
    """轮询等待后端服务就绪，超时返回 False。"""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.3)
    return False


# ── 窗口管理 ────────────────────────────────────────────────────


def open_window():
    """创建并启动 PyWebView 桌面窗口。"""
    import webview

    webview.create_window(
        title="RAG Simple",
        url=BACKEND_URL,
        width=1280,
        height=860,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )
    webview.start()


# ── 主入口 ──────────────────────────────────────────────────────


def _fix_bundle_paths():
    """PyInstaller 打包后，将项目根目录修正为 exe 同级目录。"""
    if getattr(sys, "frozen", False):
        import base.config as c
        base_dir = os.path.dirname(sys.executable)
        c._project_root = base_dir

        # 重新加载配置，捕获校验异常（如 MinerU Key 格式不对）
        try:
            c.conf.__init__(os.path.join(base_dir, "config.ini"))
        except ValueError as e:
            print(f"[desktop] 配置警告: {e}", file=sys.stderr)

        # index_file 默认是 dist/index.html，但前端文件直接放 exe 同级了
        c.conf.index_file = os.path.join(base_dir, "index.html")

        # 提前导入 app，修正 dist_path（避免 app.py 用 __file__ 找到 _internal/dist）
        try:
            import app as _app_mod
            _app_mod.dist_path = base_dir
            _app_mod.assets_path = os.path.join(base_dir, "assets")
        except ValueError as e:
            print(f"[desktop] 配置警告: {e}", file=sys.stderr)


def main():
    # GUI 模式（console=False）下 stdout/stderr 为空，重定向到 logs 目录
    if getattr(sys, "frozen", False) and not sys.stdout:
        log_dir = os.path.join(get_base_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "console.log")
        sys.stdout = open(log_path, "a", encoding="utf-8")
        sys.stderr = sys.stdout

    ensure_workdir()
    _fix_bundle_paths()

    # 检查是否在本项目目录下
    if not os.path.isfile("config.ini"):
        print("[desktop] 错误: 未找到 config.ini，请确保在项目根目录运行。")
        sys.exit(1)

    # 创建超级用户（与 app.py 行为一致）
    try:
        from api.auth import create_superusers

        create_superusers()
    except Exception:
        pass  # 非致命

    # 启动后端（守护线程，主线程退出自动回收）
    t = threading.Thread(target=start_backend, daemon=True)
    t.start()

    print(f"[desktop] 后端启动中... (端口 {BACKEND_PORT})")
    ready = wait_for_server()
    if not ready:
        print("[desktop] 错误: 后端启动超时，请检查 config.ini 配置。")
        sys.exit(1)

    print("[desktop] 后端就绪，正在打开桌面窗口...")
    open_window()

    print("[desktop] 窗口已关闭，程序退出。")
    sys.exit(0)


if __name__ == "__main__":
    main()
