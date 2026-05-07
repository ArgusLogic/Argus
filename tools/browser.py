"""浏览器控制工具：基于 Playwright 的页面导航、内容获取、截图、JS 执行。

架构：BrowserPool 单例封装 Playwright 资源（playwright/browser/context/page），提供：
- get_page(): 健康检查 + 自愈（崩溃后自动重建）
- close(): 释放全部资源
- asyncio.Lock 保护：为子代理并行使用做准备（多协程不会同时初始化）
- max_idle_seconds: 长时间空闲后主动释放资源，避免 Chromium 内存泄漏

向后兼容：保留 `get_page()` 和 `close_browser()` 模块级函数。
"""

import asyncio
import contextlib
import os
import time

from playwright.async_api import (
    Browser,
    BrowserContext,
    Frame,
    Page,
    Playwright,
    async_playwright,
)

from agent.tool_registry import registry
from utils.logger import log_warning
from utils.sanitizer import sanitize_url, truncate

DEFAULT_TIMEOUT_MS = 30000


def _is_headless_from_config() -> bool:
    """从 config.toml 读取浏览器 headed 设置。找不到配置时默认 headless。"""
    try:
        from utils.paths import CONFIG_PATH
        if CONFIG_PATH.exists():
            import toml
            cfg = toml.load(str(CONFIG_PATH))
            return not cfg.get("browser", {}).get("headed", False)
    except Exception:
        pass
    return True  # 安全默认：服务器环境默认 headless
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class BrowserPool:
    """单例式 Playwright 浏览器资源池。"""

    def __init__(self, max_idle_seconds: int = 600) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._active_frame: Frame | None = None  # iframe 上下文（A7）
        self._lock = asyncio.Lock()
        self._last_used: float = 0.0
        self.max_idle_seconds = max_idle_seconds

    async def health_check(self) -> bool:
        """检查浏览器/页面是否健康。不健康时自动清理状态以便下次重建。"""
        # 长时间空闲：主动释放
        if self._last_used and (time.time() - self._last_used) > self.max_idle_seconds:
            log_warning(f"浏览器空闲超过 {self.max_idle_seconds}s，主动关闭")
            await self.close()
            return False

        # 浏览器进程死了
        if self._browser is not None and not self._browser.is_connected():
            log_warning("浏览器连接丢失，标记为待重建")
            await self._reset_state()
            return False

        # Page 关闭了
        if self._page is not None and self._page.is_closed():
            self._page = None

        return True

    async def get_page(self, headed: bool | None = None, timeout: int = DEFAULT_TIMEOUT_MS) -> Page:
        """获取健康的浏览器页面，必要时重建。"""
        if headed is None:
            headed = not _is_headless_from_config()
        async with self._lock:
            await self.health_check()

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(
                    headless=not headed,
                    args=["--disable-blink-features=AutomationControlled"],
                )

            if self._context is None:
                self._context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=DEFAULT_USER_AGENT,
                )
                self._context.set_default_timeout(timeout)

            if self._page is None or self._page.is_closed():
                self._page = await self._context.new_page()

            self._last_used = time.time()
            return self._page

    async def close(self) -> None:
        """释放所有资源。"""
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        """实际关闭逻辑（不加锁，调用方负责）。"""
        if self._page is not None and not self._page.is_closed():
            with contextlib.suppress(Exception):
                await self._page.close()
        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
        await self._reset_state()

    async def _reset_state(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._active_frame = None
        self._last_used = 0.0

    def get_active_context(self):
        """返回当前操作上下文：active_frame 优先，否则当前 page。

        所有 browser_* 工具应通过此方法访问浏览器，以支持 iframe 上下文切换（A7）。
        """
        if self._active_frame is not None:
            try:
                if self._active_frame.is_detached():
                    self._active_frame = None
            except Exception:
                self._active_frame = None
        return self._active_frame or self._page


# 模块级单例
_pool = BrowserPool()


# ─── 向后兼容的薄包装 ────────────────────────────────────────────────────


async def get_page(headed: bool | None = None, timeout: int = DEFAULT_TIMEOUT_MS) -> Page:
    """（兼容旧 API）获取或创建浏览器页面，单例模式 + 健康检查。
    默认 headless 由 config.toml 的 browser.headed 决定。
    """
    return await _pool.get_page(headed=headed, timeout=timeout)


async def close_browser() -> None:
    """（兼容旧 API）关闭浏览器及所有资源。"""
    await _pool.close()


def get_pool() -> BrowserPool:
    """暴露单例 pool 给需要更细粒度控制的调用方（如子代理）。"""
    return _pool


async def get_browser_session(url: str | None = None) -> dict:
    """从当前浏览器上下文导出 session 信息（cookies + UA + referer）供 http_request 复用。

    Args:
        url: 可选的目标 URL，用于过滤 cookies（仅返回作用域匹配的）。None 时返回所有。

    Returns:
        {"cookies": "k1=v1; k2=v2", "user_agent": "...", "referer": "..."}
        浏览器未启动时返回 {} 。
    """
    if _pool._context is None or _pool._page is None:
        return {}

    try:
        all_cookies = await _pool._context.cookies(url) if url else await _pool._context.cookies()
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies)
        ua = await _pool._page.evaluate("() => navigator.userAgent")
        page_url = _pool._page.url if not _pool._page.is_closed() else ""
        return {
            "cookies": cookie_header,
            "user_agent": ua,
            "referer": page_url,
        }
    except Exception:
        return {}


