"""HTTP 客户端工具：发送自定义 HTTP 请求，支持复用浏览器 Cookie/UA + 大文件保存。"""

import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from agent.tool_registry import registry
from utils.logger import log_warning
from utils.paths import OUTPUT_DIR
from utils.sanitizer import sanitize_filename, sanitize_url, truncate

# Bug 3 (Coco 报告): per-host 连续超时熔断
# 同一 host 连续 3 次超时 → 本 session 内不再访问，避免 LLM 反复重试浪费时间/token
_HTTP_TIMEOUT_SECONDS: float = 30.0
_HTTP_TIMEOUT_STREAK_LIMIT: int = 3
_HTTP_HOST_TIMEOUT_STREAK: dict[str, int] = {}
_HTTP_HOST_CIRCUIT_OPEN: set[str] = set()


def _reset_http_circuit() -> None:
    """测试用：清空熔断状态。"""
    _HTTP_HOST_TIMEOUT_STREAK.clear()
    _HTTP_HOST_CIRCUIT_OPEN.clear()


@registry.tool(
    name="http_request",
    description=(
        "【作用】通用 HTTP 客户端——发任意方法的请求，返回 status / headers / body（或保存到文件）。Argus 第二高频工具，仅次于浏览器。"
        "【关键参数】url；method（默认 GET）；headers（JSON 字符串自定义请求头）；body（POST/PUT 的请求体）；"
        "use_browser_session='true'（注入登录后 cookie/UA/Referer，登录态调 API 必备）；"
        "save_to（大响应保存到 ~/.argus/output/downloads/<save_to>，避免 4000 字截断，返回路径而非内容）。"
        "【何时用】(1) 抓单个 URL 拿 JSON / HTML（轻量，比 browser 快）；(2) 登录后 API 探测 → use_browser_session='true'；"
        "(3) 下大 JS / sourcemap → save_to='app.js'；(4) 漏洞手注（in-band SQLi / SSRF / IDOR）；"
        "(5) 探测 robots.txt / sitemap.xml / .well-known / .git/HEAD。"
        "【避坑】(1) 抓需 JS 渲染的页面会拿到 SPA 骨架，要换 browser_navigate；"
        "(2) use_browser_session='true' 但浏览器没启动时只警告不失败，记得先 browser_navigate；"
        "(3) headers 必须是合法 JSON 字符串（用双引号），单引号会失败；"
        "(4) 默认 follow_redirects=True，要观察 3xx Location 头需用专门的重定向工具；"
        "(5) save_to 文件名经 sanitize，不要带路径分隔符。"
    ),
    params={
        "url": {"type": "string", "description": "请求 URL"},
        "method": {
            "type": "string",
            "description": "HTTP 方法（GET/POST/PUT/DELETE 等），默认 GET",
            "required": False,
        },
        "headers": {
            "type": "string",
            "description": '自定义请求头，JSON 格式字符串,如 \'{"Authorization": "Bearer xxx"}\'',
            "required": False,
        },
        "body": {
            "type": "string",
            "description": "请求体内容（用于 POST/PUT 等方法）",
            "required": False,
        },
        "use_browser_session": {
            "type": "string",
            "description": (
                "'true' 表示从当前浏览器复用 Cookie/UA/Referer（用户已登录时调 API 必备）。"
                "默认 'false'，发独立请求。"
            ),
            "required": False,
        },
        "save_to": {
            "type": "string",
            "description": (
                "可选：把完整响应体保存到 ~/.argus/output/downloads/<save_to>。"
                "适合下载大 JS/二进制文件，避免输出截断。返回文件路径而非响应体内容。"
            ),
            "required": False,
        },
    },
)
async def http_request(
    url: str,
    method: str = "GET",
    headers: str = "",
    body: str = "",
    use_browser_session: str = "false",
    save_to: str = "",
) -> str:
    url = sanitize_url(url)
    method = method.upper()

    # Bug 3: per-host 熔断检查
    host = (urlparse(url).hostname or "").lower()
    if host and host in _HTTP_HOST_CIRCUIT_OPEN:
        return (
            f"[CIRCUIT_OPEN] HTTP 请求拒绝：{host} 已连续 {_HTTP_TIMEOUT_STREAK_LIMIT} 次超时，本 session 内不再访问。\n"
            f"建议改用 browser_navigate（带 JS 渲染，可能绕过反爬）或换其他目标。"
        )

    custom_headers: dict = {}
    if headers:
        try:
            custom_headers = json.loads(headers)
        except json.JSONDecodeError:
            return f"请求头 JSON 解析失败: {headers}"

    # 复用浏览器会话：注入 Cookie / UA / Referer（用户显式头优先）
    session_info = ""
    if str(use_browser_session).lower() in {"true", "1", "yes"}:
        from tools.browser import get_browser_session

        session = await get_browser_session(url=url)
        if session:
            if session.get("cookies") and "cookie" not in {k.lower() for k in custom_headers}:
                custom_headers["Cookie"] = session["cookies"]
            if session.get("user_agent") and "user-agent" not in {k.lower() for k in custom_headers}:
                custom_headers["User-Agent"] = session["user_agent"]
            if session.get("referer") and "referer" not in {k.lower() for k in custom_headers}:
                custom_headers["Referer"] = session["referer"]
            cookie_count = session["cookies"].count("=") if session.get("cookies") else 0
            session_info = f"  ↳ 已注入浏览器 session ({cookie_count} cookies)\n"
        else:
            session_info = "  ↳ ⚠ 浏览器未启动，未注入 session\n"

    # 默认请求 gzip 解压（避免 chunked 截断）
    custom_headers.setdefault("Accept-Encoding", "gzip, deflate, br")

    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,  # Bug 3: 30s（之前 60s 太长）
            follow_redirects=True,
            verify=False,
        ) as client:
            kwargs: dict[str, Any] = {
                "method": method,
                "url": url,
                "headers": custom_headers,
            }
            if body and method in ("POST", "PUT", "PATCH"):
                kwargs["content"] = body

            resp = await client.request(**kwargs)

            # 强制读完整 body（防止 lazy decode 截断）
            raw_bytes = await resp.aread()
            resp_headers = "\n".join(f"  {k}: {v}" for k, v in resp.headers.items())

            # save_to: 大文件路径模式
            if save_to:
                fname = sanitize_filename(save_to)
                save_dir = os.path.join(OUTPUT_DIR, "downloads")
                os.makedirs(save_dir, exist_ok=True)
                filepath = os.path.join(save_dir, fname)
                with open(filepath, "wb") as f:
                    f.write(raw_bytes)
                return (
                    f"状态码: {resp.status_code}\n"
                    f"URL: {resp.url}\n"
                    f"{session_info}"
                    f"响应头:\n{resp_headers}\n"
                    f"已保存到: {filepath} ({len(raw_bytes)} 字节)"
                )

            # 默认：返回响应体（截断显示，但解码用完整 bytes）
            try:
                text = raw_bytes.decode(resp.encoding or "utf-8", errors="replace")
            except (LookupError, ValueError):
                text = raw_bytes.decode("utf-8", errors="replace")

            # Bug 3: 成功路径 → 重置该 host 的超时计数
            if host:
                _HTTP_HOST_TIMEOUT_STREAK.pop(host, None)

            return (
                f"状态码: {resp.status_code}\n"
                f"URL: {resp.url}\n"
                f"{session_info}"
                f"响应头:\n{resp_headers}\n"
                f"响应体 ({len(raw_bytes)} 字节):\n{truncate(text, 4000)}"
            )
    except httpx.TimeoutException as e:
        # Bug 3: 单独处理超时 → 累加 host 计数，达到阈值熔断
        if host:
            streak = _HTTP_HOST_TIMEOUT_STREAK.get(host, 0) + 1
            _HTTP_HOST_TIMEOUT_STREAK[host] = streak
            if streak >= _HTTP_TIMEOUT_STREAK_LIMIT:
                _HTTP_HOST_CIRCUIT_OPEN.add(host)
                log_warning(f"http_request 熔断: {host} 连续 {streak} 次超时")
                return (
                    f"[CIRCUIT_OPEN] HTTP 请求超时（已熔断 {host}）：连续 {streak} 次超时（≥{_HTTP_TIMEOUT_STREAK_LIMIT}）。\n"
                    f"本 session 内不再访问该 host。建议改用 browser_navigate 或换目标。"
                )
            return (
                f"HTTP 请求超时 ({_HTTP_TIMEOUT_SECONDS:.0f}s, {streak}/{_HTTP_TIMEOUT_STREAK_LIMIT}): {host}\n"
                f"({e.__class__.__name__})"
            )
        return f"HTTP 请求超时 ({_HTTP_TIMEOUT_SECONDS:.0f}s): {e}"
    except Exception as e:
        return f"HTTP 请求失败: {e}"
