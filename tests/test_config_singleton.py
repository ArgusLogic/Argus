"""issue #9 — utils.config 单例测试。"""

from __future__ import annotations

import pytest

from utils import config as config_mod


@pytest.fixture(autouse=True)
def _flush_config_cache():  # type: ignore[no-untyped-def]
    config_mod.reload()
    yield
    config_mod.reload()


class TestGetConfig:
    def test_no_config_returns_empty_dict(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(tmp_path / "no.toml"))
        assert config_mod.get_config() == {}

    def test_reads_config_from_path(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            "[security]\nper_target_concurrency = 7\n[browser]\nheaded = true\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        out = config_mod.get_config()
        assert out["security"]["per_target_concurrency"] == 7
        assert out["browser"]["headed"] is True

    def test_caches_result(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[security]\nper_target_concurrency = 5\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        first = config_mod.get_config()
        # 改文件但不 reload，应仍返回缓存值
        cfg.write_text("[security]\nper_target_concurrency = 99\n", encoding="utf-8")
        second = config_mod.get_config()
        assert first is second
        assert second["security"]["per_target_concurrency"] == 5

    def test_reload_picks_up_new_value(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[security]\nper_target_concurrency = 5\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert config_mod.get_config()["security"]["per_target_concurrency"] == 5
        cfg.write_text("[security]\nper_target_concurrency = 99\n", encoding="utf-8")
        config_mod.reload()
        assert config_mod.get_config()["security"]["per_target_concurrency"] == 99

    def test_malformed_toml_returns_empty(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("this is not = valid toml [[[", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert config_mod.get_config() == {}


class TestGetSection:
    def test_existing_section(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[security]\nfoo = 1\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert config_mod.get_section("security") == {"foo": 1}

    def test_missing_section_returns_empty(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[browser]\nheaded = false\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert config_mod.get_section("nonexistent") == {}

    def test_section_wrong_type_returns_empty(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        # 顶层标量"security"，而非 table
        cfg.write_text('security = "oops"\n', encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        assert config_mod.get_section("security") == {}


class TestLegacyFallback:
    def test_skipped_when_config_path_not_default(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        """CONFIG_PATH 被改写到 tmp 后，找不到文件不应回落到仓库根 config.toml。"""
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(tmp_path / "no.toml"))
        assert config_mod._resolve_config_path() is None
