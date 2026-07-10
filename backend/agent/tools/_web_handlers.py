"""Web 工具 handlers: 联网搜索 / 读取网页全文 + 搜索后端实现。
注册统一在 registry.py 的 register_all_builtins() 中。"""
from __future__ import annotations

from base.config import conf
from base.logger import logger
from .registry import ToolContext


def _validate_url(url: str) -> str | None:
    """SSRF 防护：验证 URL 合法且非内网地址。返回错误信息或 None（通过）。"""
    import urllib.parse
    import socket

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"不支持的协议: {parsed.scheme}（仅允许 http/https）"

    host = parsed.hostname or ""
    # 禁止访问内网地址
    try:
        ip = socket.gethostbyname(host)
        # 私有 IP 段
        parts = ip.split(".")
        if len(parts) == 4:
            first = int(parts[0])
            if (first == 10
                or (first == 172 and 16 <= int(parts[1]) <= 31)
                or (first == 192 and parts[1] == "168")
                or first == 127
                or first == 0):
                return f"禁止访问内网地址: {url}"
        # 保留地址
        if ip == "255.255.255.255" or ip.startswith("169.254."):
            return f"禁止访问保留地址: {url}"
    except socket.gaierror:
        return None  # 无法解析也放行（可能是临时故障）
    return None  # 通过


