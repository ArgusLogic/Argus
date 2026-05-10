"""Day1-1 (issue #21): dir_bruteforce 墙钟预算 + WAF / 不可达早停回归测试。

通过伪造 httpx MockTransport 精确控制响应，验证：
  1. wall_budget 到期后剩余 task 不再发请求（aborted_reason=wall_budget）
  2. 连续 429/503 ≥ 8 次 → aborted_reason=rate_limited
  3. 连续异常 ≥ 20 次 → aborted_reason=unreachable
  4. 正常完成 (200 混合 404) → 无 aborted_reason
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # 保存原类，绕开 recon.httpx patch 递归


def _mk_fake_client_factory(transport: httpx.MockTransport):  # type: ignore[no-untyped-def]
    def _factory(**kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("timeout", None)
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(**kwargs)

    return _factory


@pytest.mark.asyncio
async def test_dir_bruteforce_normal_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常场景：一半 200 一半 404，全部跑完且无早停警告。"""
    from tools import recon

    wordlist = ["admin", "login", "api", "backup", "config", "dashboard"]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if request.url.path.startswith(("/__argus_baseline", "/argus_404")):
            return httpx.Response(404, content=b"baseline-not-found")
        if request.url.path in ("/admin", "/login", "/api"):
            return httpx.Response(200, content=b"hit" + request.url.path.encode())
        return httpx.Response(404, content=b"missing")

    transport = httpx.MockTransport(handler)

    with (
        patch.object(recon, "DIRECTORIES", wordlist),
        patch.object(recon.httpx, "AsyncClient", _mk_fake_client_factory(transport)),
    ):
        out = await recon.dir_bruteforce("https://example.com", concurrency="3")

    assert "墙钟预算" not in out
    assert "WAF" not in out
    assert "不可达" not in out
    # 3 个 200 命中应该都在
    assert "/admin" in out
    assert "/login" in out
    assert "/api" in out


@pytest.mark.asyncio
async def test_dir_bruteforce_rate_limit_early_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有请求返 429 → 很快触发 WAF 判定并早停。"""
    from tools import recon

    wordlist = [f"p{i}" for i in range(200)]  # 200 条，但应该在 streak=8 后就停

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.startswith(("/__argus_baseline", "/argus_404")):
            return httpx.Response(404, content=b"baseline")
        return httpx.Response(429, content=b"rate limited")

    transport = httpx.MockTransport(handler)

    with (
        patch.object(recon, "DIRECTORIES", wordlist),
        patch.object(recon.httpx, "AsyncClient", _mk_fake_client_factory(transport)),
        patch.object(recon, "_DIR_RATE_LIMIT_STREAK", 5),
    ):
        out = await recon.dir_bruteforce("https://example.com", concurrency="1")

    assert "429" in out and "WAF" in out
    # 基线 2 + 至少 streak 次 = 合理上限远小于 202
    assert calls["n"] < 100


@pytest.mark.asyncio
async def test_dir_bruteforce_unreachable_early_stop() -> None:
    """请求总是抛异常 → 触发 unreachable 早停。"""
    from tools import recon

    wordlist = [f"p{i}" for i in range(200)]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.startswith(("/__argus_baseline", "/argus_404")):
            # baseline 成功返 404 让主流程进入
            return httpx.Response(404)
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)

    with (
        patch.object(recon, "DIRECTORIES", wordlist),
        patch.object(recon.httpx, "AsyncClient", _mk_fake_client_factory(transport)),
        patch.object(recon, "_DIR_ERROR_STREAK", 5),
    ):
        out = await recon.dir_bruteforce("https://example.com", concurrency="1")

    assert "[ABORTED:UNREACHABLE]" in out  # Bug 4: 机器可读 token
    assert "不可达" in out or "离线" in out
    assert "不要继续" in out  # 强建议给 LLM
    assert calls["n"] < 100  # 大部分 task 都被早停跳过


@pytest.mark.asyncio
async def test_dir_bruteforce_wall_budget_stops_remaining() -> None:
    """墙钟预算：处理每条都 sleep 0.05s，6 条字典 + 预算 0.1s → 应报告 wall_budget。"""
    from tools import recon

    wordlist = [f"slow{i}" for i in range(50)]

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(404)

    transport = httpx.MockTransport(slow_handler)

    with (
        patch.object(recon, "DIRECTORIES", wordlist),
        patch.object(recon.httpx, "AsyncClient", _mk_fake_client_factory(transport)),
        patch.object(recon, "_resolve_dir_budget", lambda: 0.15),
    ):
        out = await recon.dir_bruteforce("https://example.com", concurrency="1")

    assert "墙钟预算" in out or "提前收尾" in out


# ──────────────────────────────────────────────────────────────────────────
# Day 5 issue 1 修复回归：_resolve_dir_budget 自适应 tool_timeout
# ──────────────────────────────────────────────────────────────────────────


class TestResolveDirBudget:
    """budget 必须 ≤ tool_timeout - safety_margin，且 ≥ floor，且 ≤ 上限常量。"""

    def test_budget_respects_tool_timeout(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        """tool_timeout=20 → budget=15（被 timeout - 5 压低，未顶到 30）。"""
        from tools import recon

        cfg = tmp_path / "config.toml"
        cfg.write_text("[general]\ntool_timeout = 20\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        from utils import config as cfg_mod

        cfg_mod.reload()
        assert recon._resolve_dir_budget() == pytest.approx(15.0)

    def test_budget_capped_by_default(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        """tool_timeout=120 → budget=30（上限常量起作用，不会到 115）。"""
        from tools import recon

        cfg = tmp_path / "config.toml"
        cfg.write_text("[general]\ntool_timeout = 120\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        from utils import config as cfg_mod

        cfg_mod.reload()
        assert recon._resolve_dir_budget() == pytest.approx(30.0)

    def test_budget_min_floor(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        """tool_timeout=3 → budget=5（floor 兜底，不会负数或 0）。"""
        from tools import recon

        cfg = tmp_path / "config.toml"
        cfg.write_text("[general]\ntool_timeout = 3\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        from utils import config as cfg_mod

        cfg_mod.reload()
        assert recon._resolve_dir_budget() == pytest.approx(5.0)

    def test_budget_fallback_on_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_section 抛异常 → 退回常量 30。"""
        from tools import recon

        def _boom(_name: str) -> dict:
            raise RuntimeError("simulated config corruption")

        monkeypatch.setattr("utils.config.get_section", _boom)
        assert recon._resolve_dir_budget() == pytest.approx(recon._DIR_WALL_BUDGET_S)


def test_dir_bruteforce_constants_sane() -> None:
    """sanity-check 4 个常量都是合理范围。"""
    from tools import recon

    assert 5 <= recon._DIR_WALL_BUDGET_S <= 120
    assert 3 <= recon._DIR_RATE_LIMIT_STREAK <= 20
    assert 10 <= recon._DIR_ERROR_STREAK <= 50
    assert 1.0 <= recon._DIR_PER_REQUEST_TIMEOUT <= 15.0
