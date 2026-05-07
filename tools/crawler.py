"""爬虫工具：链接发现、表单提取、站点地图、JS 端点提取。"""

import re
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx

from agent.tool_registry import registry
from tools.browser import get_page
from utils.sanitizer import truncate


@registry.tool(
    name="crawl_links",
    description="爬取当前页面的所有链接（<a> 标签），返回去重后的 URL 列表",
    params={
        "same_domain": {
            "type": "string",
            "description": "是否只返回同域链接，'true' 或 'false'（默认 'true'）",
            "required": False,
        },
    },
)
async def crawl_links(same_domain: str = "true") -> str:
    page = await get_page()
    try:
        current_url = page.url
        current_domain = urlparse(current_url).netloc

        links = await page.eval_on_selector_all(
            "a[href]",
            "elements => elements.map(e => ({href: e.href, text: e.innerText.trim().substring(0, 80)}))",
        )

        seen = set()
        results = []
        for link in links:
            href = link.get("href", "")
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            full_url = urljoin(current_url, href)

            if same_domain.lower() == "true":
                link_domain = urlparse(full_url).netloc
                if link_domain != current_domain:
                    continue

            if full_url not in seen:
                seen.add(full_url)
                text = link.get("text", "")
                results.append(f"  {full_url}  [{text}]" if text else f"  {full_url}")

        output = f"共发现 {len(results)} 个链接 (同域={same_domain}):\n" + "\n".join(results)
        return truncate(output)
    except Exception as e:
        return f"爬取链接失败: {e}"


@registry.tool(
    name="crawl_forms",
    description="提取当前页面的所有表单（<form>）及其输入字段，用于发现潜在的输入点",
    params={},
)
async def crawl_forms() -> str:
    page = await get_page()
    try:
        forms = await page.eval_on_selector_all(
            "form",
            """forms => forms.map(f => ({
                action: f.action,
                method: f.method || 'GET',
                inputs: Array.from(f.querySelectorAll('input, textarea, select')).map(i => ({
                    tag: i.tagName.toLowerCase(),
                    type: i.type || '',
                    name: i.name || '',
                    id: i.id || '',
                    placeholder: i.placeholder || '',
                }))
            }))""",
        )

        if not forms:
            return "当前页面未发现表单"

        lines = []
        for i, form in enumerate(forms, 1):
            lines.append(f"\n表单 #{i}: {form.get('method', 'GET').upper()} → {form.get('action', '(self)')}")
            for inp in form.get("inputs", []):
                name = inp.get("name") or inp.get("id") or "(unnamed)"
                inp_type = inp.get("type", inp.get("tag", ""))
                placeholder = inp.get("placeholder", "")
                desc = f"    [{inp_type}] {name}"
                if placeholder:
                    desc += f'  placeholder="{placeholder}"'
                lines.append(desc)

        return f"共发现 {len(forms)} 个表单:" + "\n".join(lines)
    except Exception as e:
        return f"提取表单失败: {e}"


@registry.tool(
    name="crawl_js_sources",
    description="提取当前页面加载的所有 JavaScript 文件 URL",
    params={},
)
async def crawl_js_sources() -> str:
    page = await get_page()
    try:
        scripts = await page.eval_on_selector_all(
            "script[src]",
            "elements => elements.map(e => e.src)",
        )
        if not scripts:
            return "当前页面无外部 JS 文件"

        lines = [f"  {src}" for src in scripts]
        return f"共 {len(scripts)} 个 JS 文件:\n" + "\n".join(lines)
    except Exception as e:
        return f"提取 JS 源失败: {e}"


# ─── 递归站点地图 ─────────────────────────────────────────────────────────────


@registry.tool(
    name="crawl_site_map",
    description="从指定 URL 开始递归爬取同域链接，生成站点地图。BFS 广度优先，可限制深度和最大页面数。",
    params={
        "url": {"type": "string", "description": "起始 URL"},
        "max_depth": {
            "type": "string",
            "description": "最大爬取深度（默认 3）",
            "required": False,
        },
        "max_pages": {
            "type": "string",
            "description": "最大爬取页面数（默认 50）",
            "required": False,
        },
    },
)
async def crawl_site_map(url: str, max_depth: str = "3", max_pages: str = "50") -> str:
    from utils.sanitizer import sanitize_url

    url = sanitize_url(url)
    depth_limit = int(max_depth)
    page_limit = int(max_pages)
    base_domain = urlparse(url).netloc

    visited: set[str] = set()
    site_map: list[str] = []
    queue: deque[tuple[str, int]] = deque([(url, 0)])

    try:
        async with httpx.AsyncClient(
            timeout=10.0, verify=False, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 Argus/0.1"},
        ) as client:
            while queue and len(visited) < page_limit:
                current_url, depth = queue.popleft()

                # 规范化 URL
                parsed = urlparse(current_url)
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                if normalized in visited:
                    continue
                visited.add(normalized)

                try:
                    resp = await client.get(current_url)
                except Exception:
                    continue

                content_type = resp.headers.get("content-type", "")
                status = resp.status_code
                site_map.append(f"  [depth={depth}] [{status}] {normalized}")

                # 只从 HTML 页面提取链接
                if "text/html" not in content_type or depth >= depth_limit:
                    continue

                # 用正则从 HTML 中提取链接
                html = resp.text
                href_pattern = re.compile(r'href=["\']([^"\'>]+)["\']', re.IGNORECASE)
                for match in href_pattern.finditer(html):
                    link = match.group(1)
                    if link.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue
                    full = urljoin(current_url, link)
                    link_domain = urlparse(full).netloc
                    if link_domain == base_domain:
                        link_normalized = f"{urlparse(full).scheme}://{link_domain}{urlparse(full).path}".rstrip("/")
                        if link_normalized not in visited:
                            queue.append((full, depth + 1))

    except Exception as e:
        return f"站点地图爬取失败: {e}"

    if not site_map:
        return "未爬取到任何页面"

    return (
        f"站点地图 ({base_domain}) — 共 {len(site_map)} 个页面 "
        f"(深度={depth_limit}, 上限={page_limit}):\n" + "\n".join(site_map)
    )


