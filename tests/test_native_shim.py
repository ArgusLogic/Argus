"""utils._native 加速 shim 测试。

关键：确保即使 Rust crate 未安装，所有调用方仍然返回正确结果（fallback 路径）。
"""

from __future__ import annotations

from utils import _native
from utils.sanitizer import (
    _py_redact_secrets,
    _py_strip_ansi,
    _py_truncate,
    redact_secrets,
    strip_ansi,
    truncate,
)


class TestShimAvailability:
    def test_native_info_returns_string(self) -> None:
        info = _native.native_info()
        assert isinstance(info, str)
        assert len(info) > 0

    def test_has_native_returns_bool(self) -> None:
        assert isinstance(_native.has_native(), bool)


class TestFallbackEquivalence:
    """无论 Rust 是否可用，公开 API 输出必须等价于 _py_* 实现。"""

    def test_truncate_short_text(self) -> None:
        text = "hello"
        assert truncate(text, 100) == _py_truncate(text, 100)

    def test_truncate_long_text(self) -> None:
        text = "x" * 5000
        # 关键不变量
        result = truncate(text, 200)
        py_result = _py_truncate(text, 200)
        assert result == py_result

    def test_strip_ansi_color_codes(self) -> None:
        text = "\x1b[31mred\x1b[0m"
        assert strip_ansi(text) == _py_strip_ansi(text) == "red"

    def test_strip_ansi_empty(self) -> None:
        assert strip_ansi("") == _py_strip_ansi("") == ""

    def test_redact_openai_key(self) -> None:
        text = "config: sk-abc123def456ghi789jklmnop"
        assert redact_secrets(text) == _py_redact_secrets(text)
        assert "[REDACTED:openai_key]" in redact_secrets(text)

    def test_redact_password_keeps_key(self) -> None:
        text = "password=supersecret123"
        result = redact_secrets(text)
        py_result = _py_redact_secrets(text)
        assert result == py_result
        assert "password" in result
        assert "supersecret" not in result

    def test_redact_no_false_positive(self) -> None:
        text = "Hello world, normal message"
        assert redact_secrets(text) == _py_redact_secrets(text) == text

    def test_redact_empty(self) -> None:
        assert redact_secrets("") == _py_redact_secrets("") == ""


class TestNativeAttributesPresent:
    """_native 模块必须暴露所有期望的代理函数（无论是否 None）。"""

    def test_proxy_attributes_exist(self) -> None:
        for name in (
            "truncate", "strip_ansi", "redact_secrets",
            "parse_entries", "dedup_check", "format_block",
        ):
            assert hasattr(_native, name), f"missing _native.{name}"