# ─── 注册工具 ────────────────────────────────────────────────────────────────


@registry.tool(
    name="browser_navigate",
    description="打开浏览器访问指定 URL，返回页面标题、最终 URL 和 HTTP 状态码",
    params={
        "url": {"type": "string", "description": "要访问的目标 URL"},
    },
)
async def browser_navigate(url: str) -> str:
    url = sanitize_url(url)
    page = await get_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded")
        status = response.status if response else "unknown"
        title = await page.title()
        final_url = page.url
        return f"状态码: {status} | 标题: {title} | URL: {final_url}"
    except Exception as e:
        return f"访问失败: {e}"


@registry.tool(
    name="browser_get_html",
    description="获取当前页面的 HTML 内容。可通过 selector 指定元素，否则返回整个页面 HTML（截断到合理长度）",
    params={
        "selector": {
            "type": "string",
            "description": "CSS 选择器，为空则返回整个页面 HTML",
            "required": False,
        },
    },
)
async def browser_get_html(selector: str = "") -> str:
    await get_page()
    ctx = _pool.get_active_context()
    if ctx is None:
        return "浏览器未启动"
    try:
        if selector:
            element = await ctx.query_selector(selector)
            if not element:
                return f"未找到元素: {selector}"
            html = await element.inner_html()
        else:
            html = await ctx.content()
        return truncate(html)
    except Exception as e:
        return f"获取 HTML 失败: {e}"


@registry.tool(
    name="browser_get_text",
    description="获取当前页面的纯文本内容（去除 HTML 标签），更适合阅读和分析",
    params={
        "selector": {
            "type": "string",
            "description": "CSS 选择器，为空则返回整个页面文本",
            "required": False,
        },
    },
)
async def browser_get_text(selector: str = "") -> str:
    await get_page()
    ctx = _pool.get_active_context()
    if ctx is None:
        return "浏览器未启动"
    try:
        if selector:
            element = await ctx.query_selector(selector)
            if not element:
                return f"未找到元素: {selector}"
            text = await element.inner_text()
        else:
            text = await ctx.inner_text("body")
        return truncate(text)
    except Exception as e:
        return f"获取文本失败: {e}"


@registry.tool(
    name="browser_screenshot",
    description="截取当前页面的截图并保存到本地文件，返回文件路径",
    params={
        "filename": {
            "type": "string",
            "description": "截图文件名（不含路径），如 'homepage.png'",
            "required": False,
        },
    },
)
async def browser_screenshot(filename: str = "screenshot.png") -> str:
    page = await get_page()
    from utils.paths import SCREENSHOTS_DIR

    screenshot_dir = SCREENSHOTS_DIR
    os.makedirs(screenshot_dir, exist_ok=True)
    filepath = os.path.join(screenshot_dir, filename)
    try:
        await page.screenshot(path=filepath, full_page=True)
        return f"截图已保存: {filepath}"
    except Exception as e:
        return f"截图失败: {e}"


@registry.tool(
    name="browser_console_exec",
    description="在当前页面的浏览器 Console 中执行 JavaScript 代码，返回执行结果",
    params={
        "script": {"type": "string", "description": "要执行的 JavaScript 代码"},
    },
)
async def browser_console_exec(script: str) -> str:
    await get_page()
    ctx = _pool.get_active_context()
    if ctx is None:
        return "浏览器未启动"
    try:
        result = await ctx.evaluate(script)
        return truncate(str(result))
    except Exception as e:
        return f"JS 执行失败: {e}"