# ===== web_search =====
def _exec_web_search(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: web_search
    多后端联网搜索（duckduckgo / searxng / bocha / bing）。
    """
    query = (args.get("query") or "").strip()
    if not query:
        return "(未提供搜索 query)"
    max_results = min(int(args.get("max_results", 5)), 10)

    logger.debug(f"tool web_search query={query!r} max={max_results} backend={conf.search_backend}")

    # 自动补充年份
    from datetime import datetime as _dt
    _now = _dt.now()
    if not __import__('re').search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query):
        query = f"{_now.year}年 {query}"
        logger.debug(f"tool web_search 已补年份: {query!r}")

    backend = conf.search_backend or "duckduckgo"
    if backend == "searxng":
        results = _search_searxng(query, max_results)
    elif backend == "bocha":
        results = _search_bocha(query, max_results)
    elif backend == "bing":
        results = _search_bing(query, max_results)
    else:
        results = _search_duckduckgo(query, max_results)

    if results is None:
        return "(联网搜索暂时不可用，请直接回答，不要重试。)"
    if not results:
        return "(未找到相关搜索结果)"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()
        url = r.get("href", "").strip()
        lines.append(f"[搜索结果 {i}] {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    output = "\n".join(lines).strip()
    logger.debug(f"tool web_search 返回 {len(results)} 条结果, 长度={len(output)}")
    return output


# ===== read_url =====
def _exec_read_url(args: dict, ctx: ToolContext) -> str:
    """
    工具 handler: read_url
    抓取网页 HTML 并提取纯文本（stdlib HTMLParser）。
    """
    url = (args.get("url") or "").strip()
    if not url:
        return "(未提供 URL 参数)"

    # SSRF 防护
    err = _validate_url(url)
    if err:
        logger.warning(f"tool read_url 被 SSRF 防护拦截: {err}")
        return f"({err})"

    logger.debug(f"tool read_url: 开始抓取 {url}")
    try:
        import requests as _req
        resp = _req.get(
            url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        resp.raise_for_status()

        from html.parser import HTMLParser as _HTMLParser

        class _TextExtractor(_HTMLParser):
            def __init__(self):
                super().__init__()
                self._text = []
                self._skip = False
            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True
            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False
                if tag in ("p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div"):
                    self._text.append("\n")
            def handle_data(self, data):
                if not self._skip:
                    self._text.append(data.strip())
            def get_text(self):
                return "".join(self._text)

        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()

        import re as _re
        text = _re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) > 20000:
            text = text[:20000] + "\n\n...(网页内容过长，已截取前 20000 字符)..."

        logger.debug(f"tool read_url 成功: {url} ({len(text)} 字符)")
        return text

    except Exception as e:
        logger.warning(f"tool read_url 失败 ({url}): {e}")
        return f"(读取网页失败: {e})"
# ===== 模块文档字符串 =====
"""Web 搜索后端实现。  # 这个文档字符串说明本模块的功能：实现了多个搜索引擎的后端
# 本模块支持四个不同的搜索后端，可以根据配置自由切换
支持四个后端: DuckDuckGo / SearXNG / 博查 AI / Bing Web Search。
"""

# ===== 导入项目内部模块 =====
from base.config import conf  # 从 base.config 模块导入 conf 配置对象，用于读取配置文件中的各项设置

from base.logger import logger  # 从 base.logger 模块导入 logger 日志记录器，用于记录运行日志和错误信息


# ===== 搜索后端 1: DuckDuckGo =====

def _search_duckduckgo(query: str, max_results: int) -> list | None:
    """
    后端 1: DuckDuckGo 搜索  # 本函数实现 DuckDuckGo 搜索引擎的调用
    特点: 无需 API Key，免费，但国内访问需要 VPN。  # DuckDuckGo 免费但需要翻墙
    优先尝试新版 ddgs 库，回退到旧版 duckduckgo_search 库。  # 先试新库，新库不行再试旧库
    返回 None 表示不可用（库未安装或网络异常）。  # 返回 None 说明搜索不可用
    """
    try:  # 开始异常捕获，尝试使用新版 ddgs 库进行搜索
        from ddgs import DDGS  # 尝试从新版 ddgs 库导入 DDGS 类（这是一个更新的 DuckDuckGo 搜索客户端）
        timeout = int(conf.search_timeout or 10)  # 从配置中读取搜索超时时间（秒），如果没配置则默认用 10 秒
        return list(DDGS(timeout=timeout).text(query, max_results=max_results))  # 创建 DDGS 实例（设置超时），调用 .text() 方法搜索，将结果转为 list 返回
    except ImportError:  # 如果上面的导入失败（新版 ddgs 库没安装），就捕获 ImportError 异常
        try:  # 开始第二个尝试：使用旧版 duckduckgo_search 库
            from duckduckgo_search import DDGS  # 从旧版 duckduckgo_search 库导入 DDGS 类
            return list(DDGS().text(query, max_results=max_results))  # 创建 DDGS 实例，调用 .text() 方法搜索，将结果转为 list 返回
        except ImportError:  # 如果旧版库也没安装，捕获 ImportError 异常
            logger.warning("[tool] duckduckgo_search 库未安装")
            return None  # 返回 None，表示该后端不可用
    except Exception as e:  # 捕获其他所有类型的异常（比如网络连接超时、DNS 解析失败等）
        logger.warning(f"tool duckduckgo 搜索失败: {e}")
        return None  # 返回 None，表示搜索失败


# ===== 搜索后端 2: SearXNG =====

def _search_searxng(query: str, max_results: int) -> list | None:
    """
    后端 2: SearXNG 搜索  # 本函数实现 SearXNG 搜索引擎的调用
    特点: 开源的元搜索引擎，通过自建或公开实例使用，国内可直连。  # SearXNG 是开源元搜索引擎，可以自己搭建
    需在配置中设置 searxng_url（实例地址），否则返回 None。  # 必须在配置文件中填写 SearXNG 实例的 URL
    通过 REST JSON API 获取结果。  # 通过 HTTP REST API 获取 JSON 格式的搜索结果
    """
    base_url = (conf.searxng_url or "").rstrip("/")  # 从配置中读取 searxng_url，如果没配置就用空字符串，然后去掉结尾的斜杠
    if not base_url:  # 如果 base_url 为空（说明没配置 SearXNG 实例地址）
        logger.warning("[tool] searxng_url 未配置")
        return None  # 返回 None，表示该后端不可用

    import urllib.parse as _up  # 导入 urllib.parse 模块并简写为 _up（虽然这里没用上，但可能是为后续扩展准备）
    try:  # 开始异常捕获，准备发起 HTTP 请求
        import requests as _req  # 导入 requests 库并简写为 _req，用于发送 HTTP 请求
        params = {"q": query, "format": "json", "language": "zh-CN"}  # 构造查询参数：搜索关键词 q、返回格式 format 为 json、语言 language 设为中文
        resp = _req.get(  # 发送 GET 请求到 SearXNG 实例
            f"{base_url}/search",  # 拼接完整的搜索 URL：base_url + "/search"
            params=params,  # 传入上面构造的查询参数字典
            timeout=conf.search_timeout,  # 从配置中读取超时时间（秒）
            headers={"User-Agent": "Mozilla/5.0"},  # 设置请求头 User-Agent，伪装成浏览器，避免被拒绝
        )
        resp.raise_for_status()  # 检查响应状态码，如果状态码不是 2xx 就抛出异常
        data = resp.json()  # 将响应内容解析为 JSON 字典
    except Exception as e:  # 捕获所有异常（网络错误、超时、JSON 解析失败、HTTP 错误等）
        logger.warning(f"tool SearXNG 搜索失败: {e}")
        return None  # 返回 None，表示搜索失败

    results = data.get("results", [])  # 从返回的 JSON 数据中提取 results 字段，如果不存在则返回空列表
    out = []  # 初始化一个空列表，用于存放格式化后的搜索结果
    for r in results[:max_results]:  # 遍历结果列表，只取前 max_results 条（切片操作，避免返回过多）
        out.append({  # 将每条结果格式化为统一的字典格式，追加到 out 列表中
            "title": r.get("title", ""),  # 提取结果的标题 title，如果不存在则用空字符串
            "body": r.get("content", ""),  # 提取结果的内容 body/摘要，如果不存在则用空字符串
            "href": r.get("url", ""),  # 提取结果的链接 url，如果不存在则用空字符串
        })
    return out  # 返回格式化后的搜索结果列表


# ===== 搜索后端 3: 博查 AI =====

def _search_bocha(query: str, max_results: int) -> list | None:
    """
    后端 3: 博查 AI Search API  # 本函数实现博查 AI 搜索引擎的调用
    特点: 国内可用，无需 VPN，但需要配置 bocha_api_key。  # 博查 AI 国内可直接访问，但需要 API Key
    调用博查 Web Search API（POST JSON 格式），  # 通过 POST 请求发送 JSON 数据调用博查搜索 API
    兼容多种可能的响应路径（webPages / items / results / data 字段）。  # 兼容博查 API 的不同返回格式
    """
    api_key = conf.bocha_api_key  # 从配置中读取博查 AI 的 API Key
    if not api_key:  # 如果 API Key 为空（没配置）
        logger.warning("[tool] bocha_api_key 未配置")
        return None  # 返回 None，表示该后端不可用

    try:  # 开始异常捕获，准备调用 API
        import requests as _req  # 导入 requests 库并简写为 _req，用于发送 HTTP 请求

        # 博查 Web Search API — 支持 POST JSON
        resp = _req.post(  # 发送 POST 请求到博查搜索 API
            "https://api.bochaai.com/v1/web-search",  # 博查 Web Search API 的地址
            headers={  # 设置 HTTP 请求头
                "Authorization": f"Bearer {api_key}",  # 认证方式：Bearer Token，后面拼接 API Key
                "Content-Type": "application/json",  # 声明请求体格式为 JSON
            },
            json={  # 发送 JSON 格式的请求体（requests 库会自动序列化）
                "query": query,  # 搜索关键词
                "count": max_results,  # 需要返回的结果数量
                "summary": True,  # 是否返回摘要信息，设为 True 表示需要
                "freshness": "noLimit",  # 时间范围限制，"noLimit" 表示不限时间
            },
            timeout=conf.search_timeout,  # 从配置中读取超时时间（秒）
        )
        resp.raise_for_status()  # 检查响应状态码，如果不是 2xx 就抛出异常
        data = resp.json()  # 将响应内容解析为 JSON 字典
    except Exception as e:  # 捕获所有异常（网络错误、超时、API 返回错误等）
        logger.warning(f"tool Bocha 搜索失败: {e}")
        return None  # 返回 None，表示搜索失败

    # 尝试多种可能的响应路径
    raw = data.get("data") or data  # 先尝试获取 data 字段，如果没有则直接用整个响应数据
    items = (  # 尝试从多种可能的字段路径获取搜索结果列表
        raw.get("webPages", {}).get("value")  # 路径 1：webPages.value（Bing 风格的响应格式）
        or raw.get("items")  # 路径 2：items 字段
        or raw.get("results")  # 路径 3：results 字段
        or raw.get("data")  # 路径 4：data 字段
    )
    if not items or not isinstance(items, list):  # 如果提取出的 items 为空或者不是列表类型
        logger.warning(f"tool Bocha 返回格式异常: {str(data)[:300]}")
        return None  # 返回 None，表示无法解析搜索结果

    out = []  # 初始化一个空列表，用于存放格式化后的搜索结果
    for r in items[:max_results]:  # 遍历搜索结果列表，只取前 max_results 条
        out.append({  # 将每条结果格式化为统一的字典格式，追加到 out 列表中
            "title": r.get("name") or r.get("title") or "",  # 提取标题：优先用 name，其次用 title，都没有就用空字符串
            "body": r.get("snippet") or r.get("content") or r.get("summary") or "",  # 提取正文：优先用 snippet，其次 content，再其次 summary，都没有就用空字符串
            "href": r.get("url") or r.get("link") or "",  # 提取链接：优先用 url，其次用 link，都没有就用空字符串
        })
    return out  # 返回格式化后的搜索结果列表


# ===== 搜索后端 4: Bing Web Search =====

def _search_bing(query: str, max_results: int) -> list | None:
    """
    后端 4: Bing Web Search API v7  # 本函数实现微软 Bing 搜索引擎的调用
    特点: 微软 Azure 服务，国内可用，需配置 bing_api_key。  # Bing 搜索使用 Azure 服务，需要 API Key
    通过 GET 请求调用 official Bing API，返回结构化搜索结果。  # 使用 GET 请求调用微软官方的 Bing 搜索 API v7
    """
    api_key = conf.bing_api_key  # 从配置中读取 Bing 的 API Key
    if not api_key:  # 如果 API Key 为空（没配置）
        logger.warning("[tool] bing_api_key 未配置")
        return None  # 返回 None，表示该后端不可用

    try:  # 开始异常捕获，准备调用 API
        import requests as _req  # 导入 requests 库并简写为 _req，用于发送 HTTP 请求

        resp = _req.get(  # 发送 GET 请求到 Bing Search API
            "https://api.bing.microsoft.com/v7.0/search",  # Bing Web Search API v7 的官方地址
            headers={"Ocp-Apim-Subscription-Key": api_key},  # 设置认证请求头：Ocp-Apim-Subscription-Key 是 Bing API 的认证方式，值为 API Key
            params={  # 设置 URL 查询参数
                "q": query,  # 搜索关键词
                "count": max_results,  # 需要返回的结果数量
                "mkt": "zh-CN",  # 市场（market）设为 zh-CN，返回中文结果
            },
            timeout=conf.search_timeout,  # 从配置中读取超时时间（秒）
        )
        resp.raise_for_status()  # 检查响应状态码，如果不是 2xx 就抛出异常
        data = resp.json()  # 将响应内容解析为 JSON 字典
    except Exception as e:  # 捕获所有异常（网络错误、超时、API Key 无效、HTTP 错误等）
        logger.warning(f"tool Bing 搜索失败: {e}")
        return None  # 返回 None，表示搜索失败

    pages = data.get("webPages") or {}  # 从返回的 JSON 中提取 webPages 字段（Bing 返回的结果主体），如果不存在则用空字典
    items = pages.get("value") or []  # 从 webPages 中提取 value 字段（实际的搜索结果列表），如果不存在则用空列表
    out = []  # 初始化一个空列表，用于存放格式化后的搜索结果
    for r in items[:max_results]:  # 遍历搜索结果列表，只取前 max_results 条
        out.append({  # 将每条结果格式化为统一的字典格式，追加到 out 列表中
            "title": r.get("name", ""),  # 提取结果的标题 name，如果不存在则用空字符串
            "body": r.get("snippet", ""),  # 提取结果的摘要 snippet，如果不存在则用空字符串
            "href": r.get("url", ""),  # 提取结果的链接 url，如果不存在则用空字符串
        })
    return out  # 返回格式化后的搜索结果列表