# ─── JS 端点提取 ──────────────────────────────────────────────────────────────

# 1) 完整 URL（http/https）
_FULL_URL_RE = re.compile(
    r'["\']'
    r'(https?://[a-zA-Z0-9\-\.]+(?::[0-9]+)?[a-zA-Z0-9/_\-\.\?&=%~#:@!$&*+,;]*)'
    r'["\']'
)

# 2) 高确信路径（含已知前缀）— 字符串字面量内
_API_PATH_RE = re.compile(
    r'["\'](/(?:api|v[0-9]+|graphql|rest|auth|oauth|user|admin|search|upload|download'
    r'|mooc[a-z0-9\-]*|ai[\-_][a-z0-9\-]+|think|topic|answer|review|exam|quiz|chat|message)'
    r'[a-zA-Z0-9/_\-\.]*)["\']'
)

# 3) 宽路径：以 / 开头，至少含一个 /，长度 ≥ 5，全 URL 字符（启发式过滤）
#    避免误抓注释/正则 — 必须在字符串字面量内（'...' 或 "..."）
_BROAD_PATH_RE = re.compile(
    r'["\'](\/[a-zA-Z][a-zA-Z0-9_\-]*\/[a-zA-Z0-9/_\-\.]{3,})["\']'
)

# 4) 模板字符串里的 URL —— `/path/${param}` 或 `${base}/path`
_TEMPLATE_URL_RE = re.compile(
    r"`(/[a-zA-Z][a-zA-Z0-9/_\-\.]*"
    r"(?:\$\{[^}]+\}[a-zA-Z0-9/_\-\.]*)*)`"
)

# 5) AJAX 调用：fetch(...) / axios.get/post(...) / new EventSource(...) / new SSE(...)
#    捕获第一个字符串参数
_AJAX_CALL_RE = re.compile(
    r"(?:fetch|axios\.(?:get|post|put|delete|patch|request)|"
    r"\$\.(?:ajax|get|post)|new\s+(?:EventSource|WebSocket|SSE))\s*\(\s*"
    r"[`'\"](/?[^`'\"]+)[`'\"]"
)

# 6) jQuery $.ajax({ url: "..." }) / axios({ url: "..." })
_AJAX_OPTS_URL_RE = re.compile(
    r"(?:url|baseURL|endpoint)\s*:\s*[`'\"]"
    r"(/[a-zA-Z][a-zA-Z0-9/_\-\.\?&=%~]*)[`'\"]"
)

# 7) 敏感关键词
_SENSITIVE_RE = re.compile(
    r'(?:api[_-]?key|apikey|secret|token|password|passwd|credential|auth_?token|bearer)'
    r'\s*[:=]\s*["\']([^"\'\s>]{8,})["\']',
    re.IGNORECASE,
)


# 启发式：路径必须看起来像合法 URL path
_VALID_PATH_RE = re.compile(r"^/[a-zA-Z0-9][a-zA-Z0-9/_\-\.\?&=%~#${}@!:,;]*$")
# 黑名单：纯 CSS/MIME/正则匹配会进来
_PATH_BLACKLIST = {
    "/", "/.", "/..", "//",
}


