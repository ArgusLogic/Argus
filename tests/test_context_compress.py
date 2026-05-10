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


# ─── Bug 6 (Coco 报告): 全 tool 极端场景强制截断 ────────────────────────────


async def test_compress_all_tool_messages_forces_truncate() -> None:
    """极端场景：non_system 消息全是 tool 角色 → 之前直接 return 不压缩，
    长会话 token 溢出。修复后应强制截断到最近 keep_recent 条。"""
    cm = ContextManager(max_tokens=100, compress_threshold=0.1)

    # 50 条全 tool 消息（极端模拟，比如 LLM 输出全是 tool_calls 没 content）
    msgs: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(50):
        msgs.append({"role": "tool", "tool_call_id": f"tc{i}", "content": f"r{i}"})

    out = await cm.compress(msgs)

    # 1) 必须真的有压缩（不是原样返回）
    assert len(out) < len(msgs), "极端场景应强制截断而非不压缩"
    # 2) 截断标记存在
    assert any("强制截断" in (m.get("content") or "") for m in out), "应有强制截断摘要消息"
    # 3) tool_call_id 边界仍然合法：开头不能是孤立 tool（无 assistant 前驱）
    #    我们的修复策略是直接丢弃开头 tool 边界
    non_sys = [m for m in out if m.get("role") != "system"]
    if non_sys and non_sys[0].get("role") == "tool":
        raise AssertionError("强制截断后第一条 non-system 不应是孤立 tool 消息")


async def test_compress_all_tool_short_no_force() -> None:
    """tool 消息但条数 ≤ keep_recent 时不应触发强制截断（保持原样）。"""
    cm = ContextManager(max_tokens=100, compress_threshold=0.1)
    msgs: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(3):  # ≤ keep_recent=6
        msgs.append({"role": "tool", "tool_call_id": f"tc{i}", "content": f"r{i}"})
    out = await cm.compress(msgs)
    assert out == msgs, "短消息列表应原样返回，不强制截断"
