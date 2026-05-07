"""BrowserPool 单元测试（仅测纯逻辑，不启动真实 Chromium）。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.browser import BrowserPool

pytestmark = pytest.mark.asyncio


class TestHealthCheck:
    async def test_fresh_pool_is_healthy(self) -> None:
        pool = BrowserPool()
        # 初始无资源，health_check 应返回 True 表示「无需重建」（资源由 get_page 按需创建）
        assert await pool.health_check() is True

    async def test_idle_timeout_triggers_close(self) -> None:
        pool = BrowserPool(max_idle_seconds=1)
        pool._last_used = time.time() - 5  # 5 秒前用过
        mock_browser = MagicMock()
        mock_browser.is_connected = MagicMock(return_value=True)
        mock_browser.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.close = AsyncMock()
        pool._browser = mock_browser
        pool._context = mock_context

        result = await pool.health_check()
        assert result is False
        # close 被触发（资源已重置但 mock 引用还活着）
        mock_browser.close.assert_awaited()

    async def test_disconnected_browser_resets_state(self) -> None:
        pool = BrowserPool(max_idle_seconds=600)
        pool._last_used = time.time()
        pool._browser = MagicMock()
        pool._browser.is_connected = MagicMock(return_value=False)

        result = await pool.health_check()
        assert result is False
        assert pool._browser is None

    async def test_closed_page_is_cleared(self) -> None:
        pool = BrowserPool(max_idle_seconds=600)
        pool._last_used = time.time()
        pool._browser = MagicMock()
        pool._browser.is_connected = MagicMock(return_value=True)
        pool._page = MagicMock()
        pool._page.is_closed = MagicMock(return_value=True)

        await pool.health_check()
        assert pool._page is None


class TestLock:
    async def test_lock_is_asyncio_lock(self) -> None:
        pool = BrowserPool()
        assert isinstance(pool._lock, asyncio.Lock)

    async def test_close_serializes(self) -> None:
        """两次 close 不会同时执行 _teardown。"""
        pool = BrowserPool()
        teardown_calls = {"n": 0}

        original_teardown = pool._teardown

        async def counted_teardown():
            teardown_calls["n"] += 1
            await asyncio.sleep(0.05)
            await original_teardown()

        pool._teardown = counted_teardown

        await asyncio.gather(pool.close(), pool.close())
        assert teardown_calls["n"] == 2  # 串行化执行而非并发


class TestReset:
    async def test_reset_state_clears_all(self) -> None:
        pool = BrowserPool()
        pool._playwright = MagicMock()
        pool._browser = MagicMock()
        pool._context = MagicMock()
        pool._page = MagicMock()
        pool._last_used = time.time()

        await pool._reset_state()
        assert pool._playwright is None
        assert pool._browser is None
        assert pool._context is None
        assert pool._page is None
        assert pool._last_used == 0.0


class TestCompatAPI:
    async def test_get_pool_returns_singleton(self) -> None:
        from tools.browser import get_pool

        a = get_pool()
        b = get_pool()
        assert a is b

    async def test_compat_get_page_signature(self) -> None:
        """验证 get_page 函数签名向后兼容。"""
        import inspect

        from tools.browser import get_page

        sig = inspect.signature(get_page)
        assert "headed" in sig.parameters
        assert "timeout" in sig.parameters