@registry.tool(
    name="browser_click",
    description="点击页面上指定的元素",
    params={
        "selector": {"type": "string", "description": "要点击的元素的 CSS 选择器"},
    },
)
async def browser_click(selector: str) -> str:
    page = await get_page()
    ctx = _pool.get_active_context() or page
    try:
        await ctx.click(selector)
        # 顶层页面才需要等待 load_state（iframe 不一定有完整生命周期）
        if ctx is page:
            await page.wait_for_load_state("domcontentloaded")
        title = await page.title()
        return f"已点击 '{selector}'，当前页面: {title} ({page.url})"
    except Exception as e:
        return f"点击失败: {e}"


@registry.tool(
    name="browser_fill",
    description="在输入框中填入文本内容",
    params={
        "selector": {"type": "string", "description": "输入框的 CSS 选择器"},
        "value": {"type": "string", "description": "要填入的文本"},
    },
)
async def browser_fill(selector: str, value: str) -> str:
    await get_page()
    ctx = _pool.get_active_context()
    if ctx is None:
        return "浏览器未启动"
    try:
        await ctx.fill(selector, value)
        return f"已在 '{selector}' 中填入: {value}"
    except Exception as e:
        return f"填入失败: {e}"


# ─── A5 browser_wait_for ─────────────────────────────────────────────────


_BUILTIN_WAITS = {"page_loaded", "network_idle", "ajax_complete", "sse_closed", "domcontentloaded", "load"}


@registry.tool(
    name="browser_wait_for",
    description=(
        "等待指定条件满足后返回，避免反复轮询。"
        "条件支持: CSS 选择器（如 '#result'）/ JS 表达式（如 'app.loading === false'）/ "
        "内置预设（'page_loaded' / 'network_idle' / 'sse_closed'）。"
    ),
    params={
        "condition": {
            "type": "string",
            "description": "等待条件（CSS 选择器 / JS 表达式 / 内置预设名）",
        },
        "timeout": {
            "type": "string",
            "description": "超时毫秒数，默认 30000",
            "required": False,
        },
        "poll_interval": {
            "type": "string",
            "description": "JS 表达式轮询间隔毫秒，默认 500",
            "required": False,
        },
    },
)
async def browser_wait_for(condition: str, timeout: str = "30000", poll_interval: str = "500") -> str:
    import time as _time

    page = await get_page()
    try:
        timeout_ms = int(timeout)
        poll_ms = int(poll_interval)
    except ValueError:
        return f"timeout / poll_interval 必须是整数: {timeout} / {poll_interval}"

    cond = condition.strip()
    t0 = _time.monotonic()

    try:
        # 1) 内置预设
        if cond in _BUILTIN_WAITS:
            mapping = {
                "page_loaded": "load",
                "load": "load",
                "domcontentloaded": "domcontentloaded",
                "network_idle": "networkidle",
            }
            if cond in mapping:
                await page.wait_for_load_state(mapping[cond], timeout=timeout_ms)  # type: ignore[arg-type]
            elif cond == "ajax_complete":
                # 等所有 fetch/XHR 落地（启发式：document.readyState 完成 + jQuery active=0）
                await page.wait_for_function(
                    "() => document.readyState === 'complete' && (window.jQuery ? jQuery.active === 0 : true)",
                    timeout=timeout_ms,
                )
            elif cond == "sse_closed":
                await page.wait_for_function(
                    "() => !document.querySelectorAll('script').length || true",  # 占位：实际由用户用 JS 表达式更精确
                    timeout=timeout_ms,
                )
            elapsed = int((_time.monotonic() - t0) * 1000)
            return f"等待完成 [{cond}]，耗时 {elapsed}ms"

        # 2) 看起来像 CSS 选择器（含 #/./[ 或单纯 tag）
        looks_css = cond.startswith(("#", ".", "[", ":")) or (
            cond[:1].isalpha() and any(c in cond for c in (".", "#", "[", ">", " ", ":"))
        )
        # 但 JS 表达式可能也含 . 和 #；启发式：含 === / != / && / || / function/ () => 一定是 JS
        looks_js = any(
            s in cond for s in ("===", "!==", "==", "!=", "&&", "||", "=>", "()", "return ", "function")
        )

        if looks_js or not looks_css:
            await page.wait_for_function(
                f"() => Boolean({cond})",
                timeout=timeout_ms,
                polling=poll_ms,
            )
            mode = "js"
        else:
            await page.wait_for_selector(cond, timeout=timeout_ms, state="visible")
            mode = "css"

        elapsed = int((_time.monotonic() - t0) * 1000)
        return f"等待完成 [{mode}: {cond}]，耗时 {elapsed}ms"
    except Exception as e:
        elapsed = int((_time.monotonic() - t0) * 1000)
        return f"等待超时或失败 ({elapsed}ms): {e}"


