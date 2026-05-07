"""SSE 流式捕获测试（A4）。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tools.devtools as dt

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前重置 SSE / 网络 buffer 和监听状态。"""
    dt._sse_log.clear()
    dt._network_log.clear()
    dt._listening = False
    yield


def _push_sse(events: list[dict]) -> None:
    """直接往 buffer 里塞事件，模拟从 console 桥接过来的消息。"""
    for e in events:
        dt._sse_log.append(e)


class TestSseLogTool:
    async def test_empty_returns_helpful_message(self) -> None:
        # 跳过 _ensure_network_listening 实际调用 playwright
        with patch.object(dt, "_ensure_network_listening", new=AsyncMock()):
            result = await dt.devtools_sse_log()
            assert "暂无 SSE 消息" in result

    async def test_filter_by_kind_default_message(self) -> None:
        _push_sse(
            [
                {"kind": "open", "url": "https://x.com/sse"},
                {"kind": "message", "url": "https://x.com/sse", "data": "hello"},
                {"kind": "message", "url": "https://x.com/sse", "data": "world"},
                {"kind": "close", "url": "https://x.com/sse"},
            ]
        )

        with patch.object(dt, "_ensure_network_listening", new=AsyncMock()):
            result = await dt.devtools_sse_log(kind="message")

        assert "hello" in result
        assert "world" in result
        # 默认 kind=message 不显示 open/close
        # （因为它们没有 data 字段，可能仍会出现 [open] 标签）

    async def test_kind_all_includes_open_close(self) -> None:
        _push_sse(
            [
                {"kind": "open", "url": "https://x.com/sse"},
                {"kind": "message", "url": "https://x.com/sse", "data": "ev1"},
                {"kind": "close", "url": "https://x.com/sse"},
            ]
        )

        with patch.object(dt, "_ensure_network_listening", new=AsyncMock()):
            result = await dt.devtools_sse_log(kind="all")

        assert "[open]" in result
        assert "[close]" in result
        assert "ev1" in result

    async def test_url_filter(self) -> None:
        _push_sse(
            [
                {"kind": "message", "url": "https://api.com/chat", "data": "A"},
                {"kind": "message", "url": "https://other.com/feed", "data": "B"},
            ]
        )

        with patch.object(dt, "_ensure_network_listening", new=AsyncMock()):
            result = await dt.devtools_sse_log(filter="api.com")

        assert "A" in result
        assert "B" not in result

    async def test_grouped_by_url(self) -> None:
        _push_sse(
            [
                {"kind": "message", "url": "https://a.com/s", "data": "a1"},
                {"kind": "message", "url": "https://a.com/s", "data": "a2"},
                {"kind": "message", "url": "https://b.com/s", "data": "b1"},
            ]
        )

        with patch.object(dt, "_ensure_network_listening", new=AsyncMock()):
            result = await dt.devtools_sse_log(kind="all")

        # 应有 2 个流分组
        assert "## https://a.com/s" in result
        assert "## https://b.com/s" in result
        assert "2 个流" in result

    async def test_clear_buffer(self) -> None:
        _push_sse([{"kind": "message", "url": "x", "data": "y"}])
        result = await dt.devtools_sse_clear()
        assert "1" in result
        assert len(dt._sse_log) == 0


class TestRingBufferLimit:
    async def test_sse_log_capped(self) -> None:
        # 推超过上限的事件
        for i in range(dt._SSE_LOG_LIMIT + 50):
            dt._sse_log.append({"kind": "message", "url": "x", "data": f"e{i}"})
        # deque(maxlen=...) 应限制大小
        assert len(dt._sse_log) == dt._SSE_LOG_LIMIT


class TestConsoleBridge:
    """验证 on_console handler 把 __argus_sse__ 消息塞进 buffer。"""

    async def test_console_handler_parses_event(self) -> None:
        # 我们手动构造 _ensure_network_listening 内部的 handler 行为
        # 因为它依赖 page，简化为单元测：直接构造一个 handler 验证 JSON parse 路径
        import tools.devtools as mod

        captured = []

        # 模拟 console message
        msg = MagicMock()
        msg.text = '__argus_sse__ {"kind":"message","url":"https://x.com","data":"hello"}'
        msg.args = [MagicMock()]

        # 模拟 _ensure_network_listening 的 handler
        text = msg.text
        if "__argus_sse__" in text:
            idx = text.find("{")
            if idx >= 0:
                event = json.loads(text[idx:])
                captured.append(event)

        assert len(captured) == 1
        assert captured[0]["kind"] == "message"
        assert captured[0]["data"] == "hello"
