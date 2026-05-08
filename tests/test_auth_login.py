"""auth_login / credentials_lookup 工具测试（不依赖真实浏览器）。

策略：mock playwright Page，验证 selector 探测优先级、success_indicator 三种模式、
失败诊断、与 credentials placeholder 集成。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_page(query_results: dict[str, object] | None = None,
               url: str = "http://target/dashboard",
               content: str = "<html>welcome</html>") -> MagicMock:
    """构造一个 mock Page。query_results 控制 query_selector 行为。"""
    page = MagicMock()
    qr = query_results or {}

    async def _query_selector(sel: str):
        return qr.get(sel)

    page.query_selector = AsyncMock(side_effect=_query_selector)
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.press = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.content = AsyncMock(return_value=content)
    type(page).url = property(lambda self: url)  # property mock
    return page


# ─── _resolve_selector ───────────────────────────────────────────────────────


async def test_resolve_selector_uses_explicit_value() -> None:
    from tools.auth import _resolve_selector
    page = _make_page()
    out = await _resolve_selector(page, "#my-input", ("input[type='text']",), "用户名")
    assert out == "#my-input"
    page.query_selector.assert_not_called()


async def test_resolve_selector_auto_picks_first_matching() -> None:
    from tools.auth import _resolve_selector
    page = _make_page(query_results={"input[name='user']": MagicMock()})
    out = await _resolve_selector(
        page, "auto",
        ("input[name='username']", "input[name='user']", "input[type='text']"),
        "用户名",
    )
    assert out == "input[name='user']"


async def test_resolve_selector_auto_required_returns_failure_string() -> None:
    from tools.auth import _resolve_selector
    page = _make_page(query_results={})  # 没有任何匹配
    out = await _resolve_selector(page, "auto", ("input[name='x']",), "用户名", required=True)
    assert out.startswith("登录失败")
    assert "用户名" in out


async def test_resolve_selector_auto_optional_returns_empty() -> None:
    from tools.auth import _resolve_selector
    page = _make_page(query_results={})
    out = await _resolve_selector(page, "auto", ("button[type='submit']",), "提交按钮", required=False)
    assert out == ""


# ─── _check_indicator ───────────────────────────────────────────────────────


async def test_check_indicator_url_substring() -> None:
    from tools.auth import _check_indicator
    page = _make_page()
    assert await _check_indicator(page, "dashboard", "http://target/dashboard") is True


async def test_check_indicator_selector_match() -> None:
    from tools.auth import _check_indicator
    page = _make_page(query_results={".user-avatar": MagicMock()})
    assert await _check_indicator(page, ".user-avatar", "http://target/x") is True


async def test_check_indicator_text_in_body() -> None:
    from tools.auth import _check_indicator
    page = _make_page(content="<html>欢迎，admin</html>")
    assert await _check_indicator(page, "欢迎，admin", "http://target/x") is True


async def test_check_indicator_miss() -> None:
    from tools.auth import _check_indicator
    page = _make_page(content="<html>nothing</html>")
    assert await _check_indicator(page, "no-such-thing", "http://target/x") is False


# ─── auth_login 端到端（mock browser） ──────────────────────────────────────


async def test_auth_login_success_with_explicit_selectors() -> None:
    from tools import auth as auth_mod

    page = _make_page(
        query_results={
            "#user": MagicMock(),
            "#pass": MagicMock(),
            "#submit": MagicMock(),
        },
        url="http://target/dashboard",
    )
    pool = MagicMock()
    pool._context = MagicMock()
    pool._context.cookies = AsyncMock(return_value=[{"name": "PHPSESSID", "value": "x"}])

    with patch.object(auth_mod, "get_page", AsyncMock(return_value=page)), \
         patch.object(auth_mod, "get_pool", return_value=pool):
        out = await auth_mod.auth_login(
            login_url="http://target/login",
            username="admin", password="secret",
            user_field="#user", pass_field="#pass", submit_selector="#submit",
            success_indicator="dashboard",
        )
    assert "登录成功" in out
    assert "cookies = 1" in out
    page.fill.assert_any_await("#user", "admin")
    page.fill.assert_any_await("#pass", "secret")
    page.click.assert_awaited_with("#submit")


async def test_auth_login_uses_enter_when_no_submit_button() -> None:
    """没有 submit 按钮（且 auto 探测失败）时回退到 press(pass_sel, Enter)。"""
    from tools import auth as auth_mod

    page = _make_page(
        query_results={"input[type='password']": MagicMock()},  # 没有任何 submit 候选
        url="http://target/home",
    )
    pool = MagicMock()
    pool._context = MagicMock()
    pool._context.cookies = AsyncMock(return_value=[])

    with patch.object(auth_mod, "get_page", AsyncMock(return_value=page)), \
         patch.object(auth_mod, "get_pool", return_value=pool):
        out = await auth_mod.auth_login(
            login_url="http://target/login",
            username="u", password="p",
            user_field="#user", pass_field="auto",
            success_indicator="auto",
        )
    # 应该 press Enter 提交
    assert page.press.called
    args = page.press.call_args.args
    assert args[1] == "Enter"
    # 非 login URL → 启发式判 auto 成功
    assert "登录成功" in out


async def test_auth_login_failure_when_pass_field_not_found() -> None:
    from tools import auth as auth_mod

    page = _make_page(query_results={})  # 没有任何 input
    with patch.object(auth_mod, "get_page", AsyncMock(return_value=page)):
        out = await auth_mod.auth_login(
            login_url="http://target/login",
            username="u", password="p",
            user_field="#user", pass_field="auto",
        )
    assert out.startswith("登录失败")
    assert "密码" in out


async def test_auth_login_failure_when_indicator_not_found() -> None:
    from tools import auth as auth_mod

    page = _make_page(
        query_results={"#u": MagicMock(), "#p": MagicMock(), "#s": MagicMock()},
        url="http://target/login?error=1",  # 仍在 login URL
        content="<html>error</html>",
    )
    pool = MagicMock()
    pool._context = MagicMock()
    pool._context.cookies = AsyncMock(return_value=[])

    with patch.object(auth_mod, "get_page", AsyncMock(return_value=page)), \
         patch.object(auth_mod, "get_pool", return_value=pool):
        out = await auth_mod.auth_login(
            login_url="http://target/login",
            username="u", password="p",
            user_field="#u", pass_field="#p", submit_selector="#s",
            success_indicator="dashboard",
        )
    assert "登录失败" in out
    assert "/login" in out  # 当前 URL 包含在错误信息


# ─── credentials_lookup 工具集成 ────────────────────────────────────────────


async def test_credentials_lookup_returns_placeholder_not_password(tmp_path) -> None:
    """credentials_lookup 调用结果绝不能含明文密码。"""
    from utils import credentials as cred_mod
    creds_file = tmp_path / "credentials.toml"
    creds_file.write_text(
        '[targets."x.example"]\nusername="admin"\npassword="DO_NOT_LEAK"\n',
        encoding="utf-8",
    )
    with patch.object(cred_mod, "DEFAULT_CRED_PATH", creds_file):
        cred_mod.reset_cache()
        from tools.auth import credentials_lookup
        out = await credentials_lookup("x.example")
    assert "DO_NOT_LEAK" not in out
    assert "${CRED_x_example_PASS}" in out


# ─── 工具与 risk 注册 ───────────────────────────────────────────────────────


async def test_tools_registered() -> None:
    import tools.auth
    from agent.tool_registry import registry
    names = registry.list_tools()
    assert "auth_login" in names
    assert "credentials_lookup" in names


async def test_risk_levels_registered() -> None:
    from agent.engine import TOOL_RISK_LEVELS
    assert TOOL_RISK_LEVELS.get("credentials_lookup") == "safe"
    assert TOOL_RISK_LEVELS.get("auth_login") == "confirm"
