"""vuln_scan Tier 1 测试 — 4 工具 + 授权门 + 注册。

策略：用 httpx.MockTransport 拦截 HTTP 请求，无外网依赖。
授权门通过 monkeypatch is_authorized_target 切换。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.asyncio


def _patch_authorized(allowed: bool, reason: str = "test-mock"):
    # patch 的是 tools.vuln_scan 命名空间里的引用（import 后的副本）
    from tools import vuln_scan
    return patch.object(
        vuln_scan, "is_authorized_target", lambda url: (allowed, reason)
    )


def _mock_client(handler):
    """返回一个 httpx.AsyncClient(transport=MockTransport(handler)) 的工厂 patch。"""
    transport = httpx.MockTransport(handler)
    orig_async_client = httpx.AsyncClient

    class _Wrap(orig_async_client):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    return patch("tools.vuln_scan.httpx.AsyncClient", _Wrap)


# ─── 授权门 ─────────────────────────────────────────────────────────────────


async def test_unauthorized_target_blocked() -> None:
    from tools.vuln_scan import vuln_sqli_timing
    with _patch_authorized(False, "错误-mock-reason"):
        out = await vuln_sqli_timing("http://evil.com/p?id=1", "id")
    assert "拒绝执行" in out
    assert "错误-mock-reason" in out


async def test_authorized_path_proceeds() -> None:
    from tools.vuln_scan import vuln_cors_misconfig

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Access-Control-Allow-Origin": "*"})

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_cors_misconfig("http://allowed.example/api")
    data = json.loads(out)
    assert data["acao"] == "*"
    assert "authorization" in data


# ─── vuln_sqli_timing ───────────────────────────────────────────────────────


async def test_sqli_timing_baseline_no_signal() -> None:
    """所有请求快速返回 → 无 SQLi 信号。"""
    from tools.vuln_scan import vuln_sqli_timing

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_sqli_timing("http://allowed.example/q?id=1", "id")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["confidence"] == "none"
    assert data["triggered_count"] == 0


async def test_sqli_timing_detects_sleep() -> None:
    """payload 请求时延 ≥3s → 应判定 vulnerable。直接 mock _measure 避免真实 sleep。"""
    from tools.vuln_scan import vuln_sqli_timing

    async def fake_measure(client, method, url, headers):
        # 含 SLEEP / WAITFOR 的 payload URL 返回 3.5s；基线返回 0.1s
        if "SLEEP" in url.upper() or "WAITFOR" in url.upper():
            return 3.5
        return 0.1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    with _patch_authorized(True), \
         _mock_client(handler), \
         patch("tools.vuln_scan._measure", fake_measure):
        out = await vuln_sqli_timing(
            "http://allowed.example/q?id=1", "id", baseline_samples="1"
        )
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["confidence"] in ("high", "medium")
    assert data["triggered_count"] >= 1


# ─── vuln_xss_reflection ────────────────────────────────────────────────────


async def test_xss_reflection_unencoded_is_vulnerable() -> None:
    from tools.vuln_scan import vuln_xss_reflection

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        # 把 query 里的 q= 值原样回显（未编码）
        q = request.url.params.get("q", "")
        return httpx.Response(200, text=f"<html>echoed: {q}</html>")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_xss_reflection("http://allowed.example/search?q=hello", "q")
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["reflected"] is True
    assert data["encoded"] is False
    assert "argus_xss_probe" in data["probe"]


async def test_xss_reflection_encoded_not_vulnerable() -> None:
    """probe 被 HTML 编码（< → &lt;）→ 不算漏洞。"""
    from tools.vuln_scan import vuln_xss_reflection

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("q", "")
        # 模拟服务器编码
        encoded = q.replace("<", "&lt;").replace(">", "&gt;")
        return httpx.Response(200, text=f"<html>echoed: {encoded}</html>")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_xss_reflection("http://allowed.example/s?q=x", "q")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["reflected"] is False  # 原始 raw_probe 不在
    assert data["encoded"] is True


async def test_xss_reflection_no_echo() -> None:
    from tools.vuln_scan import vuln_xss_reflection

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>static</html>")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_xss_reflection("http://allowed.example/s?q=x", "q")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["reflected"] is False


# ─── vuln_open_redirect ─────────────────────────────────────────────────────


async def test_open_redirect_external_location_vulnerable() -> None:
    from tools.vuln_scan import vuln_open_redirect

    def handler(request: httpx.Request) -> httpx.Response:
        next_param = request.url.params.get("next", "")
        if "argus-redirect-probe.example" in next_param:
            return httpx.Response(302, headers={"Location": next_param})
        return httpx.Response(200)

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_open_redirect("http://allowed.example/go?next=ok", "next")
    data = json.loads(out)
    assert data["vulnerable"] is True


async def test_open_redirect_same_origin_safe() -> None:
    from tools.vuln_scan import vuln_open_redirect

    def handler(request: httpx.Request) -> httpx.Response:
        # 永远 302 到自家域，不跳外部
        return httpx.Response(302, headers={"Location": "/home"})

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_open_redirect("http://allowed.example/go?next=ok", "next")
    data = json.loads(out)
    assert data["vulnerable"] is False


# ─── vuln_cors_misconfig ────────────────────────────────────────────────────


async def test_cors_arbitrary_origin_with_credentials_high() -> None:
    from tools.vuln_scan import vuln_cors_misconfig

    def handler(request: httpx.Request) -> httpx.Response:
        # 回声任意 Origin + Credentials true → 高危
        return httpx.Response(
            200,
            headers={
                "Access-Control-Allow-Origin": request.headers.get("Origin", ""),
                "Access-Control-Allow-Credentials": "true",
            },
        )

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_cors_misconfig("http://allowed.example/api/data")
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["severity"] == "high"
    assert data["acac"].lower() == "true"


async def test_cors_wildcard_only_low() -> None:
    from tools.vuln_scan import vuln_cors_misconfig

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Access-Control-Allow-Origin": "*"})

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_cors_misconfig("http://allowed.example/api/x")
    data = json.loads(out)
    # ACAO: * 单独时 vulnerable=true（因为通配符）但 severity=low
    assert data["acao"] == "*"
    assert data["severity"] == "low"


async def test_cors_no_acao_safe() -> None:
    from tools.vuln_scan import vuln_cors_misconfig

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)  # 无 CORS 响应头

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_cors_misconfig("http://allowed.example/api/x")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["severity"] == "none"


# ─── 注册 + risk ────────────────────────────────────────────────────────────


async def test_all_four_tools_registered() -> None:
    import tools.vuln_scan
    from agent.tool_registry import registry
    names = registry.list_tools()
    for tname in (
        "vuln_sqli_timing",
        "vuln_xss_reflection",
        "vuln_open_redirect",
        "vuln_cors_misconfig",
    ):
        assert tname in names, f"{tname} 未注册"


async def test_all_four_tools_block_risk() -> None:
    from agent.engine import BLOCK_RISK_HINTS, TOOL_RISK_LEVELS
    for tname in (
        "vuln_sqli_timing",
        "vuln_xss_reflection",
        "vuln_open_redirect",
        "vuln_cors_misconfig",
    ):
        assert TOOL_RISK_LEVELS.get(tname) == "block"
        assert tname in BLOCK_RISK_HINTS


# ─── authorization 路径 ────────────────────────────────────────────────────


async def test_authorization_via_allowed_domains(tmp_path) -> None:
    """命中 config.toml [security] allowed_domains 即放行。"""
    from utils import authorization, config
    cfg = {"security": {"allowed_domains": ["allowed.example"]}}
    with patch.object(config, "get_config", lambda: cfg):
        ok, reason = authorization.is_authorized_target("http://allowed.example/x")
    assert ok is True
    assert "allowed.example" in reason


async def test_authorization_via_credentials(tmp_path) -> None:
    """命中 credentials.toml [targets.*] 也算授权。"""
    from utils import authorization, credentials
    creds_path = tmp_path / "credentials.toml"
    creds_path.write_text(
        '[targets."internal.example"]\nusername="u"\npassword="p"\n',
        encoding="utf-8",
    )
    with patch.object(credentials, "DEFAULT_CRED_PATH", creds_path):
        credentials.reset_cache()
        # 同时清空 allowed_domains 走凭据路径
        from utils import config
        with patch.object(config, "get_config", lambda: {"security": {"allowed_domains": []}}):
            ok, reason = authorization.is_authorized_target("http://internal.example/api")
    assert ok is True
    assert "credentials.toml" in reason


async def test_authorization_unauthorized_clear_message(tmp_path) -> None:
    from utils import authorization, config, credentials
    with patch.object(config, "get_config", lambda: {"security": {"allowed_domains": []}}), \
         patch.object(credentials, "DEFAULT_CRED_PATH", tmp_path / "noexist.toml"):
        credentials.reset_cache()
        ok, reason = authorization.is_authorized_target("http://random.example/x")
    assert ok is False
    assert "未授权" in reason
    assert "config.toml" in reason  # 提示如何放行
    assert "credentials.toml" in reason
