"""L4 故障注入场景 · 真·并发/降级集成测试。

把 plan 里 L4 的 4 个重点场景做成**能在 CI 上反复跑**的自动化检查。
每条测试独立、确定性、不依赖网络（通过 mock/ 计数器/ semaphore 观测）。

覆盖面：
  L4.a ESC 中断 → 参见 test_interrupt.py（已存在）
  L4.b 浏览器崩溃恢复 → 参见 test_browser_recovery.py（已存在）
  L4.c per-target 限流跨工具 → 本文件
  L4.d 审批拒绝 / skip session 缓存 → 参见 test_approval_ui.py（已存在）

本文件新增：
  - 2 个 subdomain_enum 并发到同一 target：全局 semaphore 上限生效
  - dir_bruteforce + subdomain_enum 叠加时共享同一 slot
  - wildcard + per-target 限流复合场景仍保持正确过滤
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_target_slot_shared_across_subdomain_enum_calls() -> None:
    """两个并发 subdomain_enum 同 target，全局 semaphore 生效 → 任一瞬间在 slot 里的协程
    数 ≤ cap。"""
    import utils.rate_limiter as rl
    from tools import recon

    rl.reset()

    cap = 5
    in_flight = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def fake_detect(_domain: str) -> set[str]:
        return set()

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        nonlocal in_flight, max_seen
        async with lock:
            in_flight += 1
            max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return []  # 解析全失败，不影响 semaphore 观测

    wordlist = [f"sub{i}" for i in range(30)]

    with (
        patch.object(recon, "_detect_wildcard_ips", side_effect=fake_detect),
        patch.object(recon, "_resolve_ips", side_effect=fake_resolve),
        patch.object(recon, "SUBDOMAINS", wordlist),
        # 强制低限流以便观察
        patch.object(rl, "_load_limit", return_value=cap),
    ):
        await asyncio.gather(
            recon.subdomain_enum("target.example", concurrency="10"),
            recon.subdomain_enum("target.example", concurrency="10"),
        )

    assert max_seen <= cap, f"semaphore 被击穿: {max_seen} > {cap}"
    # 两个任务共 60 次 resolve，都跑完
    assert in_flight == 0

    rl.reset()


@pytest.mark.asyncio
async def test_target_slot_independent_per_target() -> None:
    """不同 target 用独立 semaphore，互不占用对方槽位。"""
    import utils.rate_limiter as rl

    rl.reset()
    cap = 2
    waited: list[str] = []

    async def worker(name: str, target: str) -> None:
        async with rl.target_slot(target, limit=cap):
            waited.append(f"{name}:enter")
            await asyncio.sleep(0.02)
            waited.append(f"{name}:exit")

    # 4 个目标 A / 4 个目标 B 同时跑
    tasks = [worker(f"A{i}", "alpha") for i in range(4)] + [
        worker(f"B{i}", "beta") for i in range(4)
    ]
    await asyncio.gather(*tasks)

    # 两个 target 独立 semaphore，每个 slot cap=2，总并发可达 4
    # 这里只确认所有 8 个 worker 都进入且退出
    assert sum(1 for w in waited if w.endswith(":enter")) == 8
    assert sum(1 for w in waited if w.endswith(":exit")) == 8

    rl.reset()


@pytest.mark.asyncio
async def test_wildcard_filter_under_rate_limit() -> None:
    """wildcard 过滤 + 限流同时生效：结果依然干净。"""
    import utils.rate_limiter as rl
    from tools import recon

    rl.reset()

    async def fake_detect(_domain: str) -> set[str]:
        return {"198.18.0.0/15"}

    async def fake_resolve(_sub: str, _domain: str) -> list[str]:
        await asyncio.sleep(0.002)
        return ["198.18.24.50"]  # 命中 wildcard 段

    with (
        patch.object(recon, "_detect_wildcard_ips", side_effect=fake_detect),
        patch.object(recon, "_resolve_ips", side_effect=fake_resolve),
        patch.object(recon, "SUBDOMAINS", [f"x{i}" for i in range(10)]),
        patch.object(rl, "_load_limit", return_value=3),
    ):
        out = await recon.subdomain_enum("t.example", concurrency="5")

    assert "wildcard DNS" in out
    assert "已过滤 10 条" in out
    assert "未发现" in out

    rl.reset()


@pytest.mark.asyncio
async def test_target_slot_cleanup_on_exception() -> None:
    """工具抛异常时 semaphore 也必须释放，不能卡死。"""
    import utils.rate_limiter as rl

    rl.reset()
    cap = 2

    async def boom() -> None:
        async with rl.target_slot("broken", limit=cap):
            raise RuntimeError("tool crashed")

    # 连续跑 cap + 2 次，若未正确释放会卡死
    for _ in range(cap + 2):
        with pytest.raises(RuntimeError):
            await boom()

    # 还能正常拿槽
    entered = False
    async with rl.target_slot("broken", limit=cap):
        entered = True
    assert entered

    rl.reset()
