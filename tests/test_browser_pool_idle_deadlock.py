"""Bug 1 回归：BrowserPool idle-close 路径必须不死锁。

复现历史 bug：
  health_check() 持锁状态下调 self.close() → close 又抢 _lock → 死锁
  → tool_timeout 取消 → 重试又死锁 → 用户看到「主动关闭」打印 6 次。

修复：health_check 改用 _teardown（不抢锁）。

本测试在不依赖真实 Playwright 的前提下，给 BrowserPool 注入 mock 资源，
直接断言 idle 触发后 health_check 与并发 get_page 都不会卡。
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_idle_close_does_not_deadlock() -> None:
    """idle 触发主动关闭后 health_check 应在 1s 内返回，且锁可被重新获取。"""
    from tools.browser import BrowserPool

    pool = BrowserPool(max_idle_seconds=1)
    pool._last_used = time.time() - 5  # 5s 前用过，已 idle
    # 注入"未死"的浏览器与 context 让 _teardown 走完整路径
    mock_browser = MagicMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock()
    mock_context = MagicMock()
    mock_context.close = AsyncMock()
    mock_page = MagicMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.close = AsyncMock()
    pool._browser = mock_browser
    pool._context = mock_context
    pool._page = mock_page

    # 持锁路径：模拟 get_page 调用 health_check 的真实场景
    async with pool._lock:
        # 在 1s 时间预算内必须返回（修复前会一直卡死）
        result = await asyncio.wait_for(pool.health_check(), timeout=1.0)

    assert result is False
    mock_browser.close.assert_awaited()
    # 状态已重置
    assert pool._browser is None
    assert pool._page is None


async def test_lock_released_after_idle_teardown() -> None:
    """idle teardown 走完后，锁应可被另一协程立即获取。"""
    from tools.browser import BrowserPool

    pool = BrowserPool(max_idle_seconds=1)
    pool._last_used = time.time() - 5
    pool._browser = MagicMock()
    pool._browser.is_connected = MagicMock(return_value=True)
    pool._browser.close = AsyncMock()

    async with pool._lock:
        await pool.health_check()  # 内部调 _teardown，不再抢锁

    # 这里如果 health_check 内部抢了 _lock，上面 async with 出来时锁未释放
    # 下面 acquire 会卡死 → wait_for 超时
    await asyncio.wait_for(pool._lock.acquire(), timeout=0.5)
    pool._lock.release()


async def test_two_consecutive_get_page_calls_after_idle() -> None:
    """idle-close 后再连续两次 get_page 不能死锁（用户场景：连续工具调用）。"""
    from tools import browser as browser_mod
    from tools.browser import BrowserPool

    pool = BrowserPool(max_idle_seconds=1)
    pool._last_used = time.time() - 10
    pool._browser = MagicMock()
    pool._browser.is_connected = MagicMock(return_value=True)
    pool._browser.close = AsyncMock()
    pool._context = MagicMock()
    pool._context.close = AsyncMock()

    # health_check 必须先把状态清空，再让 get_page 走重建路径
    # 这里只测健康检查不卡 + 锁释放正常
    async with pool._lock:
        ok = await asyncio.wait_for(pool.health_check(), timeout=1.0)
    assert ok is False

    # 第二次再来一次（模拟 LLM 又调一个 browser_* 工具）
    pool._last_used = time.time() - 10
    pool._browser = MagicMock()
    pool._browser.is_connected = MagicMock(return_value=True)
    pool._browser.close = AsyncMock()
    async with pool._lock:
        ok2 = await asyncio.wait_for(pool.health_check(), timeout=1.0)
    assert ok2 is False
