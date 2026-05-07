"""A3 — 失败学习启发式提取 + LESSONS.md 入库测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.lessons import _classify, _extract_target, extract_lessons
from agent.memory_md import MemoryMD


def _assistant_call(tcid: str, tool: str, args: str = "{}") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tcid,
                "type": "function",
                "function": {"name": tool, "arguments": args},
            }
        ],
    }


def _tool_result(tcid: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tcid, "content": content}


# ─── _classify ───────────────────────────────────────────────────────────────


class TestClassify:
    def test_403(self) -> None:
        assert _classify("status_code: 403, forbidden") == "403 Forbidden"

    def test_rate_limit(self) -> None:
        assert _classify("HTTP 429 Too Many Requests") == "限流 429"

    def test_timeout(self) -> None:
        assert _classify("工具执行超时") == "超时"

    def test_waf(self) -> None:
        assert _classify("blocked by Cloudflare WAF") == "WAF 拦截"

    def test_captcha(self) -> None:
        assert _classify("Please complete the reCAPTCHA challenge") == "Captcha 验证"

    def test_no_match(self) -> None:
        assert _classify("成功获取页面内容") == ""

    def test_empty(self) -> None:
        assert _classify("") == ""


# ─── _extract_target ─────────────────────────────────────────────────────────


class TestExtractTarget:
    def test_url(self) -> None:
        assert _extract_target('{"url": "https://example.com/path"}') == "example.com"

    def test_domain(self) -> None:
        assert _extract_target('{"domain": "Example.COM"}') == "example.com"

    def test_invalid_json_returns_empty(self) -> None:
        assert _extract_target("not json") == ""

    def test_no_target_key_returns_empty(self) -> None:
        assert _extract_target('{"other": "val"}') == ""


# ─── extract_lessons ────────────────────────────────────────────────────────


class TestExtractLessons:
    def test_single_failure_produces_lesson(self) -> None:
        msgs = [
            _assistant_call("tc0", "subdomain_enum", '{"domain": "example.com"}'),
            _tool_result("tc0", "blocked by Cloudflare WAF"),
        ]
        lessons = extract_lessons(msgs)
        assert len(lessons) == 1
        assert "subdomain_enum" in lessons[0]
        assert "example.com" in lessons[0]
        assert "WAF 拦截" in lessons[0]

    def test_dedup_same_triple_within_turn(self) -> None:
        msgs = [
            _assistant_call("tc0", "http_request", '{"url": "https://x.com/a"}'),
            _tool_result("tc0", "HTTP 403 Forbidden"),
            _assistant_call("tc1", "http_request", '{"url": "https://x.com/b"}'),
            _tool_result("tc1", "status 403, Forbidden"),
        ]
        lessons = extract_lessons(msgs)
        # 同一 (tool, target=x.com, label=403) → 只 1 条
        assert len(lessons) == 1

    def test_no_failure_no_lesson(self) -> None:
        msgs = [
            _assistant_call("tc0", "browser_navigate", '{"url": "https://ok.com"}'),
            _tool_result("tc0", "状态码: 200 | 标题: OK"),
        ]
        assert extract_lessons(msgs) == []

    def test_multiple_distinct_failures(self) -> None:
        msgs = [
            _assistant_call("tc0", "subdomain_enum", '{"domain": "a.com"}'),
            _tool_result("tc0", "blocked by WAF"),
            _assistant_call("tc1", "port_scan", '{"target": "b.com"}'),
            _tool_result("tc1", "执行超时"),
        ]
        lessons = extract_lessons(msgs)
        assert len(lessons) == 2

    def test_unknown_target(self) -> None:
        msgs = [
            _assistant_call("tc0", "delegate_subagents", "{}"),
            _tool_result("tc0", "执行超时"),
        ]
        lessons = extract_lessons(msgs)
        assert len(lessons) == 1
        assert "(unknown)" in lessons[0]


# ─── MemoryMD.append_lesson ─────────────────────────────────────────────────


class TestAppendLesson:
    @pytest.fixture
    def memory_md(self, _isolate_argus_home: Path) -> MemoryMD:
        return MemoryMD()

    def test_append_writes_to_lessons_md(self, memory_md: MemoryMD) -> None:
        res = memory_md.append_lesson("[2026-05] x on y.com → WAF")
        assert res["ok"] is True
        entries = memory_md.list_entries("lessons")
        assert entries == ["[2026-05] x on y.com → WAF"]

    def test_dedup(self, memory_md: MemoryMD) -> None:
        memory_md.append_lesson("same lesson")
        res = memory_md.append_lesson("same lesson")
        assert res["ok"] is False
        assert res["msg"] == "duplicate"
        assert len(memory_md.list_entries("lessons")) == 1

    def test_fifo_eviction_on_max_entries(self, memory_md: MemoryMD) -> None:
        # 设 max=3，写 5 条 → 留下后 3 条
        for i in range(5):
            memory_md.append_lesson(f"lesson {i}", max_entries=3)
        entries = memory_md.list_entries("lessons")
        assert entries == ["lesson 2", "lesson 3", "lesson 4"]

    def test_render_block_includes_label(self, memory_md: MemoryMD) -> None:
        memory_md.append_lesson("[2026-05] tool on x.com → 失败")
        block = memory_md.render_block("lessons")
        assert "LESSONS" in block
        assert "[2026-05] tool on x.com → 失败" in block

    def test_empty_lessons_render_returns_empty_marker(self, memory_md: MemoryMD) -> None:
        block = memory_md.render_block("lessons")
        assert "(空)" in block
