"""HTTP 接口模块,按业务域分文件:auth / sessions / history / query / documents / admin

# ── 模块职责

入口 app.py 通过 ``include_router`` 注册::

    from api import auth, sessions, history, query, documents, admin
    app.include_router(auth.router)
    ...
"""
from . import admin, auth, documents, history, query, sessions

__all__ = ["admin", "auth", "documents", "history", "query", "sessions"]
