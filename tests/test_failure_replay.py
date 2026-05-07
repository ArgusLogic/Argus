"""C2 — failure_log 结构化失败请求记录测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent.failure_log import (
    MAX_ENTRIES,
    _path,
    append_failure,
    extract_and_log_failures,
    load_failures,
    query_by_target,
    render_block_for_target,
)


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


# ─── append_failure / load_failures ─────────────────────────────────────────


class TestAppendAndLoad:
    def test_append_creates_jsonl(self, _isolate_argus_home: Path) -> None:
        append_failure("dns_lookup", "example.com", "403 Forbidden", excerpt="x")
        path = _path()
        assert os.path.exists(path)
        rows = load_failures()
        assert len(rows) == 1
        assert rows[0]["tool"] == "dns_lookup"
        assert rows[0]["target"] == "example.com"
        assert rows[0]["label"] == "403 Forbidden"

    def test_skips_when_label_or_tool_empty(self, _isolate_argus_home: Path) -> None:
        append_failure("", "x.com", "403")
        append_failure("dns_lookup", "x.com", "")
        assert load_failures() == []

    def test_args_can_be_dict(self, _isolate_argus_home: Path) -> None:
        append_failure("browser_navigate", "y.com", "WAF", args={"url": "https://y.com"})
        rows = load_failures()
        # args 字段应是 JSON 字符串
        args = json.loads(rows[0]["args"])
        assert args == {"url": "https://y.com"}

    def test_excerpt_truncation(self, _isolate_argus_home: Path) -> None:
        long = "x" * 1000
        append_failure("t", "z.com", "超时", excerpt=long)
        rows = load_failures()
        assert len(rows[0]["excerpt"]) == 200


# ─── FIFO rotation ──────────────────────────────────────────────────────────


class TestRotation:
    def test_rotates_when_exceeds_max(
        self, _isolate_argus_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("agent.failure_log.MAX_ENTRIES", 5)
        for i in range(8):
            append_failure(f"tool_{i}", "x.com", "超时")
        rows = load_failures()
        assert len(rows) == 5
        # 应保留最后 5 条（tool_3 .. tool_7）
        assert rows[0]["tool"] == "tool_3"
        assert rows[-1]["tool"] == "tool_7"


# ─── query_by_target / render_block_for_target ──────────────────────────────


class TestQuery:
    def test_filter_by_target(self, _isolate_argus_home: Path) -> None:
        append_failure("a", "alpha.com", "403")
        append_failure("b", "beta.com", "429")
        append_failure("c", "alpha.com", "WAF 拦截")

        rows = query_by_target("alpha.com")
        assert len(rows) == 2
        assert rows[0]["label"] == "WAF 拦截"  # 最新优先

    def test_case_insensitive_target(self, _isolate_argus_home: Path) -> None:
        append_failure("a", "alpha.com", "403")
        rows = query_by_target("Alpha.COM")
        assert len(rows) == 1

    def test_empty_target_returns_empty(self, _isolate_argus_home: Path) -> None:
        append_failure("a", "alpha.com", "403")
        assert query_by_target("") == []

    def test_render_block_empty_when_no_match(self, _isolate_argus_home: Path) -> None:
        assert render_block_for_target("nope.com") == ""

    def test_render_block_includes_entries(self, _isolate_argus_home: Path) -> None:
        append_failure("subdomain_enum", "x.com", "WAF 拦截")
        block = render_block_for_target("x.com")
        assert "FAILURE REPLAYS for x.com" in block
        assert "subdomain_enum" in block
        assert "WAF 拦截" in block


# ─── extract_and_log_failures (engine hook) ─────────────────────────────────


class TestExtractAndLog:
    def test_extracts_failures_from_messages(self, _isolate_argus_home: Path) -> None:
        msgs = [
            _assistant_call("tc0", "subdomain_enum", '{"domain": "z.com"}'),
            _tool_result("tc0", "blocked by Cloudflare WAF"),
            _assistant_call("tc1", "browser_navigate", '{"url": "https://ok.com"}'),
            _tool_result("tc1", "状态码: 200 | 标题: OK"),
        ]
        n = extract_and_log_failures(msgs)
        assert n == 1
        rows = load_failures()
        assert len(rows) == 1
        assert rows[0]["tool"] == "subdomain_enum"
        assert rows[0]["target"] == "z.com"

    def test_no_failures_no_writes(self, _isolate_argus_home: Path) -> None:
        msgs = [
            _assistant_call("tc0", "browser_navigate", '{"url": "https://ok.com"}'),
            _tool_result("tc0", "状态码: 200 | 标题: OK"),
        ]
        assert extract_and_log_failures(msgs) == 0
        assert load_failures() == []

    def test_no_dedup_within_turn(self, _isolate_argus_home: Path) -> None:
        # C2 与 A3 不同：每条失败都记一次，不去重
        msgs = [
            _assistant_call("tc0", "http_request", '{"url": "https://x.com/a"}'),
            _tool_result("tc0", "HTTP 403 Forbidden"),
            _assistant_call("tc1", "http_request", '{"url": "https://x.com/b"}'),
            _tool_result("tc1", "status 403, Forbidden"),
        ]
        n = extract_and_log_failures(msgs)
        assert n == 2
