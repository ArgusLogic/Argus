"""C1 — /insights 跨会话趋势报表测试。"""

from __future__ import annotations

import json

import aiosqlite
import pytest

from agent.insights import (
    InsightsReport,
    _looks_failed,
    collect_insights,
    render_markdown,
    render_table,
)

# ─── _looks_failed ──────────────────────────────────────────────────────────


class TestLooksFailed:
    def test_explicit_failure(self) -> None:
        assert _looks_failed("工具执行失败：超时") is True

    def test_timeout(self) -> None:
        assert _looks_failed("工具执行超时") is True

    def test_normal_result(self) -> None:
        assert _looks_failed("状态码: 200 | 标题: OK") is False

    def test_empty(self) -> None:
        assert _looks_failed("") is False


# ─── InsightsReport.hit_rate / top_tools ────────────────────────────────────


class TestReportShape:
    def test_hit_rate_no_calls(self) -> None:
        r = InsightsReport()
        assert r.hit_rate("nope") == 0.0

    def test_hit_rate_basic(self) -> None:
        r = InsightsReport()
        r.tool_hits["a"] = 10
        r.tool_failures["a"] = 2
        assert r.hit_rate("a") == 80.0

    def test_top_tools_sorted_desc(self) -> None:
        r = InsightsReport()
        r.tool_hits["a"] = 5
        r.tool_hits["b"] = 10
        r.tool_failures["b"] = 4
        rows = r.top_tools()
        assert rows[0][0] == "b"  # b 调用更多，排第一
        assert rows[0][2] == 4
        assert rows[0][3] == 60.0


# ─── collect_insights 端到端 ────────────────────────────────────────────────


@pytest.fixture
async def populated_db(tmp_path) -> str:
    """构建一个迷你 sessions DB，含 1 session + assistant tool_calls + tool 结果。"""
    from datetime import datetime

    path = str(tmp_path / "test.db")
    db = await aiosqlite.connect(path)
    await db.execute("""
        CREATE TABLE sessions (
            name TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT NOT NULL,
            idx INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT
        )
    """)
    now = datetime.now().isoformat()
    await db.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        ("s1", now, now, 4),
    )
    tcs = [
        {"id": "tc0", "type": "function", "function": {"name": "dns_lookup", "arguments": "{}"}},
        {"id": "tc1", "type": "function", "function": {"name": "browser_navigate", "arguments": "{}"}},
    ]
    rows = [
        ("s1", 0, "user", "go", "", None),
        ("s1", 1, "assistant", "", "", json.dumps(tcs)),
        ("s1", 2, "tool", "ok dns result", "tc0", None),
        ("s1", 3, "tool", "工具执行超时", "tc1", None),  # 失败
    ]
    for r in rows:
        await db.execute(
            "INSERT INTO messages (session_name, idx, role, content, tool_call_id, tool_calls)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            r,
        )
    await db.commit()
    await db.close()
    return path


class TestCollectInsights:
    @pytest.mark.asyncio
    async def test_no_db_returns_empty_report(self, tmp_path) -> None:
        # 不存在的 DB 路径 → 空 report，不抛异常
        report = await collect_insights(days=7, db_path=str(tmp_path / "missing.db"))
        assert report.session_count == 0
        assert report.tool_call_count == 0

    @pytest.mark.asyncio
    async def test_aggregates_calls_and_failures(self, populated_db: str) -> None:
        report = await collect_insights(days=7, db_path=populated_db)
        assert report.session_count == 1
        assert report.message_count == 4
        assert report.tool_call_count == 2
        assert report.tool_hits["dns_lookup"] == 1
        assert report.tool_hits["browser_navigate"] == 1
        assert report.tool_failures["browser_navigate"] == 1
        assert report.tool_failures.get("dns_lookup", 0) == 0
        assert report.hit_rate("dns_lookup") == 100.0
        assert report.hit_rate("browser_navigate") == 0.0


# ─── render_table / render_markdown ─────────────────────────────────────────


class TestRender:
    def test_markdown_includes_headings(self) -> None:
        r = InsightsReport(days=14)
        r.session_count = 3
        r.message_count = 50
        r.tool_call_count = 12
        r.tool_hits["dns_lookup"] = 12
        md = render_markdown(r)
        assert "# Argus Insights — last 14 days" in md
        assert "dns_lookup" in md
        assert "| Tool |" in md

    def test_markdown_when_empty(self) -> None:
        r = InsightsReport(days=7)
        md = render_markdown(r)
        assert "时间窗内无工具调用记录" in md

    def test_render_table_returns_table(self) -> None:
        r = InsightsReport()
        r.tool_hits["x"] = 5
        table = render_table(r)
        # rich.table.Table 实例
        from rich.table import Table

        assert isinstance(table, Table)
