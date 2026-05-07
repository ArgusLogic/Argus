"""A5/A6/A7/B1/B2/B3 浏览器自动化原语测试（mock Playwright）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.browser import (
    BrowserPool,
    browser_download,
    browser_frame,
    browser_keyboard,
    browser_tabs,
    browser_upload,
    browser_wait_for,
    get_pool,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_pool():
    """每个测试前后重置全局 pool 状态。"""
    pool = get_pool()
    pool._page = None
    pool._context = None
    pool._active_frame = None
    yield
    pool._page = None
    pool._context = None
    pool._active_frame = None


def _mock_page() -> MagicMock:
    p = MagicMock()
    p.is_closed = MagicMock(return_value=False)
    p.url = "https://x.com"
    p.title = AsyncMock(return_value="Title")
    p.bring_to_front = AsyncMock()
    p.close = AsyncMock()
    p.click = AsyncMock()
    p.wait_for_selector = AsyncMock()
    p.wait_for_function = AsyncMock()
    p.wait_for_load_state = AsyncMock()
    p.set_input_files = AsyncMock()
    p.keyboard = MagicMock()
    p.keyboard.press = AsyncMock()
    p.keyboard.type = AsyncMock()
    p.keyboard.down = AsyncMock()
    p.keyboard.up = AsyncMock()
    return p


# ─── A5 browser_wait_for ─────────────────────────────────────────────────


class TestWaitFor:
    async def test_builtin_page_loaded(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_wait_for("page_loaded")
        page.wait_for_load_state.assert_awaited_with("load", timeout=30000)
        assert "等待完成" in result and "page_loaded" in result

    async def test_builtin_network_idle(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            await browser_wait_for("network_idle", timeout="5000")
        page.wait_for_load_state.assert_awaited_with("networkidle", timeout=5000)

    async def test_css_selector(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            await browser_wait_for("#submit-btn")
        # 应走 wait_for_selector 路径
        page.wait_for_selector.assert_awaited()
        args = page.wait_for_selector.await_args
        assert args.args[0] == "#submit-btn"

    async def test_js_expression(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            await browser_wait_for("app.loading === false")
        page.wait_for_function.assert_awaited()
        # 验证条件被包成 () => Boolean(...)
        call_arg = page.wait_for_function.await_args.args[0]
        assert "Boolean(app.loading === false)" in call_arg

    async def test_timeout_message_on_failure(self) -> None:
        page = _mock_page()
        page.wait_for_selector = AsyncMock(side_effect=TimeoutError("timeout"))
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_wait_for("#missing", timeout="100")
        assert "超时" in result or "失败" in result

    async def test_invalid_timeout(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_wait_for("x", timeout="abc")
        assert "必须是整数" in result


# ─── A6 browser_tabs ─────────────────────────────────────────────────────


class TestTabs:
    def _setup_two_pages(self) -> tuple[MagicMock, MagicMock]:
        pool = get_pool()
        p1, p2 = _mock_page(), _mock_page()
        p1.url = "https://a.com"
        p2.url = "https://b.com"
        p1.title = AsyncMock(return_value="A")
        p2.title = AsyncMock(return_value="B")
        ctx = MagicMock()
        ctx.pages = [p1, p2]
        pool._context = ctx
        pool._page = p1
        return p1, p2

    async def test_no_browser(self) -> None:
        result = await browser_tabs("list")
        assert "尚未启动" in result

    async def test_list(self) -> None:
        _p1, _p2 = self._setup_two_pages()
        result = await browser_tabs("list")
        assert "[0]" in result and "[当前]" in result
        assert "[1]" in result
        assert "https://a.com" in result
        assert "https://b.com" in result

    async def test_switch(self) -> None:
        _p1, p2 = self._setup_two_pages()
        result = await browser_tabs("switch", tab_index="1")
        assert get_pool()._page is p2
        p2.bring_to_front.assert_awaited()
        assert "已切换" in result

    async def test_switch_index_out_of_range(self) -> None:
        self._setup_two_pages()
        result = await browser_tabs("switch", tab_index="5")
        assert "越界" in result

    async def test_close(self) -> None:
        p1, p2 = self._setup_two_pages()
        get_pool()._context.pages = [p1, p2]
        await browser_tabs("close", tab_index="0")
        p1.close.assert_awaited()

    async def test_unknown_action(self) -> None:
        self._setup_two_pages()
        result = await browser_tabs("nonsense", tab_index="0")
        assert "未知 action" in result


# ─── A7 browser_frame ────────────────────────────────────────────────────


class TestFrame:
    async def test_top_returns_to_main(self) -> None:
        pool = get_pool()
        pool._page = _mock_page()
        pool._active_frame = MagicMock()  # 假装正在 iframe 内
        result = await browser_frame("top")
        assert pool._active_frame is None
        assert "顶层" in result

    async def test_empty_selector_returns_to_top(self) -> None:
        pool = get_pool()
        pool._page = _mock_page()
        pool._active_frame = MagicMock()
        result = await browser_frame("")
        assert pool._active_frame is None
        assert "顶层" in result

    async def test_switch_into_iframe(self) -> None:
        pool = get_pool()
        page = _mock_page()
        # iframe 元素 + content_frame
        iframe_element = MagicMock()
        mock_frame = MagicMock()
        mock_frame.url = "https://inner.com"
        mock_frame.is_detached = MagicMock(return_value=False)
        iframe_element.content_frame = AsyncMock(return_value=mock_frame)
        page.wait_for_selector = AsyncMock(return_value=iframe_element)
        pool._page = page
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_frame("#myframe")
        assert pool._active_frame is mock_frame
        assert "已切换" in result

    async def test_iframe_not_found(self) -> None:
        pool = get_pool()
        page = _mock_page()
        page.wait_for_selector = AsyncMock(return_value=None)
        pool._page = page
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_frame("#missing")
        assert "未找到" in result or "失败" in result

    async def test_get_active_context_prefers_frame(self) -> None:
        pool = get_pool()
        pool._page = _mock_page()
        mock_frame = MagicMock()
        mock_frame.is_detached = MagicMock(return_value=False)
        pool._active_frame = mock_frame
        assert pool.get_active_context() is mock_frame

    async def test_get_active_context_falls_back_to_page(self) -> None:
        pool = get_pool()
        page = _mock_page()
        pool._page = page
        pool._active_frame = None
        assert pool.get_active_context() is page

    async def test_detached_frame_auto_resets(self) -> None:
        pool = get_pool()
        page = _mock_page()
        pool._page = page
        bad_frame = MagicMock()
        bad_frame.is_detached = MagicMock(return_value=True)
        pool._active_frame = bad_frame
        ctx = pool.get_active_context()
        assert pool._active_frame is None
        assert ctx is page


# ─── B1 browser_upload ───────────────────────────────────────────────────


class TestUpload:
    async def test_file_not_exists(self, tmp_path: Path) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_upload("input[type=file]", str(tmp_path / "ghost.txt"))
        assert "不存在" in result

    async def test_uploads_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"abc123")
        page = _mock_page()
        # tmp_path 在 pytest 创建时一般不在 safe_path 白名单中，需放行
        with (
            patch("tools.browser.get_page", new=AsyncMock(return_value=page)),
            patch("utils.safe_path.is_path_allowed", return_value=True),
        ):
            result = await browser_upload("#file", str(f))
        page.set_input_files.assert_awaited_with("#file", str(f))
        assert "已上传" in result and "6 字节" in result

    async def test_upload_blocked_outside_allowlist(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"abc123")
        page = _mock_page()
        with (
            patch("tools.browser.get_page", new=AsyncMock(return_value=page)),
            patch("utils.safe_path.is_path_allowed", return_value=False),
        ):
            result = await browser_upload("#file", str(f))
        page.set_input_files.assert_not_awaited()
        assert "拒绝" in result and "越界" in result


# ─── B2 browser_keyboard ─────────────────────────────────────────────────


class TestKeyboard:
    async def test_press(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_keyboard("press", "Enter")
        page.keyboard.press.assert_awaited_with("Enter")
        assert "已按下: Enter" in result

    async def test_type_text(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_keyboard("type", "hello world")
        page.keyboard.type.assert_awaited_with("hello world")
        assert "11 字符" in result

    async def test_combo(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_keyboard("combo", "Control+Enter")
        # Control 应 down + 末键 press + Control up
        page.keyboard.down.assert_any_await("Control")
        page.keyboard.press.assert_any_await("Enter")
        page.keyboard.up.assert_any_await("Control")
        assert "组合键" in result

    async def test_focus_via_selector(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            await browser_keyboard("press", "Tab", selector="#input")
        page.click.assert_awaited_with("#input")
        page.keyboard.press.assert_awaited_with("Tab")

    async def test_unknown_type(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_keyboard("invalid", "x")
        assert "未知 type" in result


# ─── B3 browser_download ─────────────────────────────────────────────────


class TestDownload:
    async def test_invalid_timeout(self) -> None:
        page = _mock_page()
        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_download("/tmp", timeout="abc")
        assert "必须是整数" in result

    async def test_download_save(self, tmp_path: Path) -> None:
        page = _mock_page()
        # 模拟 expect_download 上下文
        download = MagicMock()
        download.suggested_filename = "result.bin"
        download.save_as = AsyncMock(side_effect=lambda p: Path(p).write_bytes(b"data"))

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(value=AsyncMock(return_value=download)()))
        # download_info.value 应是 awaitable returning download
        info = MagicMock()
        info.value = AsyncMock(return_value=download)()
        ctx.__aenter__ = AsyncMock(return_value=info)
        ctx.__aexit__ = AsyncMock(return_value=False)
        page.expect_download = MagicMock(return_value=ctx)

        with patch("tools.browser.get_page", new=AsyncMock(return_value=page)):
            result = await browser_download(str(tmp_path), trigger_selector="#btn")

        assert "下载完成" in result
        page.click.assert_awaited_with("#btn")
        saved = tmp_path / "result.bin"
        assert saved.exists()
