"""C1 — 跨会话趋势报表（/insights 命令）。

零 LLM 调用：纯 SQLite 统计。

汇总：
- 时间窗内的会话数 + 消息数
- 工具调用 top-N + 命中率（基于 tool 结果有无失败前缀）
- 每日趋势线（可选）

输出 Rich Table；可附加 markdown 导出。
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import aiosqlite

from utils.paths import DB_PATH

# 与 lessons.py 保持一致的失败标记
_FAILURE_KEYWORDS = (
    "执行失败",
    "执行超时",
    "操作被拒绝",
    "工具未注册",
    "保存失败",
    "读取失败",
)


def _looks_failed(content: str) -> bool:
    if not content:
        return False
    head = content[:120]
    return any(kw in head for kw in _FAILURE_KEYWORDS)


@dataclass
class InsightsReport:
    """C1 报告结构。"""

    days: int = 7
    since: str = ""
    session_count: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    tool_hits: Counter = field(default_factory=Counter)
    tool_failures: Counter = field(default_factory=Counter)

    def hit_rate(self, tool_name: str) -> float:
        total = self.tool_hits.get(tool_name, 0)
        if not total:
            return 0.0
        fail = self.tool_failures.get(tool_name, 0)
        return round((total - fail) / total * 100, 1)

    def top_tools(self, limit: int = 10) -> list[tuple[str, int, int, float]]:
        """[(tool, total, fail, success_rate%)] 按总调用次降序。"""
        rows = []
        for name, total in self.tool_hits.most_common(limit):
            fail = self.tool_failures.get(name, 0)
            rate = self.hit_rate(name)
            rows.append((name, total, fail, rate))
        return rows


async def collect_insights(days: int = 7, db_path: str | None = None) -> InsightsReport:
    """聚合最近 days 天的会话数据。db_path 仅用于测试注入。"""
    path = db_path or DB_PATH
    since_dt = datetime.now() - timedelta(days=days)
    since_iso = since_dt.isoformat()

    report = InsightsReport(days=days, since=since_iso)

    try:
        db = await aiosqlite.connect(path)
    except Exception:
        return report

    try:
        # session_count
        try:
            cur = await db.execute("SELECT COUNT(*) FROM sessions WHERE updated_at >= ?", (since_iso,))
            row = await cur.fetchone()
            report.session_count = (row[0] if row else 0) or 0
        except Exception:
            # 表不存在或其它错误 → 当作空数据
            return report

        # session_count==0 时仍可能 messages 表有内容；按 session_name in 时间窗筛选
        try:
            cur = await db.execute(
                """
                SELECT m.role, m.content, m.tool_call_id, m.tool_calls
                  FROM messages m
                  JOIN sessions s ON s.name = m.session_name
                 WHERE s.updated_at >= ?
                 ORDER BY m.id
                """,
                (since_iso,),
            )
            rows = list(await cur.fetchall())
        except Exception:
            return report
        report.message_count = len(rows)

        # 配对：assistant 的 tool_calls → 后续 tool 消息（按 tool_call_id 索引）
        pending_tool: dict[str, str] = {}  # tool_call_id → tool_name
        for role, content, tool_call_id, tool_calls_json in rows:
            if role == "assistant" and tool_calls_json:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    tcs: Any = json.loads(tool_calls_json)
                    if isinstance(tcs, list):
                        for tc in tcs:
                            tcid = tc.get("id", "")
                            tname = (tc.get("function") or {}).get("name", "")
                            if tcid and tname:
                                pending_tool[tcid] = tname
                                report.tool_hits[tname] += 1
                                report.tool_call_count += 1
            elif role == "tool" and tool_call_id and tool_call_id in pending_tool:
                tname = pending_tool[tool_call_id]
                if _looks_failed(content or ""):
                    report.tool_failures[tname] += 1
    finally:
        await db.close()

    return report


def render_table(report: InsightsReport) -> Any:
    """Rich Table 渲染器。返回一个 rich.table.Table 实例。"""
    from rich.table import Table

    table = Table(
        title=f"📊 Argus Insights — last {report.days} days",
        title_style="bold cyan",
    )
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("Calls", justify="right")
    table.add_column("Failures", justify="right", style="red")
    table.add_column("Success %", justify="right", style="green")

    for tool, total, fail, rate in report.top_tools(limit=15):
        table.add_row(tool, str(total), str(fail), f"{rate:.1f}%")
    return table


def render_markdown(report: InsightsReport) -> str:
    """生成 markdown 报告（可保存到文件）。"""
    lines = [
        f"# Argus Insights — last {report.days} days",
        "",
        f"- since: {report.since}",
        f"- sessions: {report.session_count}",
        f"- messages: {report.message_count}",
        f"- tool calls: {report.tool_call_count}",
        "",
        "## Top Tools",
        "",
        "| Tool | Calls | Failures | Success % |",
        "|---|---:|---:|---:|",
    ]
    for tool, total, fail, rate in report.top_tools(limit=20):
        lines.append(f"| {tool} | {total} | {fail} | {rate:.1f}% |")
    if report.tool_call_count == 0:
        lines.append("\n> 时间窗内无工具调用记录。")
    return "\n".join(lines)
