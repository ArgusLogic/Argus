"""issue #2 — _retry_on_broken_pipe 装饰器单测。

不依赖真实 Playwright；通过给装饰器手动包装 mock 函数验证。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tools import browser as browser_mod
from tools.browser import _is_broken_pipe, _result_indicates_broken_pipe, _retry_on_broken_pipe

pytestmark = pytest.mark.asyncio


# ─── 识别函数 ───────────────────────────────────────────────────────────────


class TestRecognition:
    def test_is_broken_pipe_target_closed(self) -> None:
        try:
            raise RuntimeError("Target closed unexpectedly")
        except RuntimeError as e:
            assert _is_broken_pipe(e)

    def test_is_broken_pipe_epipe(self) -> None:
        try:
            raise OSError("write failed: EPIPE")
        except OSError as e:
            assert _is_broken_pipe(e)

    def test_is_broken_pipe_targetclosederror_classname(self) -> None:
        # 类名匹配（即使消息不含模式）
        TargetClosedError = type("TargetClosedError", (Exception,), {})
        try:
            raise TargetClosedError("oops")
        except Exception as e:
            assert _is_broken_pipe(e)

    def test_other_exception_not_matched(self) -> None:
        try:
            raise TimeoutError("waited too long")
        except TimeoutError as e:
            assert not _is_broken_pipe(e)

    def test_result_string_match(self) -> None:
        assert _result_indicates_broken_pipe("访问失败: Target closed")
        assert _result_indicates_broken_pipe("操作失败: Browser closed")
        assert not _result_indicates_broken_pipe("访问失败: 404")
        assert not _result_indicates_broken_pipe(None)
        assert not _result_indicates_broken_pipe(123)


# ─── 装饰器行为 ─────────────────────────────────────────────────────────────


class TestRetryDecorator:
    async def test_retries_once_on_broken_pipe_exception(self) -> None:
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Target closed: page gone")
            return "ok"

        wrapped = _retry_on_broken_pipe(victim)
        with patch.object(browser_mod._pool, "close", new=AsyncMock()) as mock_close:
            assert await wrapped() == "ok"
        assert calls["n"] == 2
        mock_close.assert_awaited_once()

    async def test_retries_once_on_broken_pipe_string_return(self) -> None:
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return "访问失败: Target closed unexpectedly"
            return "状态码: 200"

        wrapped = _retry_on_broken_pipe(victim)
        with patch.object(browser_mod._pool, "close", new=AsyncMock()) as mock_close:
            assert await wrapped() == "状态码: 200"
        assert calls["n"] == 2
        mock_close.assert_awaited_once()

    async def test_does_not_retry_on_unrelated_exception(self) -> None:
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            raise TimeoutError("something else")

        wrapped = _retry_on_broken_pipe(victim)
        with (
            patch.object(browser_mod._pool, "close", new=AsyncMock()) as mock_close,
            pytest.raises(TimeoutError),
        ):
            await wrapped()
        assert calls["n"] == 1
        mock_close.assert_not_awaited()

    async def test_does_not_retry_on_normal_string_return(self) -> None:
        """正常返回值（即使含 '失败' 字样但不含 broken-pipe 模式）不重试。"""
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            return "访问失败: 404 Not Found"

        wrapped = _retry_on_broken_pipe(victim)
        with patch.object(browser_mod._pool, "close", new=AsyncMock()) as mock_close:
            assert await wrapped() == "访问失败: 404 Not Found"
        assert calls["n"] == 1
        mock_close.assert_not_awaited()

    async def test_second_attempt_still_broken_pipe_propagates(self) -> None:
        """重试一次后仍是 broken-pipe，应让结果原样返回（不无限重试）。"""
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            return "访问失败: Browser closed"

        wrapped = _retry_on_broken_pipe(victim)
        with patch.object(browser_mod._pool, "close", new=AsyncMock()):
            assert await wrapped() == "访问失败: Browser closed"
        assert calls["n"] == 2

    async def test_second_attempt_still_raises_propagates(self) -> None:
        """重试一次后仍抛 broken-pipe 异常，应原样抛出。"""
        calls = {"n": 0}

        async def victim() -> str:
            calls["n"] += 1
            raise RuntimeError("Target closed")

        wrapped = _retry_on_broken_pipe(victim)
        with (
            patch.object(browser_mod._pool, "close", new=AsyncMock()),
            pytest.raises(RuntimeError, match="Target closed"),
        ):
            await wrapped()
        assert calls["n"] == 2
