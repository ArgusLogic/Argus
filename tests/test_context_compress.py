"""issue #3.5 — context.ContextManager.compress 边界保护：不切断 tool_calls/tool 对。"""

from __future__ import annotations

import pytest

from agent.context import ContextManager

pytestmark = pytest.mark.asyncio


def _msg_assistant_with_tool_call(tc_id: str, content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}],
    }


def _msg_tool(tc_id: str, content: str = "result") -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


async def test_compress_does_not_split_tool_pair() -> None:
    """边界落在 tool 上时应推后，避免 recent_msgs 以孤立 tool 开头。"""
    cm = ContextManager(max_tokens=100, compress_threshold=0.1)
    # 14 条消息：足够多；若默认切到 -6，会落在某个 tool 上。
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(8):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append(_msg_assistant_with_tool_call(f"tc{i}"))
        msgs.append(_msg_tool(f"tc{i}", f"r{i}"))
    out = await cm.compress(msgs)

    # 关键不变量：任何 tool 消息的前一条必须是 assistant（带 tool_calls）
    for i, m in enumerate(out):
        if m.get("role") == "tool":
            assert i > 0
            prev = out[i - 1]
            assert prev.get("role") == "assistant"
            tc_ids = [tc["id"] for tc in prev.get("tool_calls", [])]
            assert m["tool_call_id"] in tc_ids, (
                f"tool_call_id {m['tool_call_id']} 找不到对应 assistant tool_calls: {tc_ids}"
            )


async def test_compress_returns_unchanged_when_too_short() -> None:
    cm = ContextManager(max_tokens=100, compress_threshold=0.1)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]
    out = await cm.compress(msgs)
    assert out == msgs


async def test_compress_with_no_llm_falls_back_to_simple_summarize() -> None:
    """无 LLM 时应回退简单截断而非崩溃。"""
    cm = ContextManager(max_tokens=100, compress_threshold=0.1)
    # 不调 set_llm
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(20):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    out = await cm.compress(msgs)
    assert any("摘要" in (m.get("content") or "") for m in out)
