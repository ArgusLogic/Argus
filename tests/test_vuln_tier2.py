"""vuln_scan Tier-2 测试 — vuln_cmd_injection + vuln_ssrf。

策略与 Tier-1 一致：
  - httpx.MockTransport 拦截 HTTP，无外网依赖
  - is_authorized_target 用 monkeypatch 切换
  - timing 路径直接 mock _measure 避免真实 sleep
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.asyncio


def _patch_authorized(allowed: bool, reason: str = "test-mock"):
    from tools import vuln_scan

    return patch.object(
        vuln_scan, "is_authorized_target", lambda url: (allowed, reason)
    )


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    class _Wrap(orig):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    return patch("tools.vuln_scan.httpx.AsyncClient", _Wrap)


# ──────────────────────────────────────────────────────────────────────────
# vuln_cmd_injection
# ──────────────────────────────────────────────────────────────────────────


async def test_cmdi_authorization_blocks_unauthorized() -> None:
    from tools.vuln_scan import vuln_cmd_injection

    with _patch_authorized(False, "未授权-mock"):
        out = await vuln_cmd_injection("http://evil.com/x?cmd=ls", "cmd")
    assert "拒绝执行" in out
    assert "未授权-mock" in out


async def test_cmdi_echo_path_hit() -> None:
    """响应体回显 token → path=echo, vulnerable=true, confidence=high。"""
    from tools.vuln_scan import vuln_cmd_injection

    def handler(request: httpx.Request) -> httpx.Response:
        # 任何请求都把 query 里的 cmd 值"原样执行 echo"——返回 marker
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(str(request.url)).query)
        cmd_val = q.get("cmd", [""])[0]
        # 模拟服务端真的执行了 ;echo argus_cmdi_<token>; → 返回 token
        if "argus_cmdi_" in cmd_val:
            # 提取 token（payload 里的 echo 后字符串）
            import re

            m = re.search(r"argus_cmdi_([a-z0-9]+)", cmd_val)
            if m:
                return httpx.Response(200, text=f"output: argus_cmdi_{m.group(1)}\n")
        return httpx.Response(200, text="hello")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_cmd_injection("http://allowed.example/run?cmd=ls", "cmd")
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["path"] == "echo"
    assert data["confidence"] == "high"
    assert data["echo_hits"] >= 1
    # echo 命中后不应跑 timing
    assert "timing_results" not in data or len(data.get("timing_results", [])) == 0


async def test_cmdi_timing_path_hit() -> None:
    """echo 不命中、sleep payload 真"睡了" → path=timing, vulnerable=true。"""
    from tools.vuln_scan import vuln_cmd_injection

    async def fake_measure(client, method, url, headers):
        # 任何含 sleep / timeout / ping 的 payload 都返回 5.2s，基线 0.1s
        u = str(url)
        if any(k in u for k in ("sleep", "timeout", "ping")):
            return 5.2
        return 0.1

    def handler(request: httpx.Request) -> httpx.Response:
        # echo 永远不回显 → 强制走 timing 路径
        return httpx.Response(200, text="generic response")

    with (
        _patch_authorized(True),
        _mock_client(handler),
        patch("tools.vuln_scan._measure", fake_measure),
    ):
        out = await vuln_cmd_injection("http://allowed.example/q?host=a", "host")
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["path"] == "timing"
    assert data["confidence"] in ("medium", "high")  # ≥2 命中即 medium，全 6 命中 high 也 ok
    assert data["timing_hits"] >= 2


async def test_cmdi_no_injection() -> None:
    """echo 不回显 + 无时延差 → vulnerable=false, path=none。"""
    from tools.vuln_scan import vuln_cmd_injection

    async def fake_measure(client, method, url, headers):
        return 0.1  # 基线 + 所有 payload 都一样快

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="filtered")

    with (
        _patch_authorized(True),
        _mock_client(handler),
        patch("tools.vuln_scan._measure", fake_measure),
    ):
        out = await vuln_cmd_injection("http://allowed.example/q?x=1", "x")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["path"] == "none"
    assert data["confidence"] == "none"


async def test_cmdi_baseline_high_latency_no_false_positive() -> None:
    """基线本身就慢（5.0s），payload 也 5.2s → delta=0.2s 不命中。"""
    from tools.vuln_scan import vuln_cmd_injection

    async def fake_measure(client, method, url, headers):
        return 5.2  # baseline 与 payload 都一样慢

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="slow but consistent")

    with (
        _patch_authorized(True),
        _mock_client(handler),
        patch("tools.vuln_scan._measure", fake_measure),
    ):
        out = await vuln_cmd_injection("http://allowed.example/q?x=1", "x")
    data = json.loads(out)
    assert data["vulnerable"] is False
    assert data["timing_hits"] == 0


# ──────────────────────────────────────────────────────────────────────────
# vuln_ssrf
# ──────────────────────────────────────────────────────────────────────────


async def test_ssrf_authorization_blocks_unauthorized() -> None:
    from tools.vuln_scan import vuln_ssrf

    with _patch_authorized(False, "未授权-ssrf"):
        out = await vuln_ssrf("http://evil.com/fetch?url=x", "url")
    assert "拒绝执行" in out
    assert "未授权-ssrf" in out


async def test_ssrf_marker_hit_linux_passwd() -> None:
    """file:///etc/passwd probe 响应含 'root:x:0' → severity=high。"""
    from tools.vuln_scan import vuln_ssrf

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(str(request.url)).query)
        u = q.get("url", [""])[0]
        if "etc/passwd" in u:
            return httpx.Response(
                200, text="root:x:0:0:root:/root:/bin/bash\nbin:x:1:1:bin:/bin:/sbin/nologin\n"
            )
        return httpx.Response(200, text="generic baseline body")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_ssrf("http://allowed.example/fetch?url=a", "url")
    data = json.loads(out)
    assert data["vulnerable"] is True
    assert data["severity"] == "high"
    # 找到对应 finding
    hits = [f for f in data["findings"] if f.get("marker_hit") is True]
    assert any(f["kind"] == "linux_passwd" for f in hits)


