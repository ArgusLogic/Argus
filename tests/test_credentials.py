"""utils.credentials 单元测试。

覆盖 lookup / placeholder hint / expand 替换三大路径。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_cache():
    from utils.credentials import reset_cache
    reset_cache()
    yield
    reset_cache()


def _write_creds(path: Path) -> None:
    path.write_text(
        '[targets."127.0.0.1:8080"]\n'
        'username = "admin"\n'
        'password = "p4$$word!"\n'
        'login_url = "/login.php"\n'
        '\n'
        '[targets."demo.testfire.net"]\n'
        'username = "jsmith"\n'
        'password = "demo1234"\n'
        'login_url = "/login.jsp"\n',
        encoding="utf-8",
    )


def test_lookup_returns_none_when_file_missing(tmp_path: Path) -> None:
    from utils.credentials import lookup
    assert lookup("missing.example", path=tmp_path / "noexist.toml") is None


def test_lookup_returns_dict_for_known_host(tmp_path: Path) -> None:
    from utils.credentials import lookup
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    cred = lookup("127.0.0.1:8080", path=creds_path)
    assert cred is not None
    assert cred["username"] == "admin"
    assert cred["password"] == "p4$$word!"
    assert cred["login_url"] == "/login.php"


def test_lookup_returns_none_for_unknown_host(tmp_path: Path) -> None:
    from utils.credentials import lookup
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    assert lookup("unknown.example.com", path=creds_path) is None


def test_make_placeholder_hint_does_not_leak_password(tmp_path: Path) -> None:
    from utils.credentials import make_placeholder_hint
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    hint = make_placeholder_hint("127.0.0.1:8080", path=creds_path)
    # 关键断言：明文密码绝不能出现在 hint 字符串里
    assert "p4$$word!" not in hint
    # 但占位符必须出现
    assert "${CRED_127_0_0_1_8080_PASS}" in hint
    assert "${CRED_127_0_0_1_8080_USER}" in hint
    # 用户名作为非敏感信息可以出现（便于 LLM 识别确认对象）
    assert "admin" in hint


def test_make_placeholder_hint_unknown_host(tmp_path: Path) -> None:
    from utils.credentials import make_placeholder_hint
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    hint = make_placeholder_hint("nope.example.com", path=creds_path)
    assert "未找到" in hint


def test_expand_placeholders_replaces_known(tmp_path: Path) -> None:
    from utils.credentials import expand_placeholders
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    args_str = (
        '{"login_url":"http://127.0.0.1:8080/login.php",'
        '"username":"${CRED_127_0_0_1_8080_USER}",'
        '"password":"${CRED_127_0_0_1_8080_PASS}"}'
    )
    expanded = expand_placeholders(args_str, path=creds_path)
    assert "${CRED_" not in expanded
    assert '"username":"admin"' in expanded
    assert '"password":"p4$$word!"' in expanded


def test_expand_placeholders_keeps_unknown_intact(tmp_path: Path) -> None:
    """unknown host 占位符保持原样不抛错。"""
    from utils.credentials import expand_placeholders
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    args_str = '{"x":"${CRED_unknown_PASS}"}'
    out = expand_placeholders(args_str, path=creds_path)
    assert "${CRED_unknown_PASS}" in out


def test_expand_placeholders_no_placeholder_no_change(tmp_path: Path) -> None:
    """无占位符的字符串原样返回（性能 & 幂等）。"""
    from utils.credentials import expand_placeholders
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    args_str = '{"username":"admin","password":"plaintext"}'
    assert expand_placeholders(args_str, path=creds_path) == args_str


def test_expand_placeholders_url_field(tmp_path: Path) -> None:
    from utils.credentials import expand_placeholders
    creds_path = tmp_path / "credentials.toml"
    _write_creds(creds_path)
    out = expand_placeholders("login_url=${CRED_demo_testfire_net_URL}", path=creds_path)
    assert out == "login_url=/login.jsp"


def test_safe_host_strips_special_chars(tmp_path: Path) -> None:
    """host 含 :, ., - 等，placeholder key 全部替换为 _。"""
    from utils.credentials import expand_placeholders, make_placeholder_hint
    creds_path = tmp_path / "credentials.toml"
    creds_path.write_text(
        '[targets."api-v2.example.com:443"]\n'
        'username = "u"\npassword = "x"\n',
        encoding="utf-8",
    )
    hint = make_placeholder_hint("api-v2.example.com:443", path=creds_path)
    assert "${CRED_api_v2_example_com_443_USER}" in hint
    expanded = expand_placeholders(
        "user=${CRED_api_v2_example_com_443_USER}", path=creds_path
    )
    assert expanded == "user=u"
