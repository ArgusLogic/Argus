"""issue #4 #7 — recon helpers 单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from tools.recon import (
    _load_custom_wordlist,
    _parse_port_spec,
    _tcp_connect_scan,
)

# ─── #4: _parse_port_spec / _tcp_connect_scan ───────────────────────────────


class TestParsePortSpec:
    def test_single(self) -> None:
        assert _parse_port_spec("80") == [80]

    def test_list(self) -> None:
        assert _parse_port_spec("80,443,8080") == [80, 443, 8080]

    def test_range(self) -> None:
        assert _parse_port_spec("21-25") == [21, 22, 23, 24, 25]

    def test_mixed(self) -> None:
        assert _parse_port_spec("21-23, 80, 443") == [21, 22, 23, 80, 443]

    def test_dedup_sort(self) -> None:
        assert _parse_port_spec("80,80,443,80") == [80, 443]

    def test_invalid_ignored(self) -> None:
        assert _parse_port_spec("80,abc,xx-yy,99999,443") == [80, 443]

    def test_empty(self) -> None:
        assert _parse_port_spec("") == []


@pytest.mark.asyncio
async def test_tcp_connect_scan_finds_open_port() -> None:
    """启动一个本地 TCP server，验证 _tcp_connect_scan 能发现它。"""

    async def handle(_reader, writer) -> None:  # type: ignore[no-untyped-def]
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await _tcp_connect_scan("127.0.0.1", str(port), timeout=1.0)
        assert "open" in result and str(port) in result
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_tcp_connect_scan_closed_port() -> None:
    # 选一个高端口几乎肯定关闭
    result = await _tcp_connect_scan("127.0.0.1", "1", timeout=0.3)
    assert "未发现" in result or "open" not in result.split("\n", 1)[-1]


@pytest.mark.asyncio
async def test_tcp_connect_scan_rejects_huge_range() -> None:
    result = await _tcp_connect_scan("127.0.0.1", "1-2000", timeout=0.1)
    assert "1024" in result


@pytest.mark.asyncio
async def test_tcp_connect_scan_invalid_spec() -> None:
    result = await _tcp_connect_scan("127.0.0.1", "not-a-port", timeout=0.1)
    assert "无法解析" in result


# ─── #7: _load_custom_wordlist ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _flush_config_cache():  # type: ignore[no-untyped-def]
    """issue #9：每个测试前后强制重读 config，避免单例缓存污染。"""
    from utils import config as _cfg

    _cfg.reload()
    yield
    _cfg.reload()