# ─── A6 browser_tabs ─────────────────────────────────────────────────────


@registry.tool(
    name="browser_tabs",
    description=(
        "管理浏览器标签页：列出、切换、关闭。"
        "解决 window.open 新窗口跟踪问题——切换后所有 browser_* 工具操作目标会跟着变。"
    ),
    params={
        "action": {
            "type": "string",
            "description": "list（列出）/ switch（切换）/ close（关闭指定）/ close_others（关闭其它）",
        },
        "tab_index": {
            "type": "string",
            "description": "标签页索引（从 0 开始），switch/close 时必填",
            "required": False,
        },
    },
)
async def browser_tabs(action: str, tab_index: str = "") -> str:
    pool = get_pool()
    if pool._context is None:
        return "浏览器尚未启动。请先调用 browser_navigate"

    pages = pool._context.pages
    if not pages:
        return "无活动标签页"

    action = action.lower().strip()

    if action == "list":
        lines = [f"共 {len(pages)} 个标签页:"]
        for i, p in enumerate(pages):
            active = " [当前]" if p is pool._page else ""
            try:
                title = await p.title()
            except Exception:
                title = "?"
            try:
                url = p.url
            except Exception:
                url = "?"
            lines.append(f"  [{i}]{active} {title}  -  {url}")
        return "\n".join(lines)

    # 其它 action 都需要 tab_index
    if not tab_index:
        return "switch / close / close_others 需要提供 tab_index"
    try:
        idx = int(tab_index)
    except ValueError:
        return f"tab_index 必须是整数: {tab_index}"
    if idx < 0 or idx >= len(pages):
        return f"tab_index 越界 ({idx} / {len(pages)})"

    target = pages[idx]

    if action == "switch":
        pool._page = target
        with contextlib.suppress(Exception):
            await target.bring_to_front()
        try:
            title = await target.title()
        except Exception:
            title = "?"
        return f"已切换到标签页 [{idx}]: {title}  ({target.url})"

    if action == "close":
        try:
            await target.close()
        except Exception as e:
            return f"关闭失败: {e}"
        # 如果关掉的是当前页，重置为剩下的第一个
        if pool._page is target:
            remaining = [p for p in pool._context.pages if not p.is_closed()]
            pool._page = remaining[0] if remaining else None
        return f"已关闭标签页 [{idx}]"

    if action == "close_others":
        closed = 0
        for p in list(pages):
            if p is not target and not p.is_closed():
                try:
                    await p.close()
                    closed += 1
                except Exception:
                    pass
        pool._page = target
        return f"已关闭 {closed} 个标签页，保留 [{idx}]"

    return f"未知 action: {action}（可用: list / switch / close / close_others）"


# ─── A7 browser_frame ────────────────────────────────────────────────────


@registry.tool(
    name="browser_frame",
    description=(
        "切换操作上下文到指定 iframe，或返回顶层。"
        "切换后 browser_get_text / click / fill / console_exec 等工具会作用于 iframe 内部。"
        "适用于现代 Web 应用的 iframe 嵌套架构（超星、微前端等）。"
    ),
    params={
        "selector": {
            "type": "string",
            "description": "iframe 的 CSS 选择器，如 '#frame_content'。传 'top' 或留空返回顶层",
            "required": False,
        },
    },
)
async def browser_frame(selector: str = "") -> str:
    pool = get_pool()

    s = (selector or "").strip()
    # 返回顶层不需要启动浏览器
    if not s or s.lower() == "top":
        pool._active_frame = None
        return "已返回顶层页面"

    page = await get_page()
    try:
        element = await page.wait_for_selector(s, timeout=5000)
        if not element:
            return f"未找到 iframe: {s}"
        frame = await element.content_frame()
        if frame is None:
            return f"元素 {s} 不是 iframe"
        pool._active_frame = frame
        return f"已切换到 iframe: {s}  (URL: {frame.url})"
    except Exception as e:
        return f"切换 iframe 失败: {e}"


