"""DevTools 深度交互工具：网络监听、请求拦截、Cookie 管理 + SSE 流式捕获。

设计：
- _network_log: 网络请求/响应（循环 buffer，最多 500 条）
- _sse_log: SSE/EventSource 数据消息（循环 buffer，最多 200 条）
- 默认在浏览器首次启动时即注入抓包（B6），无需用户先调 start_capture
- SSE 通过 init_script 在页面加载时注入 JS hook，用 console.log("__sse__", ...) 桥接到 Python 侧
"""

from __future__ import annotations

import contextlib
import json
from collections import deque

from agent.tool_registry import registry
from tools.browser import get_page
from utils.sanitizer import truncate

# 循环 buffer：用 deque(maxlen=...) 防止内存无限增长
_NETWORK_LOG_LIMIT = 500
_SSE_LOG_LIMIT = 200

_network_log: deque = deque(maxlen=_NETWORK_LOG_LIMIT)
_sse_log: deque = deque(maxlen=_SSE_LOG_LIMIT)
_listening: bool = False


# 页面加载时注入的 JS：劫持 EventSource 和 fetch 的 text/event-stream 响应
_SSE_INJECT_JS = """
(() => {
    if (window.__argus_sse_hooked) return;
    window.__argus_sse_hooked = true;

    const _log = (event) => {
        try {
            console.log("__argus_sse__", JSON.stringify(event));
        } catch (e) {}
    };

    // Hook EventSource
    const OrigES = window.EventSource;
    if (OrigES) {
        window.EventSource = new Proxy(OrigES, {
            construct(target, args) {
                const url = args[0];
                const es = new target(...args);
                _log({ kind: "open", url });
                const origAdd = es.addEventListener.bind(es);
                es.addEventListener = (type, listener, opts) => {
                    if (type === "message" || type === "error") {
                        const wrapped = (ev) => {
                            _log({ kind: type, url, data: (ev && ev.data) || "", ts: Date.now() });
                            return listener(ev);
                        };
                        return origAdd(type, wrapped, opts);
                    }
                    return origAdd(type, listener, opts);
                };
                // 默认 onmessage
                Object.defineProperty(es, "onmessage", {
                    set(fn) {
                        origAdd("message", (ev) => {
                            _log({ kind: "message", url, data: (ev && ev.data) || "", ts: Date.now() });
                            fn(ev);
                        });
                    },
                });
                return es;
            },
        });
    }

    // Hook fetch streaming（text/event-stream 响应）
    const origFetch = window.fetch;
    window.fetch = async function(...args) {
        const resp = await origFetch.apply(this, args);
        const ctype = resp.headers.get("content-type") || "";
        if (ctype.includes("text/event-stream")) {
            const url = resp.url;
            _log({ kind: "open", url });
            const reader = resp.clone().body.getReader();
            const decoder = new TextDecoder();
            (async () => {
                let buf = "";
                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) { _log({ kind: "close", url }); break; }
                        buf += decoder.decode(value, { stream: true });
                        const parts = buf.split(/\\n\\n/);
                        buf = parts.pop();
                        for (const p of parts) {
                            const dataLines = p.split("\\n").filter(l => l.startsWith("data:"));
                            if (dataLines.length) {
                                const data = dataLines.map(l => l.slice(5).trim()).join("\\n");
                                _log({ kind: "message", url, data, ts: Date.now() });
                            }
                        }
                    }
                } catch (e) { _log({ kind: "error", url, error: String(e) }); }
            })();
        }
        return resp;
    };
})();
"""


async def _ensure_network_listening() -> None:
    """确保网络监听 + SSE 注入已开启。可被多次调用，幂等。"""
    global _listening
    if _listening:
        return

    page = await get_page()
    context = page.context

    # 1) 网络抓包
    async def on_request(request):
        _network_log.append(
            {
                "type": "request",
                "method": request.method,
                "url": request.url,
                "headers": dict(request.headers),
                "resource_type": request.resource_type,
            }
        )

    async def on_response(response):
        _network_log.append(
            {
                "type": "response",
                "status": response.status,
                "url": response.url,
                "headers": dict(response.headers),
            }
        )

    page.on("request", on_request)
    page.on("response", on_response)

    # 2) SSE 桥接：监听 console，过滤 __argus_sse__ 前缀
    def on_console(msg):
        try:
            args = msg.args
            if not args:
                return
            text = msg.text
            if "__argus_sse__" not in text:
                return
            # 提取 JSON 部分
            idx = text.find("{")
            if idx < 0:
                return
            event = json.loads(text[idx:])
            _sse_log.append(event)
        except Exception:
            pass

    page.on("console", on_console)

    # 3) 在所有未来页面加载时注入 SSE hook（包括子 iframe）
    with contextlib.suppress(Exception):
        await context.add_init_script(_SSE_INJECT_JS)

    # 4) 当前页面立即注入一次（init_script 仅作用于未来加载）
    with contextlib.suppress(Exception):
        await page.evaluate(_SSE_INJECT_JS)

    _listening = True


@registry.tool(
    name="devtools_start_capture",
    description=(
        "开启网络请求抓包 + SSE 流式数据捕获。"
        "通常无需手动调用：浏览器首次启动时已自动开启（B6）。"
        "调用此工具会清空 buffer 重新开始。"
    ),
    params={},
)
async def devtools_start_capture() -> str:
    _network_log.clear()
    _sse_log.clear()
    await _ensure_network_listening()
    return "网络 + SSE 抓包已开启，buffer 已清空。"