def _is_likely_endpoint(path: str) -> bool:
    """启发式过滤误报。"""
    if len(path) < 5 or path in _PATH_BLACKLIST:
        return False
    if " " in path or "\n" in path or "\t" in path:
        return False
    # 至少一个 /，但不能全是 //
    if path.count("/") < 2 and len(path) < 8:
        return False
    if not _VALID_PATH_RE.match(path):
        return False
    # 排除明显的非 API（CSS/图片资源）
    lower = path.lower()
    return not any(
        lower.endswith(ext)
        for ext in (".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                    ".woff", ".woff2", ".ttf", ".eot")
    )


@registry.tool(
    name="crawl_js_endpoints",
    description="下载并分析 JS 文件内容，从中提取 API 端点、完整 URL 和可能的敏感信息（如 API Key）",
    params={
        "js_url": {
            "type": "string",
            "description": "要分析的 JS 文件 URL。如不提供，则分析当前页面的所有外部 JS。",
            "required": False,
        },
    },
)
async def crawl_js_endpoints(js_url: str = "") -> str:
    js_urls = []

    if js_url:
        js_urls = [js_url.strip()]
    else:
        # 从当前页面获取所有 JS URL
        page = await get_page()
        js_urls = await page.eval_on_selector_all(
            "script[src]", "elements => elements.map(e => e.src)"
        )

    if not js_urls:
        return "未找到 JS 文件可供分析"

    high_confidence: set[str] = set()   # 已知前缀的 API 路径
    broad_paths: set[str] = set()       # 启发式发现的其它路径
    template_urls: set[str] = set()     # 模板字符串
    ajax_calls: set[str] = set()        # fetch/axios/EventSource 等
    all_urls: set[str] = set()          # 完整 http(s):// URL
    all_secrets: list[str] = []
    analyzed = 0

    # 接受 gzip/deflate；httpx 会自动解压。User-Agent 用真实浏览器避免被某些 CDN 拒绝
    async with httpx.AsyncClient(
        timeout=30.0, verify=False, follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Encoding": "gzip, deflate, br",
        },
    ) as client:
        for url in js_urls[:20]:  # 最多分析 20 个 JS 文件
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                # 强制读完整 body 后解码（避免 chunked 截断）
                _ = await resp.aread()
                content = resp.text
                analyzed += 1

                # 1) 完整 URL
                for m in _FULL_URL_RE.finditer(content):
                    all_urls.add(m.group(1))

                # 2) 高确信前缀路径
                for m in _API_PATH_RE.finditer(content):
                    p = m.group(1)
                    if _is_likely_endpoint(p):
                        high_confidence.add(p)

                # 3) 宽路径（启发式过滤）
                for m in _BROAD_PATH_RE.finditer(content):
                    p = m.group(1)
                    if _is_likely_endpoint(p) and p not in high_confidence:
                        broad_paths.add(p)

                # 4) 模板字符串
                for m in _TEMPLATE_URL_RE.finditer(content):
                    p = m.group(1)
                    if _is_likely_endpoint(p):
                        template_urls.add(p)

                # 5) AJAX 调用
                for m in _AJAX_CALL_RE.finditer(content):
                    p = m.group(1)
                    if p.startswith("/") and _is_likely_endpoint(p):
                        ajax_calls.add(p)
                    elif p.startswith("http"):
                        all_urls.add(p)

                # 6) AJAX 选项里的 url
                for m in _AJAX_OPTS_URL_RE.finditer(content):
                    p = m.group(1)
                    if _is_likely_endpoint(p):
                        ajax_calls.add(p)

                # 7) 敏感信息
                for m in _SENSITIVE_RE.finditer(content):
                    pos = m.start()
                    line_start = content.rfind("\n", max(0, pos - 100), pos) + 1
                    line_end = content.find("\n", pos, pos + 200)
                    if line_end == -1:
                        line_end = min(pos + 200, len(content))
                    context = content[line_start:line_end].strip()
                    source = url.split("/")[-1]
                    all_secrets.append(f"  [{source}] {context[:150]}")
            except Exception:
                continue

    lines = [f"JS 分析完成 — 共分析 {analyzed}/{len(js_urls)} 个文件\n"]

    if high_confidence:
        lines.append(f"## 高确信 API 路径 ({len(high_confidence)})")
        for p in sorted(high_confidence):
            lines.append(f"  {p}")

    if ajax_calls:
        lines.append(f"\n## AJAX/Fetch/SSE 调用 ({len(ajax_calls)})")
        for p in sorted(ajax_calls)[:50]:
            lines.append(f"  {p}")

    if template_urls:
        lines.append(f"\n## 模板字符串 URL ({len(template_urls)})")
        for p in sorted(template_urls)[:30]:
            lines.append(f"  {p}")

    if broad_paths:
        lines.append(f"\n## 其它路径（启发式，可能含误报，{len(broad_paths)}）")
        for p in sorted(broad_paths)[:50]:
            lines.append(f"  {p}")

    if all_urls:
        lines.append(f"\n## 完整 URL ({len(all_urls)})")
        for u in sorted(all_urls)[:50]:
            lines.append(f"  {u}")

    if all_secrets:
        lines.append(f"\n## ⚠ 疑似敏感信息 ({len(all_secrets)})")
        lines.extend(all_secrets[:20])

    total = len(high_confidence) + len(broad_paths) + len(template_urls) + len(ajax_calls) + len(all_urls)
    if total == 0:
        lines.append("未在 JS 文件中发现有价值的端点或敏感信息")
    else:
        lines.insert(1, f"共发现 {total} 个端点 / URL（按可信度分组）\n")

    return truncate("\n".join(lines))
