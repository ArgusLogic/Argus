"""Day3-1: 长耗时工具的轻量进度上报。

设计目标：在不和现有 LiveUI 抢屏的前提下，让用户感知"这个工具跑到哪一步了"。

实现：维护一个 (label -> last_logged_pct) 字典，每次 tick 计算当前进度百分比，
若跨过 5% 阈值就通过 logger 输出一行（log_info 自动路由到 LiveUI console）。

API:
    from utils.progress import ProgressTracker

    async def my_long_tool():
        tracker = ProgressTracker("subdomain_enum", total=2000)
        for sub in wordlist:
            ...
            tracker.tick()
        tracker.done()

零成本：CLI 静默时（非 TTY）由 logger 自己处理；测试时 logger 可被 mute。
不依赖 Rich Progress，避免和 LiveUI 双 Live 冲突。
"""

from __future__ import annotations

import threading
import time

from utils.logger import log_info


class ProgressTracker:
    """轻量进度上报；同名 label 多个实例不会互相干扰。"""

    def __init__(self, label: str, total: int, *, milestone_pct: int = 5) -> None:
        self.label = label
        self.total = max(0, total)
        self.milestone_pct = max(1, min(50, milestone_pct))
        self._current = 0
        self._last_logged_pct = -1
        self._lock = threading.Lock()
        self._t0 = time.monotonic()

    def tick(self, advance: int = 1) -> None:
        if self.total <= 0:
            return
        with self._lock:
            self._current += advance
            pct = int(100 * self._current / self.total)
            # 只在跨越下一档 milestone 时上报
            next_threshold = self._last_logged_pct + self.milestone_pct
            if pct >= next_threshold and pct < 100:
                self._last_logged_pct = pct - (pct % self.milestone_pct)
                self._emit(pct)

    def done(self) -> None:
        with self._lock:
            if self.total > 0 and self._last_logged_pct < 100:
                self._emit(100, suffix=" ✓")
                self._last_logged_pct = 100

    def _emit(self, pct: int, suffix: str = "") -> None:
        elapsed = time.monotonic() - self._t0
        eta_s = ""
        if 0 < pct < 100 and elapsed > 0.5:
            est_total = elapsed * 100 / pct
            remaining = max(0.0, est_total - elapsed)
            eta_s = f" · ETA {remaining:.0f}s"
        log_info(f"  ▸ {self.label}: {pct}% ({self._current}/{self.total}){eta_s}{suffix}")
