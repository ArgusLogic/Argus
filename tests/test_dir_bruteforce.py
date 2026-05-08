"""issue #17: dir_bruteforce 基线校准回归测试。

历史 bug：在 Vercel/CDN 全 307 重定向站点上，190 条字典全部被报为"发现"。
新行为：先用 2 条随机路径打基线（status + body sha1 + size），命中基线则跳过。
"""

from __future__ import annotations

import httpx
import pytest

from tools.recon import (
    _body_fingerprint,
    _is_baseline_match,
    _probe_baseline,
    dir_bruteforce,
)

# ─── 工具函数 ────────────────────────────────────────────────────────────


def test_fingerprint_stable_for_same_body() -> None:
    assert _body_fingerprint(b"hello world") == _body_fingerprint(b"hello world")


def test_fingerprint_differs_for_different_body() -> None:
    assert _body_fingerprint(b"a" * 10) != _body_fingerprint(b"b" * 10)


def test_baseline_match_status_mismatch_means_no_match() -> None:
    base = {"ok": True, "codes": {307}, "fps": {"abc"}, "size": 100}
    resp = httpx.Response(200, content=b"x" * 100)
    assert _is_baseline_match(resp, base) is False


def test_baseline_match_fingerprint_match_means_match() -> None:
    body = b"redirect to home" * 100
    fp = _body_fingerprint(body)
    base = {"ok": True, "codes": {307}, "fps": {fp}, "size": len(body)}
    resp = httpx.Response(307, content=body)
    assert _is_baseline_match(resp, base) is True


def test_baseline_match_size_within_32_bytes_means_match() -> None:
    base = {"ok": True, "codes": {307}, "fps": {"deadbeef"}, "size": 100}
    resp = httpx.Response(307, content=b"x" * 110)  # diff 10 bytes < 32
    assert _is_baseline_match(resp, base) is True


def test_baseline_match_failed_baseline_skips_filter() -> None:
    base = {"ok": False, "codes": set(), "fps": set(), "size": None}
    resp = httpx.Response(200, content=b"x")
    assert _is_baseline_match(resp, base) is False


# ─── 端到端：dir_bruteforce 集成（用 httpx.MockTransport） ────────────────


def _patch_client_with(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    """把 tools.recon 里的 httpx.AsyncClient 替换成自带 MockTransport 的版本。"""
    real = httpx.AsyncClient

    def _factory(*args, **kw):  # type: ignore[no-untyped-def]
        kw["transport"] = httpx.MockTransport(handler)
        return real(*args, **kw)

    monkeypatch.setattr("tools.recon.httpx.AsyncClient", _factory)


@pytest.mark.asyncio
async def test_probe_baseline_records_codes_and_fingerprints() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(307, content=b"go home")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        base = await _probe_baseline(client, "https://x.test")
    assert base["ok"] is True
    assert base["codes"] == {307}
    assert len(base["fps"]) == 1


@pytest.mark.asyncio
async def test_dir_bruteforce_vercel_307_no_false_positives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vercel 全 307 站点：所有路径都返回相同的 307 + 相同 body → 应过滤干净。"""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(307, content=b"redirect to /\n", headers={"location": "/"})

    _patch_client_with(monkeypatch, handler)
    out = await dir_bruteforce("https://vercel.test")
    assert "未发现" in out
    assert "全站重定向" in out
    # 确保没把字典里的路径塞进 found
    assert "[307]" not in out


@pytest.mark.asyncio
async def test_dir_bruteforce_all_404_clean_no_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全 404：基线 = {404}，不属于 30x，不该输出"全站重定向"警告。"""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    _patch_client_with(monkeypatch, handler)
    out = await dir_bruteforce("https://normal.test")
    assert "未发现" in out
    assert "全站重定向" not in out


@pytest.mark.asyncio
async def test_dir_bruteforce_real_hit_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """baseline=404，仅 /admin → 200 不同 body，应只报 /admin。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/admin":
            return httpx.Response(200, content=b"<html>admin panel</html>")
        return httpx.Response(404, content=b"not found")

    _patch_client_with(monkeypatch, handler)
    out = await dir_bruteforce("https://target.test")
    assert "/admin" in out
    assert "[200]" in out
    # 别的路径不该混进来
    assert out.count("[200]") == 1


@pytest.mark.asyncio
async def test_dir_bruteforce_200_baseline_with_real_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPA 风格站：baseline=200 hash A，/phpmyadmin 返 200 hash B → 仅报 /phpmyadmin。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/phpmyadmin":
            return httpx.Response(200, content=b"PHPMYADMIN_LOGIN_PAGE_DIFFERENT" * 50)
        return httpx.Response(200, content=b"<html>SPA shell</html>")

    _patch_client_with(monkeypatch, handler)
    out = await dir_bruteforce("https://spa.test")
    assert "/phpmyadmin" in out
    # SPA shell 是 baseline，不该报
    assert out.count("[200]") == 1
