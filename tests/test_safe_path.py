"""issue #15.2 — utils.safe_path 单元测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils import safe_path


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    safe_path.reset_cache()
    yield
    safe_path.reset_cache()


def _patch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """让 SECAGENT_HOME / CWD 指向 tmp 子目录；CONFIG_PATH 不存在 → 默认白名单。

    返回 (fake_home, fake_cwd)。两者是 tmp_path 的兄弟子目录，便于构造"外部"路径。
    """
    fake_home = tmp_path / "argus_home"
    fake_cwd = tmp_path / "cwd"
    fake_home.mkdir(exist_ok=True)
    fake_cwd.mkdir(exist_ok=True)
    monkeypatch.setattr("utils.safe_path.SECAGENT_HOME", str(fake_home))
    monkeypatch.setattr("utils.paths.CONFIG_PATH", str(tmp_path / "no_config.toml"))
    monkeypatch.chdir(fake_cwd)
    safe_path.reset_cache()
    return fake_home, fake_cwd


class TestDefaults:
    def test_secagent_home_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home, _cwd = _patch_paths(tmp_path, monkeypatch)
        assert safe_path.is_path_allowed(str(home / "x.md"), mode="write")

    def test_cwd_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _home, cwd = _patch_paths(tmp_path, monkeypatch)
        assert safe_path.is_path_allowed(str(cwd / "in_cwd.txt"), mode="write")

    def test_outside_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_paths(tmp_path, monkeypatch)
        # tmp_path/outside 不在 fake_home 也不在 fake_cwd 内
        outside = tmp_path / "outside" / "away.txt"
        assert not safe_path.is_path_allowed(str(outside), mode="write")

    def test_invalid_mode_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_paths(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            safe_path.is_path_allowed("x", mode="execute")


class TestRequireSafe:
    def test_returns_abspath(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _home, cwd = _patch_paths(tmp_path, monkeypatch)
        out = safe_path.require_safe_path(str(cwd / "ok.md"), mode="write")
        assert os.path.isabs(out)

    def test_raises_permission_error_outside(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_paths(tmp_path, monkeypatch)
        outside = tmp_path / "outside" / "x"
        with pytest.raises(PermissionError):
            safe_path.require_safe_path(str(outside), mode="write")


class TestConfigExtras:
    def test_write_allowed_dirs_extends(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        extra = tmp_path / "extra_writable"
        extra.mkdir(exist_ok=True)
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[security]\nwrite_allowed_dirs = ["{str(extra).replace(chr(92), "/")}"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        monkeypatch.setattr("utils.safe_path.SECAGENT_HOME", str(tmp_path / "argus_home"))
        # 让 cwd 也在 tmp 下，与 extra 并列（不重叠）
        cwd = tmp_path / "cwd_iso"
        cwd.mkdir(exist_ok=True)
        monkeypatch.chdir(cwd)
        safe_path.reset_cache()
        assert safe_path.is_path_allowed(str(extra / "ok.md"), mode="write")

    def test_prefix_collision_avoided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`/foo/bar` 不应让 `/foo/barbaz` 被放行（commonpath 防护）。"""
        _patch_paths(tmp_path, monkeypatch)
        sneaky = tmp_path / "cwd_evil" / "x.txt"
        # sneaky 名字以 cwd 开头但不是 cwd 的子目录——commonpath 应拒绝
        assert not safe_path.is_path_allowed(str(sneaky), mode="write")
