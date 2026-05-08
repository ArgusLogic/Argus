"""审批 UI + engine._ask_approval 集成测试。

prompt_toolkit Application 难以在 pytest 里跑真键盘事件，因此：
  - 直接 mock prompt_for_approval 验证 engine 行为
  - 单测 _fallback_text_prompt 用 monkeypatch 替换 input/stdin
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.approval_ui import (
    ApprovalChoice,
    _fallback_text_prompt,
    _pretty_args,
    _PromptParams,
    _truncate,
)

# ─── 工具函数 ────────────────────────────────────────────────────────────────


def test_pretty_args_formats_json() -> None:
    out = _pretty_args('{"a": 1, "b": [1, 2]}')
    assert "\n" in out
    assert '"a": 1' in out


def test_pretty_args_returns_raw_on_garbage() -> None:
    assert _pretty_args("not json") == "not json"


def test_truncate_one_line_keeps_short() -> None:
    assert _truncate("hello", limit=20) == "hello"


def test_truncate_long_string_clips() -> None:
    out = _truncate("a" * 200, limit=10)
    assert out.endswith("…")
    assert len(out) == 10


def test_truncate_takes_first_line_only() -> None:
    out = _truncate("first\nsecond")
    assert out == "first"


# ─── _fallback_text_prompt（无 TTY 时走的路径） ─────────────────────────────


def test_fallback_default_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_args, **_kw: "")
    p = _PromptParams("test", "subdomain_enum", "{}", "block", "warning")
    assert _fallback_text_prompt(p) == ApprovalChoice.APPROVE


def test_fallback_choice_2_skip_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_args, **_kw: "2")
    p = _PromptParams("test", "subdomain_enum", "{}", "block", "warning")
    assert _fallback_text_prompt(p) == ApprovalChoice.APPROVE_SKIP_SESSION


def test_fallback_choice_3_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_args, **_kw: "3")
    p = _PromptParams("test", "x", "{}", "confirm", None)
    assert _fallback_text_prompt(p) == ApprovalChoice.REJECT


def test_fallback_eof_treated_as_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_eof(*_args, **_kw):  # type: ignore[no-untyped-def]
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    p = _PromptParams("test", "x", "{}", "confirm", None)
    assert _fallback_text_prompt(p) == ApprovalChoice.REJECT


# ─── prompt_for_approval：非 TTY 自动回退 ────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_for_approval_falls_back_when_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest 跑的时候 stdin 一般不是 TTY，应当直接走 fallback。"""
    from agent import approval_ui

    monkeypatch.setattr(approval_ui.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kw: "1")

    out = await approval_ui.prompt_for_approval(
        user_request="hi",
        tool_name="x",
        tool_args="{}",
        risk_level="confirm",
    )
    assert out == ApprovalChoice.APPROVE


# ─── engine._ask_approval 集成 ────────────────────────────────────────────


def _make_engine():  # type: ignore[no-untyped-def]
    from agent.engine import AgentEngine
    from agent.tool_registry import ToolRegistry

    class _Stub:
        model = "mock/m"
        api_keys: dict = {}  # noqa: RUF012

    return AgentEngine(llm=_Stub(), registry=ToolRegistry(), approval_mode=True, verbose=False)


@pytest.mark.asyncio
async def test_ask_approval_approve() -> None:
    engine = _make_engine()
    engine.messages.append({"role": "user", "content": "scan it"})

    with patch(
        "agent.approval_ui.prompt_for_approval",
        new=AsyncMock(return_value=ApprovalChoice.APPROVE),
    ) as mock_prompt:
        approved = await engine._ask_approval("subdomain_enum", '{"d": "x"}', "block")
    assert approved is True
    assert mock_prompt.await_count == 1
    # 没加进 skip 集合
    assert "subdomain_enum" not in engine._session_approval_skips


@pytest.mark.asyncio
async def test_ask_approval_reject() -> None:
    engine = _make_engine()
    engine.messages.append({"role": "user", "content": "scan it"})

    with patch(
        "agent.approval_ui.prompt_for_approval",
        new=AsyncMock(return_value=ApprovalChoice.REJECT),
    ):
        approved = await engine._ask_approval("subdomain_enum", '{"d": "x"}', "block")
    assert approved is False
    assert "subdomain_enum" not in engine._session_approval_skips


@pytest.mark.asyncio
async def test_ask_approval_skip_session_then_silent_pass() -> None:
    """选了 skip-session 后，第二次同名工具不再调 prompt_for_approval。"""
    engine = _make_engine()
    engine.messages.append({"role": "user", "content": "scan it"})

    mock = AsyncMock(return_value=ApprovalChoice.APPROVE_SKIP_SESSION)
    with patch("agent.approval_ui.prompt_for_approval", new=mock):
        first = await engine._ask_approval("subdomain_enum", '{"d": "x"}', "block")
        second = await engine._ask_approval("subdomain_enum", '{"d": "y"}', "block")
        third = await engine._ask_approval("subdomain_enum", '{"d": "z"}', "block")

    assert first is True
    assert second is True
    assert third is True
    # 第一次后就 cache 住了，prompt 只该被调一次
    assert mock.await_count == 1
    assert "subdomain_enum" in engine._session_approval_skips


@pytest.mark.asyncio
async def test_ask_approval_skip_does_not_leak_across_tools() -> None:
    """skip subdomain_enum 不该影响 port_scan 的审批。"""
    engine = _make_engine()
    engine.messages.append({"role": "user", "content": "scan it"})

    seq = [ApprovalChoice.APPROVE_SKIP_SESSION, ApprovalChoice.REJECT]
    mock = AsyncMock(side_effect=seq)
    with patch("agent.approval_ui.prompt_for_approval", new=mock):
        a = await engine._ask_approval("subdomain_enum", "{}", "block")
        b = await engine._ask_approval("port_scan", "{}", "block")

    assert a is True  # subdomain_enum skip session
    assert b is False  # port_scan 仍被询问且被拒
    assert mock.await_count == 2
    assert engine._session_approval_skips == {"subdomain_enum"}
