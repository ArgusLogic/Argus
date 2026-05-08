"""utils.scrub 单元测试 — 凭据脱敏覆盖。"""

from __future__ import annotations


def test_scrub_kv_form() -> None:
    from utils.scrub import scrub
    out = scrub("password=p4$$word")
    assert "p4$$word" not in out
    assert "***" in out


def test_scrub_colon_form() -> None:
    from utils.scrub import scrub
    out = scrub("password: secret123")
    assert "secret123" not in out
    assert "***" in out


def test_scrub_json_form() -> None:
    from utils.scrub import scrub
    out = scrub('{"password":"hunter2","other":"keep"}')
    assert "hunter2" not in out
    assert "keep" in out  # 非 password 字段保留


def test_scrub_passwd_alias() -> None:
    from utils.scrub import scrub
    assert "secret" not in scrub("passwd=secret")


def test_scrub_pwd_alias() -> None:
    from utils.scrub import scrub
    assert "secret" not in scrub("pwd: secret")


def test_scrub_authorization_bearer() -> None:
    from utils.scrub import scrub
    out = scrub("Authorization: Bearer abcdef.ghijkl-mnopq.rstuvw")
    assert "abcdef" not in out
    assert "Bearer" in out
    assert "***" in out


def test_scrub_authorization_basic() -> None:
    from utils.scrub import scrub
    out = scrub("Authorization: Basic YWRtaW46cGFzc3dvcmQ=")
    assert "YWRtaW46" not in out


def test_scrub_api_key() -> None:
    from utils.scrub import scrub
    assert "sk-abc123" not in scrub("api_key=sk-abc123def456")
    assert "sk-abc123" not in scrub('"api-key": "sk-abc123def456"')


def test_scrub_does_not_break_other_text() -> None:
    """正常文本不应被改动。"""
    from utils.scrub import scrub
    text = "用户登录到 admin 页面，浏览器 cookies = 5"
    assert scrub(text) == text


def test_scrub_empty_returns_empty() -> None:
    from utils.scrub import scrub
    assert scrub("") == ""
    assert scrub(None) is None  # type: ignore[arg-type]


def test_scrub_preserves_username_field() -> None:
    """username 不应被 mask（不是敏感字段），只 mask password 类。"""
    from utils.scrub import scrub
    out = scrub('{"username":"admin","password":"secret"}')
    assert "admin" in out
    assert "secret" not in out


def test_scrub_idempotent() -> None:
    """scrub(scrub(x)) == scrub(x)。"""
    from utils.scrub import scrub
    once = scrub("password=secret123 api_key=key456")
    twice = scrub(once)
    assert once == twice