@registry.tool(
    name="devtools_network_log",
    description="获取已捕获的网络请求/响应记录。可通过 filter 关键词过滤。",
    params={
        "filter": {
            "type": "string",
            "description": "URL 过滤关键词（可选），如 'api' 只显示包含 api 的请求",
            "required": False,
        },
        "limit": {
            "type": "string",
            "description": "返回的最大记录数（默认 30）",
            "required": False,
        },
    },
)
async def devtools_network_log(filter: str = "", limit: str = "30") -> str:
    # B6: 默认抓包 — 首次访问自动启用
    await _ensure_network_listening()

    if not _network_log:
        return "暂无网络记录。请先访问页面后再查询（抓包已默认开启）。"

    max_count = int(limit)
    logs = list(_network_log)

    if filter:
        logs = [entry for entry in logs if filter.lower() in entry.get("url", "").lower()]

    # 精简输出
    results = []
    for entry in logs[-max_count:]:
        if entry["type"] == "request":
            results.append(f"→ {entry['method']} {entry['url']} [{entry['resource_type']}]")
        else:
            results.append(f"← {entry['status']} {entry['url']}")

    output = f"共 {len(logs)} 条记录（显示最近 {min(max_count, len(logs))} 条）:\n"
    output += "\n".join(results[-max_count:])
    return truncate(output)


@registry.tool(
    name="devtools_sse_log",
    description=(
        "获取已捕获的 SSE / EventSource / fetch streaming 流式消息（含完整 data 内容）。"
        "适用于 AI 对话、实时翻译、推送通知等流式接口的逆向分析。"
        "抓包默认开启，无需手动启用。"
    ),
    params={
        "filter": {
            "type": "string",
            "description": "URL 过滤关键词（可选）",
            "required": False,
        },
        "limit": {
            "type": "string",
            "description": "返回的最大消息数（默认 50）",
            "required": False,
        },
        "kind": {
            "type": "string",
            "description": "事件类型过滤：'message'（默认）/ 'open' / 'close' / 'error' / 'all'",
            "required": False,
        },
    },
)
async def devtools_sse_log(filter: str = "", limit: str = "50", kind: str = "message") -> str:
    await _ensure_network_listening()

    if not _sse_log:
        return "暂无 SSE 消息。需先访问含流式接口（EventSource / fetch streaming）的页面。"

    max_count = int(limit)
    events = list(_sse_log)

    if kind != "all":
        events = [e for e in events if e.get("kind") == kind]
    if filter:
        events = [e for e in events if filter.lower() in e.get("url", "").lower()]

    if not events:
        return "无匹配的 SSE 消息（尝试 kind='all'）"

    # 按 URL 分组渲染
    from collections import defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in events[-max_count:]:
        grouped[e.get("url", "?")].append(e)

    lines = [f"共 {len(events)} 条 SSE 事件，按 URL 分组（{len(grouped)} 个流）:\n"]
    for url, evs in grouped.items():
        lines.append(f"\n## {url}  ({len(evs)} 条)")
        for e in evs[:20]:  # 每个 URL 最多 20 条
            k = e.get("kind", "?")
            data = (e.get("data") or "").replace("\n", " ")[:200]
            lines.append(f"  [{k}] {data}" if data else f"  [{k}]")

    return truncate("\n".join(lines))


@registry.tool(
    name="devtools_sse_clear",
    description="清空 SSE 消息 buffer（不影响监听）。",
    params={},
)
async def devtools_sse_clear() -> str:
    n = len(_sse_log)
    _sse_log.clear()
    return f"已清空 {n} 条 SSE 消息。"


@registry.tool(
    name="devtools_cookies",
    description="获取当前页面所在域名的所有 Cookie",
    params={},
)
async def devtools_cookies() -> str:
    page = await get_page()
    try:
        context = page.context
        cookies = await context.cookies()
        if not cookies:
            return "当前域名无 Cookie"

        lines = []
        for c in cookies:
            flags = []
            if c.get("httpOnly"):
                flags.append("HttpOnly")
            if c.get("secure"):
                flags.append("Secure")
            same_site = c.get("sameSite", "")
            if same_site:
                flags.append(f"SameSite={same_site}")

            lines.append(
                f"  {c['name']} = {c['value'][:80]}"
                f"  (domain: {c.get('domain', '')}, path: {c.get('path', '')}"
                f", flags: {', '.join(flags) if flags else 'none'})"
            )

        return f"共 {len(cookies)} 个 Cookie:\n" + "\n".join(lines)
    except Exception as e:
        return f"获取 Cookie 失败: {e}"


@registry.tool(
    name="devtools_headers",
    description="获取当前页面加载时的 HTTP 响应头，可用于安全头分析",
    params={},
)
async def devtools_headers() -> str:
    # 从 network_log 中找到最近的主页面响应
    page_url = (await get_page()).url

    for entry in reversed(_network_log):
        if entry["type"] == "response" and entry["url"] == page_url:
            headers = entry.get("headers", {})
            lines = [f"  {k}: {v}" for k, v in headers.items()]
            return f"响应头 ({entry['url']}):\n" + "\n".join(lines)

    return "未找到当前页面的响应头记录。请先开启抓包 (devtools_start_capture) 再访问页面。"
