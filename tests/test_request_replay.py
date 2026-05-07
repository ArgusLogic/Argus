"""B4 请求重放测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import tools.devtools as dt
from tools.request_replay import request_replay, request_replay_list

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_log():
    dt._network_log.clear()
    yield
    dt._network_log.clear()


def _push_request(method: str, url: str, headers: dict | None = None) -> None:
    dt._network_log.append({
        "type": "request",
        "method": method,
        "url": url,
        "headers": headers or {},
        "resource_type": "fetch",
    })


def _push_response(status: int, url: str) -> None:
    dt._network_log.append({"type": "response", "status": status, "url": url, "headers": {}})


class TestList:
    async def test_empty(self) -> None:
        result = await request_replay_list()
        assert "无匹配" in result

    async def test_lists_only_requests(self) -> None:
        _push_request("GET", "https://api.com/a")
        _push_response(200, "https://api.com/a")
        _push_request("POST", "https://api.com/b")
        result = await request_replay_list()
        assert "GET" in result
        assert "POST" in result
        assert "/a" in result and "/b" in result

    async def test_filter(self) -> None:
        _push_request("GET", "https://api.com/users")
        _push_request("GET", "https://api.com/products")
        result = await request_replay_list(filter="users")
        assert "/users" in result
        assert "/products" not in result


class TestReplay:
    async def test_invalid_index(self) -> None:
        result = await request_replay(index="abc")
        assert "必须是整数" in result

    async def test_index_out_of_range(self) -> None:
        result = await request_replay(index="99")
        assert "越界" in result

    async def test_replays_with_browser_session(self) -> None:
        _push_request("GET", "https://x.com/api", headers={"X-Original": "v1"})

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.url = "https://x.com/api"
            mock_resp.headers = {}
            mock_resp.encoding = "utf-8"
            mock_resp.aread = AsyncMock(return_value=b"ok")
            mock_resp.text = "ok"
            mock_client.request = AsyncMock(return_value=mock_resp)

            result = await request_replay(index="0", use_browser_session="false")

            assert "200" in result
            sent = mock_client.request.await_args.kwargs
            assert sent["url"] == "https://x.com/api"
            assert sent["method"] == "GET"
            # 原始 X-Original 头部应保留
            assert sent["headers"].get("X-Original") == "v1"

    async def test_modify_headers_merged(self) -> None:
        _push_request("GET", "https://x.com/api", headers={"A": "1"})

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.url = "https://x.com/api"
            mock_resp.headers = {}
            mock_resp.encoding = "utf-8"
            mock_resp.aread = AsyncMock(return_value=b"")
            mock_resp.text = ""
            mock_client.request = AsyncMock(return_value=mock_resp)

            await request_replay(
                index="0",
                modify_headers='{"A": "2", "B": "3"}',
                use_browser_session="false",
            )

            sent_headers = mock_client.request.await_args.kwargs["headers"]
            assert sent_headers["A"] == "2"  # override
            assert sent_headers["B"] == "3"  # added

    async def test_strips_hop_by_hop_headers(self) -> None:
        _push_request("GET", "https://x.com", headers={
            "Connection": "keep-alive",
            "Host": "evil.com",
            "Content-Length": "100",
            "X-Real": "keep",
        })

        with patch("tools.http_client.httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.url = "https://x.com"
            mock_resp.headers = {}
            mock_resp.encoding = "utf-8"
            mock_resp.aread = AsyncMock(return_value=b"")
            mock_resp.text = ""
            mock_client.request = AsyncMock(return_value=mock_resp)

            await request_replay(index="0", use_browser_session="false")

            sent = mock_client.request.await_args.kwargs["headers"]
            keys_lower = {k.lower() for k in sent}
            assert "connection" not in keys_lower
            assert "host" not in keys_lower
            assert "content-length" not in keys_lower
            assert sent.get("X-Real") == "keep"

    async def test_response_index_rejected(self) -> None:
        _push_response(200, "https://x.com")
        result = await request_replay(index="0")
        assert "不是请求" in result
