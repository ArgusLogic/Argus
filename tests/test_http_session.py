"""http_request 浏览器会话复用测试（A2）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.browser import BrowserPool
from tools.http_client import http_request

pytestmark = pytest.mark.asyncio


class TestGetBrowserSession:
    async def test_returns_empty_when_no_browser(self) -> None:
        from tools.browser import get_browser_session, get_pool

        pool = get_pool()
        # 确保是干净的（无浏览器启动）
        pool._context = None
        pool._page = None

        result = await get_browser_session()
        assert result == {}

    async def test_returns_cookies_when_browser_active(self) -> None:
        from tools.browser import get_browser_session, get_pool

        pool = get_pool()
        # mock context.cookies + page.evaluate + page.url
        mock_context = MagicMock()
        mock_context.cookies = AsyncMock(
            return_value=[
                {"name": "session_id", "value": "abc123"},
                {"name": "csrf", "value": "tok456"},
            ]
        )
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value="Mozilla/5.0 Test")
        mock_page.is_closed = MagicMock(return_value=False)
        mock_page.url = "https://example.com/dashboard"
        pool._context = mock_context
        pool._page = mock_page

        try:
            result = await get_browser_session()
            assert result["cookies"] == "session_id=abc123; csrf=tok456"
            assert result["user_agent"] == "Mozilla/5.0 Test"
            assert result["referer"] == "https://example.com/dashboard"
        finally:
            pool._context = None
            pool._page = None


def _make_resp(status: int = 200, body: bytes = b"ok", headers: dict | None = None) -> MagicMock:
    """构造一个模拟 httpx Response，aread() 返回完整 body。"""
    resp = MagicMock()
    resp.status_code = status
    resp.url = "https://x.com"
    resp.headers = headers or {}
    resp.encoding = "utf-8"
    resp.aread = AsyncMock(return_value=body)
    resp.text = body.decode("utf-8", errors="replace")
    return resp


class TestHttpRequestSessionInjection:
    async def test_no_session_by_default(self) -> None:
        """默认 use_browser_session=false，不注入。"""
        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp())

            await http_request(url="https://x.com", use_browser_session="false")

            sent_headers = mock_client.request.await_args.kwargs["headers"]
            assert "Cookie" not in sent_headers

    async def test_session_injected_when_enabled(self) -> None:
        with (
            patch(
                "tools.browser.get_browser_session",
                new=AsyncMock(
                    return_value={
                        "cookies": "k1=v1; k2=v2",
                        "user_agent": "BrowserUA/1.0",
                        "referer": "https://app.example.com/",
                    }
                ),
            ),
            patch("tools.http_client.httpx.AsyncClient") as MockClient,
        ):
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp())

            result = await http_request(url="https://x.com", use_browser_session="true")

            sent_headers = mock_client.request.await_args.kwargs["headers"]
            assert sent_headers["Cookie"] == "k1=v1; k2=v2"
            assert sent_headers["User-Agent"] == "BrowserUA/1.0"
            assert sent_headers["Referer"] == "https://app.example.com/"
            assert "已注入浏览器 session" in result
            assert "2 cookies" in result

    async def test_user_headers_take_precedence(self) -> None:
        """用户显式给的 Cookie 优先于浏览器自动注入的。"""
        with (
            patch(
                "tools.browser.get_browser_session",
                new=AsyncMock(return_value={"cookies": "auto=session", "user_agent": "auto", "referer": ""}),
            ),
            patch("tools.http_client.httpx.AsyncClient") as MockClient,
        ):
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp())

            await http_request(
                url="https://x.com",
                headers='{"Cookie": "user=manual"}',
                use_browser_session="true",
            )

            sent = mock_client.request.await_args.kwargs["headers"]
            assert sent["Cookie"] == "user=manual"  # 用户值保留

    async def test_warning_when_browser_inactive(self) -> None:
        with (
            patch("tools.browser.get_browser_session", new=AsyncMock(return_value={})),
            patch("tools.http_client.httpx.AsyncClient") as MockClient,
        ):
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp())

            result = await http_request(url="https://x.com", use_browser_session="true")
            assert "浏览器未启动" in result


class TestHttpResponseIntegrity:
    """A3 大文件完整性：aread + Accept-Encoding + save_to。"""

    async def test_drains_full_body(self) -> None:
        """body 大小应基于 aread() 真实字节数，不被 lazy text 截断。"""
        big_body = b"x" * 100_000  # 100KB
        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp(body=big_body))

            result = await http_request(url="https://x.com")

            assert "100000 字节" in result

    async def test_accept_encoding_default(self) -> None:
        """默认请求头应含 Accept-Encoding: gzip,..."""
        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp())

            await http_request(url="https://x.com")

            sent = mock_client.request.await_args.kwargs["headers"]
            assert "gzip" in sent.get("Accept-Encoding", "")

    async def test_save_to_writes_file(self, tmp_path, monkeypatch) -> None:
        """save_to=foo.js 应把完整 body 写入下载目录。"""
        # 重定向 OUTPUT_DIR 到 tmp
        monkeypatch.setattr("tools.http_client.OUTPUT_DIR", str(tmp_path))

        big_js = b"// js content\n" * 5000  # ~75KB
        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp(body=big_js))

            result = await http_request(url="https://x.com/big.js", save_to="big.js")

            assert "已保存到" in result
            saved = tmp_path / "downloads" / "big.js"
            assert saved.exists()
            assert saved.read_bytes() == big_js

    async def test_save_to_sanitizes_filename(self, tmp_path, monkeypatch) -> None:
        """save_to 含路径穿越的文件名应被剥离。"""
        monkeypatch.setattr("tools.http_client.OUTPUT_DIR", str(tmp_path))

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(return_value=_make_resp(body=b"data"))

            await http_request(url="https://x.com", save_to="../../etc/passwd")

            # 路径穿越被剥离 → 实际文件应在 downloads/passwd
            saved = tmp_path / "downloads" / "passwd"
            assert saved.exists()


# ─── Bug 3 (Coco 报告): per-host 连续超时熔断 ──────────────────────────────


class TestCircuitBreaker:
    """per-host 连续 N 次超时 → 熔断本 session 内不再访问该 host。"""

    @pytest.fixture(autouse=True)
    def _reset_circuit(self):
        """每个测试前清空熔断状态。"""
        from tools.http_client import _reset_http_circuit

        _reset_http_circuit()
        yield
        _reset_http_circuit()

    async def test_timeout_increments_streak_below_threshold(self) -> None:
        import httpx

        from tools.http_client import _HTTP_HOST_CIRCUIT_OPEN, _HTTP_HOST_TIMEOUT_STREAK

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            # 第 1 次超时
            r1 = await http_request(url="https://slow.example/")
            assert "超时" in r1
            assert "[CIRCUIT_OPEN]" not in r1
            assert _HTTP_HOST_TIMEOUT_STREAK.get("slow.example") == 1
            assert "slow.example" not in _HTTP_HOST_CIRCUIT_OPEN

            # 第 2 次
            r2 = await http_request(url="https://slow.example/")
            assert "[CIRCUIT_OPEN]" not in r2
            assert _HTTP_HOST_TIMEOUT_STREAK.get("slow.example") == 2

    async def test_three_timeouts_open_circuit(self) -> None:
        import httpx

        from tools.http_client import _HTTP_HOST_CIRCUIT_OPEN

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            # 第 1+2 次 — 累计但不熔断
            await http_request(url="https://dead.example/a")
            await http_request(url="https://dead.example/b")
            # 第 3 次 — 触发熔断
            r3 = await http_request(url="https://dead.example/c")
            assert "[CIRCUIT_OPEN]" in r3
            assert "dead.example" in _HTTP_HOST_CIRCUIT_OPEN

            # 后续任何请求该 host 都被立刻拒绝（不再发实际请求）
            mock_client.request.reset_mock()
            r4 = await http_request(url="https://dead.example/d")
            assert "[CIRCUIT_OPEN]" in r4
            assert "本 session 内不再访问" in r4
            mock_client.request.assert_not_called(), "熔断后不应再调实际 httpx"

    async def test_success_resets_streak(self) -> None:
        """超时 1 次后成功一次，streak 应清零。"""
        import httpx

        from tools.http_client import _HTTP_HOST_TIMEOUT_STREAK

        call_count = {"n": 0}

        async def request_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.TimeoutException("first timeout")
            return _make_resp(body=b"ok")

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.request = AsyncMock(side_effect=request_side_effect)

            await http_request(url="https://flaky.example/")
            assert _HTTP_HOST_TIMEOUT_STREAK.get("flaky.example") == 1

            await http_request(url="https://flaky.example/")
            # 成功后清零
            assert "flaky.example" not in _HTTP_HOST_TIMEOUT_STREAK

    async def test_circuit_is_per_host_not_global(self) -> None:
        """一个 host 熔断不影响其他 host。"""
        import httpx

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value

            # dead.example 总超时 → 熔断
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("t"))
            for _ in range(3):
                await http_request(url="https://dead.example/")

            # other.example 是好的 → 仍能通
            mock_client.request = AsyncMock(return_value=_make_resp(body=b"ok"))
            r = await http_request(url="https://other.example/")
            assert "状态码" in r
            assert "[CIRCUIT_OPEN]" not in r

    async def test_timeout_constant_is_30s(self) -> None:
        """Bug 3 推荐 30s（之前 60s 太长）。"""
        from tools.http_client import _HTTP_TIMEOUT_SECONDS

        assert _HTTP_TIMEOUT_SECONDS == 30.0
