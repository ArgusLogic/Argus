"""ESC 中断监听 + run_stream 取消行为测试。"""

from __future__ import annotations

import asyncio

import pytest

from utils.interrupt import EscInterruptListener

pytestmark = pytest.mark.asyncio


# ─── EscInterruptListener ───────────────────────────────────────────────────


async def test_listener_fires_callback_via_inject() -> None:
    """单测不能依赖真实键盘，用 _inject_for_test 模拟。"""
    fired = asyncio.Event()
    listener = EscInterruptListener(on_press=fired.set)
    listener._inject_for_test()
    assert listener.triggered
    assert fired.is_set()


async def test_listener_only_fires_once() -> None:
    count = {"n": 0}

    def cb() -> None:
        count["n"] += 1

    listener = EscInterruptListener(on_press=cb)
    listener._inject_for_test()
    listener._inject_for_test()
    listener._inject_for_test()
    assert count["n"] == 1


async def test_listener_start_noop_when_stdin_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 TTY（如 CI/pytest）下 start() 不开线程，避免阻塞。"""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    listener = EscInterruptListener(on_press=lambda: None)
    listener.start()
    assert listener._thread is None  # 没起线程
    listener.stop()  # no-op


async def test_listener_stop_idempotent() -> None:
    listener = EscInterruptListener(on_press=lambda: None)
    listener.stop()
    listener.stop()  # 不应抛


async def test_listener_callback_exception_swallowed() -> None:
    """on_press 抛异常不能炸到调用方。"""

    def boom() -> None:
        raise RuntimeError("oops")

    listener = EscInterruptListener(on_press=boom)
    # 不应抛
    listener._inject_for_test()
    assert listener.triggered


# ─── 集成：run_with_esc_interrupt 取消逻辑 ──────────────────────────────────


async def test_run_with_esc_interrupt_completes_normally() -> None:
    """没按 ESC 时正常返回结果。"""
    from utils.interrupt import run_with_esc_interrupt

    async def task() -> str:
        await asyncio.sleep(0.01)
        return "done"

    result, cancelled = await run_with_esc_interrupt(task)
    assert result == "done"
    assert cancelled is False


# ─── engine.run_stream 取消行为 ──────────────────────────────────────────────


async def test_run_stream_cancel_keeps_messages_consistent() -> None:
    """取消正在跑的 run_stream 后，messages 应保持 user→assistant 配对一致。"""
    from agent.engine import AgentEngine
    from agent.tool_registry import ToolRegistry

    class _StallingLLM:
        model = "mock/model"
        api_keys: dict = {}  # noqa: RUF012  (类只在测试里实例化一次)

        async def chat_stream_events(self, messages, tools=None):  # type: ignore[no-untyped-def]
            # 一直挂着，直到被 cancel
            await asyncio.sleep(60)
            yield  # never reached

        async def chat(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    engine = AgentEngine(
        llm=_StallingLLM(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        approval_mode=False,
        verbose=False,
    )

    task = asyncio.create_task(engine.run_stream("ping", ui=None))
    await asyncio.sleep(0.05)  # 让任务进入 stream loop
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # messages 应以 user 开头并补了占位 assistant
    roles = [m["role"] for m in engine.messages]
    # 典型形态: [system, user, assistant("[用户按 ESC 中断]")]
    assert roles[-2:] == ["user", "assistant"]
    assert "中断" in engine.messages[-1]["content"]
