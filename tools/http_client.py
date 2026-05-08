"""HTTP 客户端工具：发送自定义 HTTP 请求，支持复用浏览器 Cookie/UA + 大文件保存。"""

import json
import os
from typing import Any

import httpx

from agent.tool_registry import registry
from utils.paths import OUTPUT_DIR
from utils.sanitizer import sanitize_filename, sanitize_url, truncate


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
            timeout=60.0,
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

            return (
                f"状态码: {resp.status_code}\n"
                f"URL: {resp.url}\n"
                f"{session_info}"
                f"响应头:\n{resp_headers}\n"
                f"响应体 ({len(raw_bytes)} 字节):\n{truncate(text, 4000)}"
            )
    except Exception as e:
        return f"HTTP 请求失败: {e}"
