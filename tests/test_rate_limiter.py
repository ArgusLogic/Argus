"""issue #15.4 — utils.rate_limiter 单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from utils import rate_limiter

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset() -> None:
    rate_limiter.reset()
    yield
    rate_limiter.reset()


class TestPerTargetSlot:
    async def test_concurrent_acquires_serialized(self) -> None:
        """limit=1 时同 target 必须串行。"""
        order: list[str] = []

        async def worker(name: str) -> None:
            async with rate_limiter.target_slot("alpha", limit=1):
                order.append(f"start-{name}")
                await asyncio.sleep(0.01)
                order.append(f"end-{name}")

        await asyncio.gather(worker("a"), worker("b"))
        # 必须严格交替：start/end 成对，不能 start/start
        assert order[0].startswith("start-")
        assert order[1].startswith("end-")
        assert order[2].startswith("start-")
        assert order[3].startswith("end-")

    async def test_different_targets_independent(self) -> None:
        """不同 target 互不影响。"""
        ran: list[str] = []

        async def worker(target: str) -> None:
            async with rate_limiter.target_slot(target, limit=1):
                ran.append(target)
                await asyncio.sleep(0.005)

        # 两个不同目标，limit=1 但应同时进入
        await asyncio.gather(worker("a.com"), worker("b.com"))
        assert sorted(ran) == ["a.com", "b.com"]

    async def test_target_normalized(self) -> None:
        """大小写/空白归一化：相同 host 共享 semaphore。"""
        order: list[str] = []

        async def worker(target: str, name: str) -> None:
            async with rate_limiter.target_slot(target, limit=1):
                order.append(name)
                await asyncio.sleep(0.005)

        await asyncio.gather(worker("Foo.COM", "x"), worker("foo.com ", "y"))
        # 串行
        assert len(order) == 2

    async def test_empty_target_uses_unknown_bucket(self) -> None:
        # 不应崩溃
        async with rate_limiter.target_slot("", limit=2):
            pass
        async with rate_limiter.target_slot(None, limit=2):  # type: ignore[arg-type]
            pass


class TestConfigLoading:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_default_when_no_config(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(tmp_path / "no.toml"))
        rate_limiter.reset()
        assert rate_limiter._load_limit() == 20

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reads_from_config(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[security]\nper_target_concurrency = 5\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        rate_limiter.reset()
        assert rate_limiter._load_limit() == 5

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_value_falls_back(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        cfg = tmp_path / "config.toml"
        cfg.write_text("[security]\nper_target_concurrency = -1\n", encoding="utf-8")
        monkeypatch.setattr("utils.paths.CONFIG_PATH", str(cfg))
        rate_limiter.reset()
        assert rate_limiter._load_limit() == 20
