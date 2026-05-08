"""issue #16: RDAP 客户端 + whois_lookup fallback 测试。

不打外网 — 全部用 httpx.MockTransport。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from tools import _rdap

# ─── 工具函数 ────────────────────────────────────────────────────────────


def test_find_rdap_server_picks_https(tmp_path: Path) -> None:
    bootstrap = {
        "services": [
            [["com", "net"], ["http://example.com/rdap", "https://rdap.verisign.com/com/v1/"]],
            [["org"], ["https://rdap.publicinterestregistry.org/rdap/"]],
        ]
    }
    assert _rdap.find_rdap_server(bootstrap, "com") == "https://rdap.verisign.com/com/v1"
    assert _rdap.find_rdap_server(bootstrap, "ORG") == "https://rdap.publicinterestregistry.org/rdap"
    assert _rdap.find_rdap_server(bootstrap, "xyz") is None


def test_find_rdap_server_handles_malformed_entries() -> None:
    bootstrap = {"services": [["malformed"], None, [["com"], []]]}
    assert _rdap.find_rdap_server(bootstrap, "com") is None


# ─── 解析 ────────────────────────────────────────────────────────────────


_SAMPLE_RDAP = {
    "ldhName": "example.com",
    "status": ["active", "client transfer prohibited"],
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2026-08-13T04:00:00Z"},
        {"eventAction": "last changed", "eventDate": "2025-08-14T07:01:31Z"},
    ],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": [
                "vcard",
                [["fn", {}, "text", "RESERVED-Internet Assigned Numbers Authority"]],
            ],
        },
        {
            "roles": ["registrant"],
            "handle": "iana-handle",
            "vcardArray": [
                "vcard",
                [
                    ["fn", {}, "text", "Internet Assigned Numbers Authority"],
                    ["org", {}, "text", "IANA"],
                ],
            ],
        },
    ],
    "nameservers": [
        {"ldhName": "a.iana-servers.net"},
        {"ldhName": "b.iana-servers.net"},
    ],
}


def test_parse_rdap_extracts_key_fields() -> None:
    out = _rdap.parse_rdap_response(_SAMPLE_RDAP)
    assert out["domain"] == "example.com"
    assert out["registrar"] == "RESERVED-Internet Assigned Numbers Authority"
    assert out["registrant_org"] == "IANA"
    assert out["creation"] == "1995-08-14T04:00:00Z"
    assert out["expiration"] == "2026-08-13T04:00:00Z"
    assert out["last_changed"] == "2025-08-14T07:01:31Z"
    assert "active" in out["status"]
    assert out["nameservers"] == ["a.iana-servers.net", "b.iana-servers.net"]


def test_parse_rdap_handles_missing_fields() -> None:
    out = _rdap.parse_rdap_response({"ldhName": "x.com"})
    assert out["domain"] == "x.com"
    assert out["status"] == []
    assert "creation" not in out
    assert "registrar" not in out


def test_format_rdap_summary_contains_domain() -> None:
    out = _rdap.parse_rdap_response(_SAMPLE_RDAP)
    text = _rdap.format_rdap_summary(out)
    assert "example.com" in text
    assert "IANA" in text


def test_format_rdap_summary_empty_input() -> None:
    assert _rdap.format_rdap_summary({}) == "(无可解析字段)"


# ─── bootstrap 缓存 TTL ────────────────────────────────────────────────


def test_bootstrap_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sample = {"services": [[["com"], ["https://x/"]]]}
    _rdap._save_cached_bootstrap(sample)
    cached = _rdap._load_cached_bootstrap()
    assert cached is not None
    assert cached["services"] == sample["services"]


def test_bootstrap_cache_expired_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cache_path = _rdap._bootstrap_cache_path()
    payload = {"services": [], "_argus_cached_at": time.time() - (8 * 24 * 3600)}
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _rdap._load_cached_bootstrap() is None


# ─── 集成：lookup_rdap 端到端 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookup_rdap_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟 IANA bootstrap + verisign domain 查询。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        if "data.iana.org" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "services": [
                        [["com"], ["https://rdap.verisign.example/com/v1"]],
                    ]
                },
            )
        if "rdap.verisign.example" in str(req.url):
            return httpx.Response(200, json=_SAMPLE_RDAP)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await _rdap.lookup_rdap("example.com", client=client)

    assert out is not None
    assert out["domain"] == "example.com"
    assert out["registrant_org"] == "IANA"


@pytest.mark.asyncio
async def test_lookup_rdap_returns_none_when_bootstrap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await _rdap.lookup_rdap("example.com", client=client) is None


# ─── whois_lookup 集成：fallback 行为 ───────────────────────────────────


@pytest.mark.asyncio
async def test_whois_lookup_uses_rdap_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    async def fake_lookup(domain: str, *, client=None):  # type: ignore[no-untyped-def]
        return {"domain": domain, "registrar": "FakeReg"}

    monkeypatch.setattr("tools._rdap.lookup_rdap", fake_lookup)

    from tools.recon import whois_lookup

    out = await whois_lookup("example.com")
    assert "RDAP" in out
    assert "FakeReg" in out


@pytest.mark.asyncio
async def test_whois_lookup_falls_back_when_rdap_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    async def fake_lookup(domain: str, *, client=None):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr("tools._rdap.lookup_rdap", fake_lookup)

    # 旧 API 也炸 → 友好错误
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "message": "Missing name or suffix parameter"})

    real = httpx.AsyncClient

    def factory(*a, **kw):  # type: ignore[no-untyped-def]
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr("tools.recon.httpx.AsyncClient", factory)

    from tools.recon import whois_lookup

    out = await whois_lookup("example.com")
    assert "WHOIS 查询失败" in out
    assert "旧 API 返回 error" in out
