"""Day3-1: ProgressTracker 单元测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from utils.progress import ProgressTracker


def test_tracker_emits_at_milestones() -> None:
    """每 5% 跨越一次时调用 log_info；100/100 ticks 应触发约 19 次 (5,10,...,95)。"""
    with patch("utils.progress.log_info") as mock_log:
        tracker = ProgressTracker("test", total=100, milestone_pct=5)
        for _ in range(99):
            tracker.tick()
        # 95% 应该已经被 emit；100% 不该出现（done 未调用）
        mock_log.assert_called()
        # 大致 19 次（5,10,...,95），允许一点偏差
        assert 15 <= mock_log.call_count <= 22


def test_tracker_done_emits_100() -> None:
    with patch("utils.progress.log_info") as mock_log:
        tracker = ProgressTracker("test", total=10, milestone_pct=10)
        for _ in range(10):
            tracker.tick()
        tracker.done()
        # 至少最后一次包含 "100%"
        last_msg = mock_log.call_args_list[-1].args[0]
        assert "100%" in last_msg
        assert "✓" in last_msg


def test_tracker_no_emit_for_zero_total() -> None:
    """total=0 不应崩溃也不应输出。"""
    with patch("utils.progress.log_info") as mock_log:
        tracker = ProgressTracker("empty", total=0)
        tracker.tick()
        tracker.done()
        mock_log.assert_not_called()


def test_tracker_milestone_pct_clamped() -> None:
    tracker = ProgressTracker("x", total=100, milestone_pct=0)
    assert tracker.milestone_pct >= 1
    tracker = ProgressTracker("x", total=100, milestone_pct=99)
    assert tracker.milestone_pct <= 50


def test_tracker_label_in_emitted_message() -> None:
    with patch("utils.progress.log_info") as mock_log:
        tracker = ProgressTracker("custom_label_xyz", total=100, milestone_pct=10)
        for _ in range(50):
            tracker.tick()
        all_msgs = [c.args[0] for c in mock_log.call_args_list]
        assert any("custom_label_xyz" in m for m in all_msgs)


def test_tracker_eta_appears_after_warmup() -> None:
    """0.5s 后 emit 的进度行应带 ETA。"""
    import time

    with patch("utils.progress.log_info") as mock_log:
        tracker = ProgressTracker("slow", total=100, milestone_pct=10)
        for _ in range(20):
            tracker.tick()
        # 模拟 0.6s 已过
        tracker._t0 = time.monotonic() - 0.6
        for _ in range(20):
            tracker.tick()
        msgs_with_eta = [m for c in mock_log.call_args_list for m in c.args if "ETA" in m]
        assert msgs_with_eta, "应至少有一条带 ETA 的 emit"
