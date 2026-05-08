"""ESC 中断监听：在 LLM 流式输出 / 工具运行期间监听 ESC，让用户能停下来。

设计要点：
  - **守护线程** + 平台原生 stdin 读取（Windows: msvcrt；POSIX: termios+select）
  - 触发后只设一个 asyncio.Event，由调用方决定怎么用（cancel Task / break loop）
  - 显式 start() / stop() 上下文管理；stop() 后线程会在最多 _POLL 秒内退出
  - 不依赖 prompt_toolkit / Rich 内部状态，避免和 Live UI 抢 stdin
  - 测试可注入 mock keypress（_inject_for_test）

不接管 Ctrl+C —— 那个走原生 SIGINT，由 main.py 单独处理。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

_POLL = 0.05  # 50ms 轮询，平衡响应性和 CPU
_ESC = 27  # ASCII for ESC


class EscInterruptListener:
    """监听键盘 ESC，触发后调用 on_press（线程安全）。

    用法：

        listener = EscInterruptListener(on_press=lambda: ev.set())
        listener.start()
        try:
            ...
        finally:
            listener.stop()

    在非 TTY（CI / pipe）下 start() 直接 no-op，stop() 也 no-op。
    """

    def __init__(self, on_press: Callable[[], None]) -> None:
        self._on_press = on_press
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._triggered = False

    @property
    def triggered(self) -> bool:
        return self._triggered

    def start(self) -> None:
        if self._thread is not None:
            return
        # 非交互式 stdin（CI/pipe/重定向）下不启动 —— 没意义且可能阻塞
        try:
            if not sys.stdin.isatty():
                return
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="EscListener")
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        t = self._thread
        if t is not None and t.is_alive():
            # 不强 join，留余量；线程是 daemon 进程退出会自动收
            t.join(timeout=_POLL * 4)
        self._thread = None

    # ────────────────────────────────────────────────────────────────────────
    # 平台分支
    # ────────────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if os.name == "nt":
            self._run_windows()
        else:
            self._run_posix()

    def _run_windows(self) -> None:
        try:
            import msvcrt
        except ImportError:
            return
        while not self._stop_flag.is_set():
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    # 0x00 / 0xE0 是功能键前缀，再吃一个字节避免误触
                    if ch in (b"\x00", b"\xe0"):
                        with self._suppress():
                            msvcrt.getch()
                        continue
                    if ch == b"\x1b":  # ESC
                        self._fire()
                        return
            except Exception:
                return
            self._stop_flag.wait(_POLL)

    def _run_posix(self) -> None:
        # POSIX-only 模块；Windows 上 mypy 看不到这些符号，整段用 type: ignore 屏蔽。
        try:
            import select
            import termios  # type: ignore[import-not-found]
            import tty  # type: ignore[import-not-found]
        except ImportError:
            return

        try:
            fd = sys.stdin.fileno()
        except Exception:
            return
        try:
            old_attrs = termios.tcgetattr(fd)  # type: ignore[attr-defined]
        except Exception:
            return

        try:
            tty.setcbreak(fd)  # type: ignore[attr-defined]
            while not self._stop_flag.is_set():
                rlist, _, _ = select.select([fd], [], [], _POLL)
                if not rlist:
                    continue
                try:
                    ch = os.read(fd, 1)
                except OSError:
                    return
                if not ch:
                    continue
                if ch == b"\x1b":  # ESC
                    # ESC 后短暂等下，区分单 ESC vs ANSI 转义序列（如方向键）
                    rlist2, _, _ = select.select([fd], [], [], 0.02)
                    if rlist2:
                        # 是 ANSI 序列，把后续字节读掉，不触发中断
                        with self._suppress():
                            os.read(fd, 8)
                        continue
                    self._fire()
                    return
        finally:
            with self._suppress():
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)  # type: ignore[attr-defined]

    # ────────────────────────────────────────────────────────────────────────

    def _fire(self) -> None:
        if self._triggered:
            return
        self._triggered = True
        import contextlib as _ctxlib

        with _ctxlib.suppress(Exception):
            self._on_press()

    @staticmethod
    def _suppress():  # type: ignore[no-untyped-def]
        import contextlib

        return contextlib.suppress(Exception)

    # ────────────────────────────────────────────────────────────────────────
    # 测试钩子
    # ────────────────────────────────────────────────────────────────────────

    def _inject_for_test(self) -> None:
        """单测专用：模拟一次 ESC 触发，不依赖真实 stdin。"""
        self._fire()


async def run_with_esc_interrupt(
    coro_factory: Callable[[], Any],
) -> tuple[Any, bool]:
    """运行 coro_factory()（必须返回 awaitable），同时监听 ESC。

    返回 (result_or_None, was_cancelled)。被 ESC 中断时取消 Task 并返回 (None, True)。
    """
    loop = asyncio.get_event_loop()
    cancel_event = asyncio.Event()

    def _on_esc() -> None:
        loop.call_soon_threadsafe(cancel_event.set)

    listener = EscInterruptListener(on_press=_on_esc)
    listener.start()

    awaitable = coro_factory()
    task = asyncio.ensure_future(awaitable)  # type: ignore[arg-type]
    cancel_task = asyncio.ensure_future(cancel_event.wait())
    try:
        # 同时等任务完成或 ESC 触发
        _done, _pending = await asyncio.wait(
            {task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_event.is_set() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            return None, True
        # task 自然完成
        cancel_task.cancel()
        return task.result(), False
    finally:
        listener.stop()
