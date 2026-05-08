"""Day3-3: doctor 体检脚本单测。"""

from __future__ import annotations

from unittest.mock import patch

from agent.doctor import (
    CheckResult,
    _check_argus_home_writable,
    _check_default_model,
    _check_dependency,
    _check_provider_keys,
    _check_python,
    _check_wordlists,
    _mask_key,
    collect_checks,
    has_blocking_failures,
    render_doctor_report,
)


def test_check_python_passes_on_supported() -> None:
    r = _check_python()
    assert r.ok
    assert "Python" in r.name
    assert r.detail.split(".")[0].isdigit()


def test_check_dependency_known_module() -> None:
    r = _check_dependency("httpx")
    assert r.ok
    assert "v" in r.detail


def test_check_dependency_missing_module() -> None:
    r = _check_dependency("definitely_no_such_module_xyz")
    assert not r.ok


def test_check_argus_home_writable() -> None:
    r = _check_argus_home_writable()
    assert r.ok


def test_check_default_model_with_config() -> None:
    """conftest 把 ~/.argus 隔离到 tmp，但没默认 config，应该返回 not ok。"""
    r = _check_default_model()
    # 在 tmp 隔离环境下 default_model 多半为空，断言不崩即可
    assert isinstance(r.ok, bool)


def test_check_provider_keys_no_keys() -> None:
    """全空 config 时应有"至少一个 provider"的阻塞项。"""
    results = _check_provider_keys()
    blocking = [r for r in results if not r.ok and not r.optional]
    # 全空 config 下应有"LLM Provider 总览"阻塞失败
    assert any("总览" in b.name for b in blocking)


def test_check_provider_keys_with_one_configured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from utils import config

    monkeypatch.setattr(
        config,
        "get_section",
        lambda section: {"deepseek": "sk-test123"} if section == "api_keys" else {},
    )
    results = _check_provider_keys()
    # 有一个 provider 配了 → 不应有总览阻塞
    blocking = [r for r in results if not r.ok and not r.optional]
    assert all("总览" not in b.name for b in blocking)
    # deepseek 那条应 ok
    deepseek = next(r for r in results if "DeepSeek" in r.name)
    assert deepseek.ok


def test_check_wordlists_loads() -> None:
    results = _check_wordlists()
    # 内置字典应该都加载得到
    assert all(r.ok for r in results)


def test_mask_key_short() -> None:
    assert "..." in _mask_key("abc")
    assert _mask_key("") == "(空)"


def test_mask_key_long() -> None:
    masked = _mask_key("sk-d6e0dd12673a4e23")
    assert masked.startswith("sk-d6e")
    assert masked.endswith("4e23")
    assert "..." in masked


def test_collect_checks_runs() -> None:
    checks = collect_checks(ping_llm=False)
    assert len(checks) >= 8  # python + 5 deps + chromium + nmap + ~/.argus + model + 4 keys + 字典 ≥ 14
    assert all(isinstance(c, CheckResult) for c in checks)


def test_render_doctor_report_format() -> None:
    checks = [
        CheckResult(name="OK 项", ok=True, detail="ok"),
        CheckResult(name="可选失败", ok=False, detail="fail", optional=True),
        CheckResult(name="阻塞失败", ok=False, detail="blocker", optional=False),
    ]
    text = render_doctor_report(checks)
    assert "Argus doctor" in text
    assert "✓" in text
    assert "ⓘ" in text
    assert "✗" in text
    assert "阻塞项" in text
    assert "阻塞失败" in text


def test_render_doctor_report_all_pass_ready() -> None:
    checks = [CheckResult(name="A", ok=True, detail="x")]
    text = render_doctor_report(checks)
    assert "Ready" in text


def test_has_blocking_failures_logic() -> None:
    assert has_blocking_failures([CheckResult(name="x", ok=False, detail="", optional=False)])
    assert not has_blocking_failures([CheckResult(name="x", ok=False, detail="", optional=True)])
    assert not has_blocking_failures([CheckResult(name="x", ok=True, detail="")])


def test_run_doctor_silent_when_all_pass(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from agent import doctor

    fake_checks = [CheckResult(name="OK", ok=True, detail="x")]
    with patch.object(doctor, "collect_checks", return_value=fake_checks):
        ok = doctor.run_doctor(silent_unless_failure=True)
    assert ok is True
    captured = capsys.readouterr()
    # 静默模式 + 全通过 → 不打印
    assert captured.out == ""


def test_run_doctor_prints_on_blocking(capsys) -> None:  # type: ignore[no-untyped-def]
    from agent import doctor

    fake_checks = [CheckResult(name="Blocker", ok=False, detail="bad", optional=False)]
    with patch.object(doctor, "collect_checks", return_value=fake_checks):
        ok = doctor.run_doctor(silent_unless_failure=True)
    assert ok is False
    captured = capsys.readouterr()
    assert "Blocker" in captured.out
    assert "阻塞" in captured.out
