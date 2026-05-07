"""全局每目标并发限流器（issue #15.4）。

场景：多个子代理可能同时对同一目标做 subdomain_enum / dir_bruteforce / port_scan，
每个内部又有 20/10 并发，叠加后极易触发 WAF/rate-limit。

本模块提供 per-target 的 asyncio.Semaphore，跨工具/跨子代理共享。

API:
    async with target_slot("example.com", limit=20):
        ...

限流上限可通过 config.toml 的 `[security] per_target_concurrency` 调整（默认 20）。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

_semaphores: dict[str, asyncio.Semaphore] = {}
_lock = asyncio.Lock()
_default_limit: int | None = None


def _load_limit() -> int:
    """从 config.toml 读取 per-target 并发上限，缓存结果。"""
    global _default_limit
    if _default_limit is not None:
        return _default_limit
    try:
        import os

        from utils.paths import CONFIG_PATH

        if os.path.exists(CONFIG_PATH):
            import toml

            cfg = toml.load(CONFIG_PATH)
            n = cfg.get("security", {}).get("per_target_concurrency", 20)
            if isinstance(n, int) and n > 0:
                _default_limit = n
                return n
    except Exception:
        pass
    _default_limit = 20
    return 20


def reset() -> None:
    """测试用：清掉所有 semaphore + 缓存。"""
    global _default_limit
    _semaphores.clear()
    _default_limit = None


@asynccontextmanager
async def target_slot(target: str, limit: int | None = None):  # type: ignore[no-untyped-def]
    """对 `target` 拿一个并发槽。

    Args:
        target: 任意标识（domain/host/url），同名共享同一 semaphore
        limit: 覆盖默认 per-target 并发上限
    """
    key = (target or "").strip().lower() or "_unknown"
    cap = limit if limit is not None else _load_limit()
    async with _lock:
        sem = _semaphores.get(key)
        if sem is None:
            sem = asyncio.Semaphore(cap)
            _semaphores[key] = sem
    async with sem:
        yield
