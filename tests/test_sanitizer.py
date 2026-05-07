"""utils.sanitizer 测试。"""

from __future__ import annotations

from utils.sanitizer import (
    redact_secrets,
    sanitize_domain,
    sanitize_filename,
    sanitize_url,
    strip_ansi,
    truncate,
)


class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        assert truncate("hello", max_len=100) == "hello"

    def test_exact_length_unchanged(self) -> None:
        text = "x" * 100
        assert truncate(text, max_len=100) == text

    def test_long_text_truncated(self) -> None:
        text = "x" * 10000
        result = truncate(text, max_len=200)
        assert len(result) < len(text)
        assert "truncated" in result
        assert result.startswith("x")
        assert result.endswith("x")

    def test_truncate_preserves_head_and_tail(self) -> None:
        text = "HEADHEADHEAD" + "M" * 1000 + "TAILTAILTAIL"
        result = truncate(text, max_len=100)
        assert "HEAD" in result
        assert "TAIL" in result

    def test_empty_text(self) -> None:
        assert truncate("", max_len=100) == ""


class TestSanitizeUrl:
    def test_already_https(self) -> None:
        assert sanitize_url("https://example.com") == "https://example.com"

    def test_already_http(self) -> None:
        assert sanitize_url("http://example.com") == "http://example.com"

    def test_adds_https_prefix(self) -> None:
        assert sanitize_url("example.com") == "https://example.com"

    def test_strips_whitespace(self) -> None:
        assert sanitize_url("  example.com  ") == "https://example.com"

    def test_with_path(self) -> None:
        assert sanitize_url("example.com/api/v1") == "https://example.com/api/v1"

    def test_with_port(self) -> None:
        assert sanitize_url("example.com:8080") == "https://example.com:8080"


class TestSanitizeFilename:
    def test_simple_name_unchanged(self) -> None:
        assert sanitize_filename("report.txt") == "report.txt"

    def test_path_traversal_stripped(self) -> None:
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_windows_path_stripped(self) -> None:
        assert sanitize_filename(r"C:\Windows\System32\evil.exe") == "evil.exe"

    def test_illegal_chars_replaced(self) -> None:
        result = sanitize_filename("a<b>c:d.txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_leading_trailing_dots_stripped(self) -> None:
        assert sanitize_filename("...hidden...") == "hidden"

    def test_empty_returns_unnamed(self) -> None:
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("   ") == "unnamed"

    def test_only_dots_returns_unnamed(self) -> None:
        assert sanitize_filename("...") == "unnamed"

    def test_truncates_long_name_preserves_extension(self) -> None:
        long_name = "x" * 300 + ".txt"
        result = sanitize_filename(long_name, max_len=50)
        assert len(result) <= 50
        assert result.endswith(".txt")

    def test_control_chars_stripped(self) -> None:
        assert "\x00" not in sanitize_filename("file\x00name.txt")


class TestSanitizeDomain:
    def test_plain_domain(self) -> None:
        assert sanitize_domain("example.com") == "example.com"

    def test_strips_https(self) -> None:
        assert sanitize_domain("https://example.com") == "example.com"

    def test_strips_path(self) -> None:
        assert sanitize_domain("https://example.com/api/v1?key=x") == "example.com"

    def test_strips_port(self) -> None:
        assert sanitize_domain("example.com:8443") == "example.com"

    def test_strips_userinfo(self) -> None:
        assert sanitize_domain("https://user:pass@example.com/path") == "example.com"

    def test_lowercases(self) -> None:
        assert sanitize_domain("EXAMPLE.COM") == "example.com"

    def test_empty_returns_none(self) -> None:
        assert sanitize_domain("") is None
        assert sanitize_domain("   ") is None

    def test_invalid_returns_none(self) -> None:
        assert sanitize_domain("not_a_domain") is None
        assert sanitize_domain("just text") is None

    def test_subdomain(self) -> None:
        assert sanitize_domain("api.v2.example.com") == "api.v2.example.com"


class TestStripAnsi:
    def test_removes_color_codes(self) -> None:
        text = "\x1b[31mred\x1b[0m"
        assert strip_ansi(text) == "red"

    def test_removes_cursor_movement(self) -> None:
        text = "\x1b[2J\x1b[H some output"
        assert strip_ansi(text) == " some output"

    def test_plain_text_unchanged(self) -> None:
        assert strip_ansi("hello world") == "hello world"

    def test_empty(self) -> None:
        assert strip_ansi("") == ""
        assert strip_ansi(None) == ""  # type: ignore

    def test_complex_sequence(self) -> None:
        text = "\x1b[1;38;2;255;0;0mbold red\x1b[0m end"
        assert strip_ansi(text) == "bold red end"


class TestRedactSecrets:
    def test_openai_key(self) -> None:
        text = "config: sk-abc123def456ghi789jklmnop"
        result = redact_secrets(text)
        assert "sk-abc" not in result
        assert "[REDACTED:openai_key]" in result

    def test_anthropic_key(self) -> None:
        text = "key=sk-ant-api03-abcdef0123456789"
        result = redact_secrets(text)
        assert "sk-ant-api" not in result
        assert "REDACTED" in result

    def test_github_token(self) -> None:
        text = "token: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        result = redact_secrets(text)
        assert "ghp_aa" not in result
        assert "[REDACTED:github_token]" in result

    def test_aws_access_key(self) -> None:
        text = "Access key: AKIAIOSFODNN7EXAMPLE goes here"
        result = redact_secrets(text)
        assert "AKIAIOSF" not in result
        assert "[REDACTED:aws_access_key]" in result

    def test_jwt(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "abc123def456ghi"
        )
        text = f"Authorization: {jwt}"
        result = redact_secrets(text)
        assert jwt not in result
        assert "[REDACTED:jwt]" in result

    def test_bearer_token(self) -> None:
        text = "Authorization: Bearer abc123def456ghi789jklmnop"
        result = redact_secrets(text)
        assert "abc123def456" not in result
        assert "[REDACTED:bearer_token]" in result

    def test_password_value_only(self) -> None:
        """password=xxx 应只 redact xxx，保留 'password=' 前缀。"""
        text = "config password=supersecret123 next_field"
        result = redact_secrets(text)
        assert "password" in result.lower()
        assert "supersecret" not in result
        assert "[REDACTED:password]" in result

    def test_api_key_value_only(self) -> None:
        text = 'api_key="abc123def456ghi789xyz"'
        result = redact_secrets(text)
        assert "abc123def456" not in result
        assert "api_key" in result.lower()

    def test_private_key_block(self) -> None:
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA...\n"
            "abcdefABCDEF1234\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = redact_secrets(text)
        assert "MIIEowIB" not in result
        assert "[REDACTED:private_key]" in result

    def test_no_false_positive_on_normal_text(self) -> None:
        text = "Hello world, this is a normal message about example.com"
        assert redact_secrets(text) == text

    def test_empty_text(self) -> None:
        assert redact_secrets("") == ""

    def test_multiple_secrets_in_one_text(self) -> None:
        text = (
            "openai: sk-aaaaaaaaaaaaaaaaaaaaaaaa\n"
            "github: ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
            "aws: AKIAABCDEFGHIJKLMNOP"
        )
        result = redact_secrets(text)
        assert "sk-aaa" not in result
        assert "ghp_bbb" not in result
        assert "AKIAABC" not in result
        assert result.count("REDACTED") == 3

    def test_does_not_redact_short_strings(self) -> None:
        # 'sk-short' 不到 20 字符，不应触发
        assert "sk-short" in redact_secrets("key sk-short")