# ─── B1 browser_upload ───────────────────────────────────────────────────


@registry.tool(
    name="browser_upload",
    description="向页面的文件 input 上传本地文件",
    params={
        "selector": {
            "type": "string",
            "description": "文件 input 元素的 CSS 选择器",
        },
        "file_path": {
            "type": "string",
            "description": "本地文件的绝对路径",
        },
    },
)
async def browser_upload(selector: str, file_path: str) -> str:
    page = await get_page()
    if not os.path.isfile(file_path):
        return f"文件不存在: {file_path}"
    try:
        await page.set_input_files(selector, file_path)
        size = os.path.getsize(file_path)
        return f"已上传到 '{selector}': {os.path.basename(file_path)} ({size} 字节)"
    except Exception as e:
        return f"上传失败: {e}"


# ─── B2 browser_keyboard ─────────────────────────────────────────────────


@registry.tool(
    name="browser_keyboard",
    description=(
        "模拟键盘输入。type=press（按单键如 'Enter'）/ type=type（逐字输入文本，触发 input 事件）/ "
        "type=combo（组合键如 'Control+Enter'）。"
    ),
    params={
        "type": {
            "type": "string",
            "description": "press / type / combo",
        },
        "key": {
            "type": "string",
            "description": "press: 键名 'Enter'/'Tab'/'Escape'；type: 要输入的文本；combo: 'Control+Enter'",
        },
        "selector": {
            "type": "string",
            "description": "可选：先聚焦此元素再输入",
            "required": False,
        },
    },
)
async def browser_keyboard(type: str, key: str, selector: str = "") -> str:
    page = await get_page()
    action = type.lower().strip()

    if selector:
        try:
            await page.click(selector)
        except Exception as e:
            return f"聚焦 {selector} 失败: {e}"

    try:
        if action == "press":
            await page.keyboard.press(key)
            return f"已按下: {key}"
        if action == "type":
            await page.keyboard.type(key)
            return f"已输入文本（{len(key)} 字符）"
        if action == "combo":
            # Control+Shift+Enter 这种组合
            parts = [p.strip() for p in key.split("+") if p.strip()]
            if not parts:
                return "组合键格式错误，应为 'Control+Enter'"
            for k in parts[:-1]:
                await page.keyboard.down(k)
            await page.keyboard.press(parts[-1])
            for k in reversed(parts[:-1]):
                await page.keyboard.up(k)
            return f"已按下组合键: {key}"
        return f"未知 type: {type}（可用: press / type / combo）"
    except Exception as e:
        return f"键盘操作失败: {e}"


# ─── B3 browser_download ─────────────────────────────────────────────────


@registry.tool(
    name="browser_download",
    description=(
        "等待并保存浏览器触发的下载。"
        "用法：先调此工具设置监听 + 超时，然后立即触发下载（点击 / JS）。"
        "成功后返回保存路径。"
    ),
    params={
        "save_path": {
            "type": "string",
            "description": "保存目录或完整文件路径",
        },
        "trigger_selector": {
            "type": "string",
            "description": "触发下载的元素 CSS 选择器；提供则自动 click 触发",
            "required": False,
        },
        "timeout": {
            "type": "string",
            "description": "等待下载完成的超时毫秒数，默认 30000",
            "required": False,
        },
    },
)
async def browser_download(save_path: str, trigger_selector: str = "", timeout: str = "30000") -> str:
    page = await get_page()
    try:
        timeout_ms = int(timeout)
    except ValueError:
        return f"timeout 必须是整数: {timeout}"

    # Playwright 的 expect_download 上下文管理器：
    try:
        async with page.expect_download(timeout=timeout_ms) as download_info:
            if trigger_selector:
                await page.click(trigger_selector)
            else:
                # 用户自己保证下载会被触发；保留时间窗口
                pass
        download = await download_info.value
    except Exception as e:
        return f"等待下载失败: {e}"

    # 保存
    try:
        # save_path 可能是目录或完整路径
        if os.path.isdir(save_path):
            target = os.path.join(save_path, download.suggested_filename or "download.bin")
        else:
            target = save_path
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        await download.save_as(target)
        size = os.path.getsize(target)
        return f"下载完成: {target} ({size} 字节)"
    except Exception as e:
        return f"保存下载失败: {e}"
