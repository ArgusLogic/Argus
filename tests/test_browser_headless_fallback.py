"""issue #19: headless Linux 无 DISPLAY 时的强制降级测试。"""

from __future__ import annotations

import pytest

from tools.browser import _coerce_headed_for_environment


def test_headed_false_stays_false_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何环境下 headed=False 都该原样返回 False，不打 warning。"""
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert _coerce_headed_for_environment(False) is False


def test_linux_no_display_forces_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux + headed=True + DISPLAY 缺 → 强制 False。"""
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert _coerce_headed_for_environment(True) is False


def test_linux_with_display_keeps_headed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Linux")
    monkeypatch.setenv("DISPLAY", ":0")
    assert _coerce_headed_for_environment(True) is True


def test_windows_keeps_headed_regardless_of_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 不存在 DISPLAY 概念，绝不该被降级。"""
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Windows")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert _coerce_headed_for_environment(True) is True


def test_macos_keeps_headed_regardless_of_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Darwin")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert _coerce_headed_for_environment(True) is True


def test_warning_emitted_when_forcing_headless(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    captured: list[str] = []
    monkeypatch.setattr("tools.browser.log_warning", lambda msg: captured.append(str(msg)))
    _coerce_headed_for_environment(True)
    assert any("DISPLAY" in m for m in captured)
    assert any("headless" in m.lower() for m in captured)


def test_no_warning_when_headed_already_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.browser.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    captured: list[str] = []
    monkeypatch.setattr("tools.browser.log_warning", lambda msg: captured.append(str(msg)))
    _coerce_headed_for_environment(False)
    assert captured == []