async def test_ssrf_marker_hit_aws_metadata() -> None:
    """AWS metadata probe 响应含 'ami-id' → severity=high。"""
    from tools.vuln_scan import vuln_ssrf

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(str(request.url)).query)
        u = q.get("url", [""])[0]
        if "169.254.169.254" in u:
            return httpx.Response(200, text="ami-id\nami-launch-index\nhostname\n")
        return httpx.Response(200, text="ok")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_ssrf("http://allowed.example/fetch?url=a", "url")
    data = json.loads(out)
    assert data["severity"] == "high"
    hits = [f for f in data["findings"] if f.get("marker_hit") is True]
    assert any(f["kind"] == "aws_metadata" for f in hits)


async def test_ssrf_status_diff_suspect() -> None:
    """baseline=200 + probe 返 500 + 无 marker → severity=medium。"""
    from tools.vuln_scan import vuln_ssrf

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(str(request.url)).query)
        u = q.get("url", [""])[0]
        if "example.com" in u:
            return httpx.Response(200, text="baseline body")
        # 所有 probe 返 500，无 marker
        return httpx.Response(500, text="internal error")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_ssrf("http://allowed.example/fetch?url=a", "url")
    data = json.loads(out)
    # 至少一个 finding 是 medium，且 overall severity=medium（无 high）
    assert data["severity"] == "medium"
    assert data["vulnerable"] is True


async def test_ssrf_no_findings() -> None:
    """baseline 与所有 probe 响应一致 → severity=none, vulnerable=false。"""
    from tools.vuln_scan import vuln_ssrf

    def handler(request: httpx.Request) -> httpx.Response:
        # 所有响应一致：200 + 空 body
        return httpx.Response(200, text="")

    with _patch_authorized(True), _mock_client(handler):
        out = await vuln_ssrf("http://allowed.example/fetch?url=a", "url")
    data = json.loads(out)
    assert data["severity"] == "none"
    assert data["vulnerable"] is False


# ──────────────────────────────────────────────────────────────────────────
# 注册检查
# ──────────────────────────────────────────────────────────────────────────


async def test_tier2_tools_registered() -> None:
    """vuln_cmd_injection + vuln_ssrf 都要在 registry 里。"""
    from agent.tool_registry import registry

    # 触发 import（registry 装饰器副作用）
    import tools.vuln_scan  # noqa: F401

    assert "vuln_cmd_injection" in registry._tools
    assert "vuln_ssrf" in registry._tools
    # 4 段格式：每段必有【】标记
    cmdi_desc = registry._tools["vuln_cmd_injection"]["description"]
    ssrf_desc = registry._tools["vuln_ssrf"]["description"]
    for marker in ("【作用】", "【关键参数】", "【何时用】", "【避坑】"):
        assert marker in cmdi_desc, f"vuln_cmd_injection 缺 {marker}"
        assert marker in ssrf_desc, f"vuln_ssrf 缺 {marker}"
