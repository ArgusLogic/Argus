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
