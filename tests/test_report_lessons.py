"""Day2-3: LESSONS 选取 + generate_report 集成测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _write_lessons(content: str) -> None:
    from utils.paths import LESSONS_MD_PATH

    Path(LESSONS_MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(LESSONS_MD_PATH).write_text("# Lessons Learned\n\n" + content, encoding="utf-8")


def test_extract_keywords_root_domain() -> None:
    from tools._report_lessons import _extract_keywords

    kws = _extract_keywords("https://api.example.com/path")
    assert "api.example.com" in kws
    assert "example.com" in kws
    assert "com" in kws


def test_select_relevant_lessons_finds_target_match(tmp_path: Path) -> None:
    """LESSONS 中含目标域 → 应被命中并排在前。"""
    from tools._report_lessons import select_relevant_lessons
    from utils.paths import LESSONS_MD_PATH

    sep = "§"
    lessons_text = f"对 example.com 的 dir_bruteforce 容易触发 Cloudflare 限流{sep}通用：whois RDAP 对子域要回退父域{sep}ftp 端口扫描经常 timeout"
    _write_lessons(lessons_text)

    out = select_relevant_lessons("example.com", top_n=3)
    assert any("example.com" in s for s in out)


def test_select_relevant_lessons_no_match_returns_empty() -> None:
    sep = "§"
    _write_lessons(f"some lesson about foo.org{sep}另一个 bar.net 的教训")
    from tools._report_lessons import select_relevant_lessons

    out = select_relevant_lessons("xyz123notfound.local", top_n=3)
    assert out == []


def test_select_relevant_lessons_no_file_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """LESSONS.md 不存在 → 返空，无异常。"""
    fake_path = tmp_path / "no_such_lessons.md"
    # _report_lessons 在运行时通过 utils.paths.LESSONS_MD_PATH 解析；patch 这里
    monkeypatch.setattr("utils.paths.LESSONS_MD_PATH", str(fake_path))
    from tools._report_lessons import select_relevant_lessons

    assert select_relevant_lessons("any.com") == []


def test_render_lessons_block_format() -> None:
    sep = "§"
    _write_lessons(f"对 example.com 不要硬扫 /admin/{sep}example.com 的 robots.txt 经常 404")
    from tools._report_lessons import render_lessons_block

    out = render_lessons_block("example.com", top_n=2)
    assert "💡 本次命中的避坑教训" in out
    assert "1." in out and "2." in out
    assert "example.com" in out


def test_render_empty_when_no_match() -> None:
    sep = "§"
    _write_lessons(f"foo.org 教训{sep}bar.net 教训")
    from tools._report_lessons import render_lessons_block

    out = render_lessons_block("xyz.unknown")
    assert out == ""


# ──────────────────────────────────────────────────────────────────────────
# generate_report 集成
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_report_includes_top3_summary() -> None:
    """报告应包含 Top-3 摘要（注入触发风险的 headers/dirs）。"""
    from tools.report import generate_report

    result = await generate_report(
        target="example.com",
        summary="测试报告",
        headers="✗ HSTS — 缺失\n安全头评分: 0/10",
        directories="  [200] /.git/config  (123 bytes)",
    )

    assert "报告已生成" in result
    file_path = result.split(": ")[1].split(" (")[0]
    content = Path(file_path).read_text(encoding="utf-8")
    assert "🎯 执行摘要" in content
    assert ".git" in content
    assert "立即" in content


@pytest.mark.asyncio
async def test_generate_report_includes_topology_when_dns_present() -> None:
    from tools.report import generate_report

    result = await generate_report(
        target="example.com",
        summary="x",
        dns_info="A: 1.2.3.4\nNS: ns.example.com",
        open_ports="80/tcp open\n443/tcp open",
    )
    file_path = result.split(": ")[1].split(" (")[0]
    content = Path(file_path).read_text(encoding="utf-8")
    assert "🌐 拓扑" in content
    assert "1.2.3.4" in content


@pytest.mark.asyncio
async def test_generate_report_lessons_block_when_match() -> None:
    from tools.report import generate_report

    sep = "§"
    _write_lessons(
        f"对 example.com 的扫描容易遇到 Cloudflare 限流{sep}example.com 走 wildcard DNS"
    )
    result = await generate_report(target="example.com", summary="x")
    file_path = result.split(": ")[1].split(" (")[0]
    content = Path(file_path).read_text(encoding="utf-8")
    assert "💡 本次命中的避坑教训" in content


@pytest.mark.asyncio
async def test_generate_report_no_signals_no_summary_block() -> None:
    """无任何风险信号时不应出现执行摘要 section（避免空标题）。"""
    from tools.report import generate_report

    result = await generate_report(target="cleansite.local", summary="干净的报告")
    file_path = result.split(": ")[1].split(" (")[0]
    content = Path(file_path).read_text(encoding="utf-8")
    assert "🎯 执行摘要" not in content
    assert "🌐 拓扑" not in content