class TestLoadCustomWordlist:
    def test_no_config_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(tmp_path / "no.toml"))
        assert _load_custom_wordlist("subdomain_wordlist") is None

    def test_empty_path_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text('[security]\nsubdomain_wordlist = ""\n', encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert _load_custom_wordlist("subdomain_wordlist") is None

    def test_missing_file_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[security]\nsubdomain_wordlist = "{(tmp_path / "ghost.txt").as_posix()}"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert _load_custom_wordlist("subdomain_wordlist") is None

    def test_loads_entries_strips_comments(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        wl = tmp_path / "subs.txt"
        wl.write_text(
            "# comment\nadmin\n  api  \n\n# another\ndev\n",
            encoding="utf-8",
        )
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[security]\nsubdomain_wordlist = "{wl.as_posix()}"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        out = _load_custom_wordlist("subdomain_wordlist")
        assert out == ["admin", "api", "dev"]

    def test_empty_file_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        wl = tmp_path / "empty.txt"
        wl.write_text("# only comment\n\n", encoding="utf-8")
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[security]\nsubdomain_wordlist = "{wl.as_posix()}"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert _load_custom_wordlist("subdomain_wordlist") is None


# ─── Bug 1 (Coco 报告): port_scan 多 IP 只扫首个 ────────────────────────────


class TestPortScanMultiIP:
    @pytest.mark.asyncio
    async def test_multi_ip_hostname_uses_first_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hostname 解析到多个 IP 时，只把首个 IP 传给 nmap。"""
        from tools import recon

        # mock _resolve_ips 返回 3 个 IP
        async def fake_resolve(sub: str, domain: str) -> list[str]:
            return ["1.2.3.4", "5.6.7.8", "9.10.11.12"]

        captured: dict[str, str] = {}

        class FakeScanner:
            def scan(self, hosts: str, ports: str, arguments: str) -> None:
                captured["hosts"] = hosts

            def all_hosts(self) -> list:
                return []

        monkeypatch.setattr(recon, "_resolve_ips", fake_resolve)
        monkeypatch.setattr(recon.nmap, "PortScanner", FakeScanner)

        await recon.port_scan("multi-ip.example.com", "80")

        assert captured["hosts"] == "1.2.3.4", "应只把首个 IP 传给 nmap，避免对所有 IP 全扫"

    @pytest.mark.asyncio
    async def test_already_ip_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """target 本身是 IP 时不做 DNS 解析，直接传 nmap。"""
        from tools import recon

        captured: dict[str, str] = {}

        class FakeScanner:
            def scan(self, hosts: str, ports: str, arguments: str) -> None:
                captured["hosts"] = hosts

            def all_hosts(self) -> list:
                return []

        async def must_not_call(*args, **kw):  # noqa: ANN001,ANN002,ANN003
            raise AssertionError("IP 不应触发 DNS 解析")

        monkeypatch.setattr(recon, "_resolve_ips", must_not_call)
        monkeypatch.setattr(recon.nmap, "PortScanner", FakeScanner)

        await recon.port_scan("8.8.8.8", "53")

        assert captured["hosts"] == "8.8.8.8"


# ─── Hermes-C 报告 Bug 01+03: IP 段分类标注 ────────────────────────────────


class TestClassifyIP:
    """_classify_ip: 公网域名解析到保留段 = 数据可疑信号。"""

    def test_public_ip_returns_none(self) -> None:
        from tools.recon import _classify_ip

        assert _classify_ip("8.8.8.8") is None
        assert _classify_ip("1.1.1.1") is None

    def test_rfc1918_internal(self) -> None:
        from tools.recon import _classify_ip

        for ip in ("10.0.0.1", "172.16.5.5", "192.168.1.1"):
            label = _classify_ip(ip)
            assert label is not None
            assert "RFC1918" in label

    def test_rfc2544_fake_ip_section(self) -> None:
        """198.18.0.0/15 = WSL2 mihomo fake-IP / proxy 回环——必须明确标注。"""
        from tools.recon import _classify_ip

        for ip in ("198.18.0.73", "198.18.32.63", "198.19.255.255"):
            label = _classify_ip(ip)
            assert label is not None
            assert "RFC2544" in label
            assert "fake-IP" in label or "代理回环" in label, "标签必须提示用户这可能是代理回环"

    def test_loopback_and_linklocal(self) -> None:
        from tools.recon import _classify_ip

        assert "回环" in (_classify_ip("127.0.0.1") or "")
        assert "RFC3927" in (_classify_ip("169.254.10.10") or "")

    def test_invalid_ip_returns_none(self) -> None:
        from tools.recon import _classify_ip

        assert _classify_ip("not-an-ip") is None
        assert _classify_ip("") is None


class TestDnsLookupReservedTagging:
    """dns_lookup 命中保留段时必须打标签 + 末尾警告。"""

    @pytest.mark.asyncio
    async def test_a_record_in_reserved_segment_is_tagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 记录解析到 198.18.x.x → 应内联标注 + 尾部强警告。"""
        from tools import recon

        class _FakeRdata:
            def __init__(self, s: str) -> None:
                self._s = s

            def __str__(self) -> str:
                return self._s

        def fake_resolve(domain: str, rtype: str):  # noqa: ANN001
            if rtype == "A":
                return [_FakeRdata("198.18.32.63")]
            raise recon.dns.resolver.NoAnswer()

        monkeypatch.setattr(recon.dns.resolver, "resolve", fake_resolve)

        out = await recon.dns_lookup("httpbin.org", record_type="A")
        # 内联标签
        assert "[⚠" in out
        assert "RFC2544" in out
        # 尾部强警告
        assert "fake-IP" in out or "代理回环" in out
        assert "数据可信度低" in out

    @pytest.mark.asyncio
    async def test_public_a_record_no_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正常公网 IP 不应有保留段警告。"""
        from tools import recon

        class _FakeRdata:
            def __init__(self, s: str) -> None:
                self._s = s

            def __str__(self) -> str:
                return self._s

        def fake_resolve(domain: str, rtype: str):  # noqa: ANN001
            if rtype == "A":
                return [_FakeRdata("8.8.8.8")]
            raise recon.dns.resolver.NoAnswer()

        monkeypatch.setattr(recon.dns.resolver, "resolve", fake_resolve)

        out = await recon.dns_lookup("dns.google", record_type="A")
        assert "[⚠" not in out
        assert "数据可信度低" not in out
        assert "8.8.8.8" in out


class TestDnsLookupTxtFullBytes:
    """Hermes-C 报告 Bug 04: TXT 用 .strings 拼接拿完整字节，避免 str() 引号截断。"""

    @pytest.mark.asyncio
    async def test_txt_record_uses_full_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tools import recon

        # 模拟 dnspython TXT rdata：strings 是 list[bytes]，str() 表达可能引入边界
        full_txt = "v=spf1 include:%{i}._ip.%{h}._ehlo.%{d}._spf.vali.email ~all"

        class _FakeTxtRdata:
            strings = (full_txt.encode("utf-8"),)

            def __str__(self) -> str:
                # 模拟 str() 截断到引号边界（这是 Bug 04 描述的现象）
                return '"v=spf1 include:%{i}._ip.%{h}._ehlo.%{d}._spf.val'

        def fake_resolve(domain: str, rtype: str):  # noqa: ANN001
            if rtype == "TXT":
                return [_FakeTxtRdata()]
            raise recon.dns.resolver.NoAnswer()

        monkeypatch.setattr(recon.dns.resolver, "resolve", fake_resolve)

        out = await recon.dns_lookup("test.example", record_type="TXT")
        assert full_txt in out, "TXT 应输出完整内容（来自 .strings），而非 str() 截断的部分"
