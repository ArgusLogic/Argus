"""crawl_js_endpoints 正则覆盖测试（A1）。

验证：
1. 所有 7 个模式都能命中
2. 启发式过滤剔除 CSS/图片/根路径
3. 真实 fixture (超星类) 至少抓到 10 个端点
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.crawler import (
    _AJAX_CALL_RE,
    _AJAX_OPTS_URL_RE,
    _API_PATH_RE,
    _BROAD_PATH_RE,
    _FULL_URL_RE,
    _SENSITIVE_RE,
    _TEMPLATE_URL_RE,
    _is_likely_endpoint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_chaoxing.js"


@pytest.fixture
def sample_js() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class TestFullUrlRe:
    def test_https_with_path(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _FULL_URL_RE.finditer(sample_js)}
        assert "https://api.chaoxing.com" in urls
        assert "https://passport.chaoxing.com/login" in urls
        assert "https://cdn.example.com/static/main.js" in urls


class TestApiPathRe:
    def test_high_confidence_prefixes(self, sample_js: str) -> None:
        paths = {m.group(1) for m in _API_PATH_RE.finditer(sample_js)}
        assert "/mooc2-ans/ai-evaluate/v2/answer/init" in paths
        assert "/mooc2-ans/ai-evaluate/v2/answer/load-data" in paths
        assert "/mooc2-ans/ai-evaluate/v2/answer/submit" in paths
        assert "/api/v2/review/modify-eva" in paths
        assert "/auth/login" in paths


class TestBroadPathRe:
    def test_generic_paths(self, sample_js: str) -> None:
        paths = {m.group(1) for m in _BROAD_PATH_RE.finditer(sample_js)}
        assert "/student/course/detail" in paths
        assert "/business/report/export" in paths


class TestTemplateUrlRe:
    def test_template_with_var(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _TEMPLATE_URL_RE.finditer(sample_js)}
        # 含 ${id} 的模板
        assert any("/think/topic/" in u and "${id}" in u for u in urls)
        assert "/ai-ans/ai-evaluate/think/main-talk" in urls


class TestAjaxCallRe:
    def test_fetch(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _AJAX_CALL_RE.finditer(sample_js)}
        assert "/topic-map-data" in urls

    def test_axios_get(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _AJAX_CALL_RE.finditer(sample_js)}
        assert "/answer-topic-stat" in urls

    def test_event_source(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _AJAX_CALL_RE.finditer(sample_js)}
        assert "/think/tip-question" in urls

    def test_jquery_ajax(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _AJAX_CALL_RE.finditer(sample_js)}
        assert "/think/end-report" in urls


class TestAjaxOptsUrlRe:
    def test_url_in_options(self, sample_js: str) -> None:
        urls = {m.group(1) for m in _AJAX_OPTS_URL_RE.finditer(sample_js)}
        assert "/think/change-question" in urls
        assert "/exam/result/save" in urls


class TestSensitiveRe:
    def test_finds_secrets(self, sample_js: str) -> None:
        secrets = [m.group(1) for m in _SENSITIVE_RE.finditer(sample_js)]
        assert "abc123def456ghi789" in secrets
        assert "supersecretvalue123" in secrets
        # JWT 也应被捕获（作为 token 值）
        assert any("eyJhbGc" in s for s in secrets)


class TestHeuristicFilter:
    def test_rejects_css(self) -> None:
        assert not _is_likely_endpoint("/static/main.css")

    def test_rejects_images(self) -> None:
        assert not _is_likely_endpoint("/img/logo.png")
        assert not _is_likely_endpoint("/icon.svg")

    def test_rejects_fonts(self) -> None:
        assert not _is_likely_endpoint("/fonts/icon.woff2")

    def test_rejects_root_and_dots(self) -> None:
        assert not _is_likely_endpoint("/")
        assert not _is_likely_endpoint("/.")
        assert not _is_likely_endpoint("/..")

    def test_rejects_too_short(self) -> None:
        assert not _is_likely_endpoint("/a")
        assert not _is_likely_endpoint("/ab")

    def test_rejects_with_whitespace(self) -> None:
        assert not _is_likely_endpoint("/path with space")
        assert not _is_likely_endpoint("/foo\n/bar")

    def test_accepts_real_endpoints(self) -> None:
        assert _is_likely_endpoint("/api/v1/users")
        assert _is_likely_endpoint("/mooc2-ans/answer/init")
        assert _is_likely_endpoint("/student/course/detail")


class TestEndpointCountBaseline:
    """整体 baseline：fixture 至少应被抓到 N 个端点。"""

    def test_minimum_endpoints_extracted(self, sample_js: str) -> None:
        all_paths = set()
        for regex in (_API_PATH_RE, _BROAD_PATH_RE, _AJAX_CALL_RE, _AJAX_OPTS_URL_RE):
            for m in regex.finditer(sample_js):
                p = m.group(1)
                if _is_likely_endpoint(p):
                    all_paths.add(p)
        # 模板 URL 单独算
        for m in _TEMPLATE_URL_RE.finditer(sample_js):
            p = m.group(1)
            if _is_likely_endpoint(p):
                all_paths.add(p)

        # 至少应抓到这些端点（已验证过应该存在的）
        assert len(all_paths) >= 12, f"baseline 失守，仅抓到 {len(all_paths)} 个: {all_paths}"

        # 关键端点必须命中（覆盖 fixture 中的真实业务）
        critical = [
            "/mooc2-ans/ai-evaluate/v2/answer/init",
            "/mooc2-ans/ai-evaluate/v2/answer/submit",
            "/think/end-report",
            "/think/change-question",
            "/topic-map-data",
            "/exam/result/save",
        ]
        for c in critical:
            assert c in all_paths, f"关键端点缺失: {c}"

    def test_no_false_positive_on_static_assets(self, sample_js: str) -> None:
        """确保过滤器拦下了 CSS/图片/字体。"""
        all_paths = set()
        for regex in (_API_PATH_RE, _BROAD_PATH_RE):
            for m in regex.finditer(sample_js):
                p = m.group(1)
                if _is_likely_endpoint(p):
                    all_paths.add(p)

        for asset in ("/static/main.css", "/img/logo.png", "/fonts/icon.woff2"):
            assert asset not in all_paths, f"误抓静态资源: {asset}"
