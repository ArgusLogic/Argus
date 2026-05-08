"""Day2-2: ASCII 拓扑图渲染回归测试。"""

from __future__ import annotations

from tools._report_topology import (
    _extract_dns_records,
    _extract_open_ports,
    _summarize_subdomains,
    build_topology,
)


def test_extract_dns_records_simple_format() -> None:
    text = """DNS 查询结果 (example.com):
  A: 198.18.0.4
  AAAA: 无记录
  MX: 0 alt1.aspmx.l.google.com
  NS: elliott.ns.cloudflare.com.
  NS: hera.ns.cloudflare.com.
  TXT: "v=spf1 -all"
"""
    records = _extract_dns_records(text)
    assert records["A"] == ["198.18.0.4"]
    assert records["AAAA"] == []
    assert "elliott.ns.cloudflare.com" in records["NS"]
    assert "hera.ns.cloudflare.com" in records["NS"]


def test_extract_dns_records_markdown_table() -> None:
    text = """| A | 198.18.0.4 |
| MX | 0 . |
| NS | elliott.ns.cloudflare.com、hera.ns.cloudflare.com |
"""
    records = _extract_dns_records(text)
    assert "198.18.0.4" in records["A"]
    assert "elliott.ns.cloudflare.com" in records["NS"]


def test_extract_open_ports() -> None:
    text = """端口扫描结果:
主机: example.com
  22/tcp  open  ssh
  80/tcp  open  http
  443/tcp open https
"""
    ports = _extract_open_ports(text)
    assert ports == [("22", "ssh"), ("80", "http"), ("443", "https")]


def test_extract_open_ports_no_service_field_uses_hint() -> None:
    text = "  3306/tcp  open"
    ports = _extract_open_ports(text)
    assert ports == [("3306", "mysql")]


def test_extract_open_ports_empty() -> None:
    assert _extract_open_ports("") == []
    assert _extract_open_ports("未发现 example.com 的开放端口") == []


def test_summarize_subdomains_wildcard_filtered() -> None:
    text = "⚠ 检测到 wildcard DNS (*.example.com → 198.18.0.0/15)，已过滤 1998 条疑似假阳性\n未发现 example.com 的存活子域名（已检测 2000 个）"
    info = _summarize_subdomains(text)
    assert info["wildcard"] is True
    assert info["filtered"] == 1998


def test_summarize_subdomains_normal_finds() -> None:
    text = "子域名枚举 (example.com) — 发现 12/2000:"
    info = _summarize_subdomains(text)
    assert info["found"] == 12
    assert info["wildcard"] is False


def test_build_topology_full_example() -> None:
    out = build_topology(
        target="example.com",
        dns_info="A: 198.18.0.4\nNS: ns1.cf.com\nNS: ns2.cf.com",
        subdomains="发现 5/2000",
        open_ports="80/tcp open\n443/tcp open",
    )
    assert "## 🌐 拓扑" in out
    assert "example.com" in out
    assert "198.18.0.4" in out
    assert "ns1.cf.com" in out
    assert ":80" in out and "(open)" in out
    assert ":443" in out
    assert "5 项存活" in out


def test_build_topology_wildcard_marker() -> None:
    out = build_topology(
        target="example.com",
        dns_info="A: 198.18.0.4",
        subdomains="⚠ 检测到 wildcard DNS，已过滤 1998 条",
    )
    assert "wildcard 过滤 ⚠" in out
    assert "1998" in out


def test_build_topology_empty_input_returns_empty() -> None:
    assert build_topology("example.com") == ""
    assert build_topology("example.com", dns_info="无任何记录") == ""


def test_build_topology_only_dns_no_ports() -> None:
    out = build_topology(target="x.com", dns_info="A: 1.2.3.4\nNS: ns.x.com")
    assert "x.com" in out
    assert "1.2.3.4" in out
    # 不应有端口行
    assert "/tcp" not in out


def test_build_topology_ascii_tree_structure() -> None:
    """验证 ASCII 树字符正确（├ / └）。"""
    out = build_topology(
        target="x.com",
        dns_info="A: 1.2.3.4\nNS: ns.x.com",
        open_ports="80/tcp open",
    )
    assert "├──" in out  # 至少有一个非末端分支
    assert "└──" in out  # 至少有一个末端分支
