"""issue #20: L2 实测暴露的 3 个 bug 的回归测试。

Bug A: subdomain_enum 对 wildcard DNS 域名返回 2000/2000 假阳性
Bug B: whois_lookup 对子域（scanme.nmap.org）查 RDAP 返回 None
Bug C: port_scan 对 IANA 保留段无提示
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────
# Bug A: wildcard DNS 检测
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_wildcard_ips_positive() -> None:
    """3 个随机子域都解析到同一组 IP → 判定 wildcard。"""
    from tools import recon

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        return ["198.18.0.4"]

    with patch.object(recon, "_resolve_ips", side_effect=fake_resolve):
        ips = await recon._detect_wildcard_ips("example.com")
    assert ips == {"198.18.0.4"}


@pytest.mark.asyncio
async def test_detect_wildcard_ips_negative() -> None:
    """3 个随机子域全返空 → 无 wildcard。"""
    from tools import recon

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        return []

    with patch.object(recon, "_resolve_ips", side_effect=fake_resolve):
        ips = await recon._detect_wildcard_ips("nmap.org")
    assert ips == set()


@pytest.mark.asyncio
async def test_subdomain_enum_filters_wildcard() -> None:
    """wildcard 触发时，命中 wildcard IP 的条目被过滤，报告带警告。"""
    from tools import recon

    wildcard = {"198.18.0.4"}

    async def fake_detect(_domain: str) -> set[str]:
        return wildcard

    # 模拟字典里每个词都解析到 wildcard IP
    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        return ["198.18.0.4"]

    small_list = ["www", "api", "mail"]

    with (
        patch.object(recon, "_detect_wildcard_ips", side_effect=fake_detect),
        patch.object(recon, "_resolve_ips", side_effect=fake_resolve),
        patch.object(recon, "SUBDOMAINS", small_list),
    ):
        out = await recon.subdomain_enum("example.com", "3")

    assert "wildcard DNS" in out
    assert "已过滤 3 条" in out
    # 所有条目都被过滤 → 无存活子域
    assert "未发现" in out


@pytest.mark.asyncio
async def test_subdomain_enum_keeps_real_hits_under_wildcard() -> None:
    """wildcard 存在但部分子域解析到不同 IP → 这些应当保留。"""
    from tools import recon

    wildcard = {"198.18.0.4"}

    async def fake_detect(_domain: str) -> set[str]:
        return wildcard

    async def fake_resolve(sub: str, _domain: str) -> list[str]:
        if sub == "www":
            return ["93.184.216.34"]  # 真实 IP，非 wildcard
        return ["198.18.0.4"]

    small_list = ["www", "api", "mail"]

    with (
        patch.object(recon, "_detect_wildcard_ips", side_effect=fake_detect),
        patch.object(recon, "_resolve_ips", side_effect=fake_resolve),
        patch.object(recon, "SUBDOMAINS", small_list),
    ):
        out = await recon.subdomain_enum("example.com", "3")

    assert "wildcard DNS" in out
    assert "已过滤 2 条" in out
    assert "www.example.com" in out
    assert "93.184.216.34" in out
    assert "发现 1/3" in out


# ─────────────────────────────────────────────────────────────────────────
# Bug B: RDAP 子域回退父域
# ─────────────────────────────────────────────────────────────────────────


def test_registrable_candidates_two_labels() -> None:
    from tools._rdap import _registrable_candidates

    assert _registrable_candidates("example.com") == ["example.com"]


def test_registrable_candidates_subdomain() -> None:
    from tools._rdap import _registrable_candidates

    # scanme.nmap.org → 先试 scanme.nmap.org，失败回 nmap.org
    out = _registrable_candidates("scanme.nmap.org")
    assert out[0] == "scanme.nmap.org"
    assert "nmap.org" in out
    # 顺序：从最长到最短
    assert out.index("scanme.nmap.org") < out.index("nmap.org")


def test_registrable_candidates_deep_subdomain() -> None:
    from tools._rdap import _registrable_candidates

    out = _registrable_candidates("a.b.c.example.com")
    assert out == [
        "a.b.c.example.com",
        "b.c.example.com",
        "c.example.com",
        "example.com",
    ]


def test_registrable_candidates_invalid() -> None:
    from tools._rdap import _registrable_candidates

    assert _registrable_candidates("nodot") == []
    assert _registrable_candidates("") == []


@pytest.mark.asyncio
async def test_lookup_rdap_falls_back_to_parent() -> None:
    """子域查 RDAP 失败时回退到父域。"""
    from tools import _rdap

    # scanme.nmap.org 返 None，nmap.org 返数据
    calls: list[str] = []

    async def fake_try(_client, _bootstrap, dom: str):
        calls.append(dom)
        if dom == "nmap.org":
            return {"domain": "nmap.org", "registrar": "Dynadot"}
        return None

    fake_bootstrap = {"services": []}
    mock_client = AsyncMock()

    with (
        patch.object(_rdap, "_try_lookup_one", side_effect=fake_try),
        patch.object(_rdap, "fetch_bootstrap", AsyncMock(return_value=fake_bootstrap)),
    ):
        result = await _rdap.lookup_rdap("scanme.nmap.org", client=mock_client)

    assert result is not None
    assert result["registrar"] == "Dynadot"
    assert result["_queried_as"] == "scanme.nmap.org"
    assert result["_resolved_via"] == "nmap.org"
    assert calls == ["scanme.nmap.org", "nmap.org"]


@pytest.mark.asyncio
async def test_lookup_rdap_direct_hit_no_fallback_note() -> None:
    """直接查注册域命中，不带 _queried_as 字段。"""
    from tools import _rdap

    async def fake_try(_client, _bootstrap, _dom: str):
        return {"domain": "example.com", "registrar": "IANA"}

    with (
        patch.object(_rdap, "_try_lookup_one", side_effect=fake_try),
        patch.object(_rdap, "fetch_bootstrap", AsyncMock(return_value={"services": []})),
    ):
        result = await _rdap.lookup_rdap("example.com", client=AsyncMock())

    assert result is not None
    assert "_queried_as" not in result


def test_format_rdap_summary_includes_fallback_note() -> None:
    from tools._rdap import format_rdap_summary

    out = format_rdap_summary({
        "_queried_as": "scanme.nmap.org",
        "_resolved_via": "nmap.org",
        "domain": "nmap.org",
        "registrar": "Dynadot",
    })
    assert "scanme.nmap.org" in out
    assert "nmap.org" in out
    assert "回退" in out


# ─────────────────────────────────────────────────────────────────────────
# Bug C: port_scan 保留段提示
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reserved_range_note_iana_testnet() -> None:
    from tools.recon import _reserved_range_note

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        return ["198.18.8.29"]

    with patch("tools.recon._resolve_ips", side_effect=fake_resolve):
        note = await _reserved_range_note("scanme.nmap.org")

    assert note
    assert "198.18.0.0/15" in note
    assert "保留" in note or "测试" in note


@pytest.mark.asyncio
async def test_reserved_range_note_rfc1918() -> None:
    from tools.recon import _reserved_range_note

    note = await _reserved_range_note("192.168.1.1")
    assert "192.168.0.0/16" in note
    assert "RFC1918" in note


@pytest.mark.asyncio
async def test_reserved_range_note_public_ip_empty() -> None:
    from tools.recon import _reserved_range_note

    note = await _reserved_range_note("8.8.8.8")
    assert note == ""


@pytest.mark.asyncio
async def test_reserved_range_note_unresolvable() -> None:
    from tools import recon

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        return []

    with patch.object(recon, "_resolve_ips", side_effect=fake_resolve):
        note = await recon._reserved_range_note("does-not-exist.invalid")
    assert note == ""


def test_ip_in_cidr_basic() -> None:
    from tools.recon import _ip_in_cidr

    assert _ip_in_cidr("198.18.8.29", "198.18.0.0/15")
    assert _ip_in_cidr("10.0.0.1", "10.0.0.0/8")
    assert not _ip_in_cidr("8.8.8.8", "10.0.0.0/8")
    assert not _ip_in_cidr("not-an-ip", "10.0.0.0/8")
