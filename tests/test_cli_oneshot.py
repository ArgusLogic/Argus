"""issue #8 — recon_modes + _parse_cli_args 一键侦察 CLI 测试。"""

from __future__ import annotations

import sys

import pytest

from agent.recon_modes import RECON_TEMPLATES, VALID_MODES, render_prompt

# ─── recon_modes ─────────────────────────────────────────────────────────────


class TestReconModes:
    def test_valid_modes_match_templates(self) -> None:
        assert set(VALID_MODES) == set(RECON_TEMPLATES.keys())
        assert "recon" in VALID_MODES
        assert "scan" in VALID_MODES
        assert "full" in VALID_MODES

    def test_render_recon_substitutes_target(self) -> None:
        out = render_prompt("example.com", "recon")
        assert "example.com" in out
        assert "dns_lookup" in out
        assert "subdomain_enum" in out
        # recon 不应触发主动扫描
        assert "port_scan" not in out
        assert "browser_navigate" not in out

    def test_render_scan_includes_active_tools(self) -> None:
        out = render_prompt("https://target.test", "scan")
        assert "target.test" in out
        assert "dir_bruteforce" in out
        assert "port_scan" in out
        assert "browser_navigate" not in out  # full 才上浏览器

    def test_render_full_includes_browser(self) -> None:
        out = render_prompt("foo.test", "full")
        assert "foo.test" in out
        assert "browser_navigate" in out
        assert "browser_screenshot" in out
        assert "generate_report" in out

    def test_render_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="未知"):
            render_prompt("x.com", "stealth")

    def test_render_empty_target_raises(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            render_prompt("   ", "recon")

    def test_render_strips_target(self) -> None:
        out = render_prompt("  example.com  ", "recon")
        assert "  example.com  " not in out
        assert "example.com" in out


# ─── _parse_cli_args ─────────────────────────────────────────────────────────


@pytest.fixture
def restore_argv():
    """fixture：测试结束后恢复 sys.argv。"""
    saved = sys.argv[:]
    yield
    sys.argv[:] = saved


class TestParseCliArgs:
    def _parse(self, *argv: str) -> dict:
        from main import _parse_cli_args

        sys.argv = ["main.py", *argv]
        return _parse_cli_args()

    def test_default_no_args(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse()
        assert out == {"yolo": False, "target": None, "mode": "recon"}

    def test_yolo_short(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse("-y")
        assert out["yolo"] is True

    def test_yolo_long(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse("--yolo")
        assert out["yolo"] is True

    def test_target_short(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse("-t", "example.com")
        assert out["target"] == "example.com"
        assert out["mode"] == "recon"

    def test_target_with_mode_scan(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse("--target", "example.com", "--mode", "scan")
        assert out["target"] == "example.com"
        assert out["mode"] == "scan"

    def test_target_with_mode_full_and_yolo(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        out = self._parse("-t", "x.com", "--mode", "full", "-y")
        assert out["target"] == "x.com"
        assert out["mode"] == "full"
        assert out["yolo"] is True

    def test_invalid_mode_exits(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as ei:
            self._parse("-t", "x.com", "--mode", "stealth")
        assert ei.value.code == 2

    def test_mode_without_target_exits(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as ei:
            self._parse("--mode", "scan")
        assert ei.value.code == 2

    def test_target_without_value_exits(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as ei:
            self._parse("-t")
        assert ei.value.code == 2

    def test_mode_without_value_exits(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as ei:
            self._parse("--mode")
        assert ei.value.code == 2

    def test_help_exits_zero(self, restore_argv) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as ei:
            self._parse("--help")
        assert ei.value.code == 0
