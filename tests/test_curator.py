"""B1 — autonomous skill curator 测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from agent.curator import (
    _group_similar,
    _is_stale,
    _parse_interval,
    _similarity,
    run_curator,
    write_report,
)
from agent.skills import SkillManager


def _make_skill(
    name: str,
    description: str,
    success_count: int = 0,
    pinned: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "steps": [{"tool": "x", "args_template": {}}],
        "success_count": success_count,
        "pinned": pinned,
        "created_at": created_at or datetime.now().isoformat(),
    }


# ─── 工具函数 ────────────────────────────────────────────────────────────────


class TestSimilarity:
    def test_identical_descriptions(self) -> None:
        assert _similarity("DNS 全套查询", "DNS 全套查询") == 1.0

    def test_completely_different(self) -> None:
        assert _similarity("DNS lookup flow", "browser screenshot tool") < 0.5


class TestIsStale:
    def test_recent_not_stale(self) -> None:
        assert _is_stale(datetime.now().isoformat(), 30) is False

    def test_old_is_stale(self) -> None:
        old = (datetime.now() - timedelta(days=45)).isoformat()
        assert _is_stale(old, 30) is True

    def test_invalid_returns_false(self) -> None:
        assert _is_stale("not-a-date", 30) is False


class TestParseInterval:
    def test_hours(self) -> None:
        assert _parse_interval("24h") == 24 * 3600

    def test_minutes(self) -> None:
        assert _parse_interval("30m") == 30 * 60

    def test_days(self) -> None:
        assert _parse_interval("7d") == 7 * 86400

    def test_seconds_default(self) -> None:
        assert _parse_interval("600") == 600.0


# ─── _group_similar ──────────────────────────────────────────────────────────


class TestGroupSimilar:
    def test_no_groups_when_descriptions_differ(self) -> None:
        skills = [
            {"name": "a", "description": "完全不同的描述 A 路径", "pinned": False},
            {"name": "b", "description": "完全无关的内容 zzz", "pinned": False},
        ]
        assert _group_similar(skills, threshold=0.85) == []

    def test_groups_similar_descriptions(self) -> None:
        skills = [
            {"name": "v1", "description": "DNS 全套查询流程", "pinned": False},
            {"name": "v2", "description": "DNS 全套查询流程 ", "pinned": False},
            {"name": "other", "description": "浏览器截图工具", "pinned": False},
        ]
        groups = _group_similar(skills, threshold=0.85)
        assert len(groups) == 1
        assert sorted(groups[0]) == ["v1", "v2"]

    def test_pinned_excluded_from_grouping(self) -> None:
        skills = [
            {"name": "p", "description": "DNS 全套查询", "pinned": True},
            {"name": "v2", "description": "DNS 全套查询", "pinned": False},
        ]
        # pinned 不参与分组
        assert _group_similar(skills, threshold=0.85) == []


# ─── run_curator 端到端 ──────────────────────────────────────────────────────


class TestRunCurator:
    def test_no_skills_no_changes(self, skill_manager: SkillManager) -> None:
        report = run_curator(skill_manager)
        assert report.total_before == 0
        assert report.total_after == 0
        assert report.merged == []
        assert report.archived_stale == []

    def test_merge_similar_keeps_higher_success(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(_make_skill("recon_v1", "DNS 全套侦察流程", success_count=2))
        skill_manager.save_skill(_make_skill("recon_v2", "DNS 全套侦察流程 ", success_count=5))
        report = run_curator(skill_manager)
        assert len(report.merged) == 1
        assert report.merged[0]["kept"] == "recon_v2"
        assert report.merged[0]["success_total"] == 7
        # v1 已被归档，仅剩 v2
        remaining = [s["name"] for s in skill_manager.list_skills()]
        assert remaining == ["recon_v2"]
        kept = skill_manager.get_skill("recon_v2")
        assert kept is not None
        assert kept["success_count"] == 7

    def test_archive_stale_zero_success(self, skill_manager: SkillManager) -> None:
        old = (datetime.now() - timedelta(days=45)).isoformat()
        skill_manager.save_skill(_make_skill("stale_one", "陈旧的 A", success_count=0, created_at=old))
        skill_manager.save_skill(_make_skill("active_one", "活跃的 B", success_count=3, created_at=old))
        skill_manager.save_skill(
            _make_skill("recent_zero", "新的 C", success_count=0)  # 今日，不归档
        )
        report = run_curator(skill_manager, archive_after_days=30)
        assert report.archived_stale == ["stale_one"]
        remaining = sorted(s["name"] for s in skill_manager.list_skills())
        assert remaining == ["active_one", "recent_zero"]

    def test_pinned_never_touched(self, skill_manager: SkillManager) -> None:
        old = (datetime.now() - timedelta(days=45)).isoformat()
        skill_manager.save_skill(
            _make_skill(
                "pinned_old",
                "陈旧 + pinned",
                success_count=0,
                pinned=True,
                created_at=old,
            )
        )
        skill_manager.save_skill(
            _make_skill(
                "pinned_dup",
                "DNS 全套侦察流程",
                success_count=1,
                pinned=True,
            )
        )
        skill_manager.save_skill(_make_skill("dup_v2", "DNS 全套侦察流程"))
        report = run_curator(skill_manager)
        # pinned 不参与 merge / 不被陈旧归档
        assert "pinned_old" not in report.archived_stale
        assert all("pinned_dup" not in m["merged_into_kept"] for m in report.merged)
        assert all(m["kept"] != "pinned_dup" for m in report.merged)
        # dup_v2 与 pinned_dup 不应分组
        assert len(report.merged) == 0
        # 三个技能都还在
        names = {s["name"] for s in skill_manager.list_skills()}
        assert names == {"pinned_old", "pinned_dup", "dup_v2"}

    def test_dry_run_does_not_mutate(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(_make_skill("a", "DNS 全套侦察流程", success_count=1))
        skill_manager.save_skill(_make_skill("b", "DNS 全套侦察流程"))
        report = run_curator(skill_manager, dry_run=True)
        assert len(report.merged) == 1
        # 文件未变
        names = sorted(s["name"] for s in skill_manager.list_skills())
        assert names == ["a", "b"]


class TestWriteReport:
    def test_writes_markdown_file(self, skill_manager: SkillManager, _isolate_argus_home) -> None:
        skill_manager.save_skill(_make_skill("a", "x"))
        report = run_curator(skill_manager, dry_run=True)
        path = write_report(report)
        assert path.endswith(".md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "# Curator Report" in text


class TestPinningSkillManager:
    def test_set_pinned_flow(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(_make_skill("foo", "x"))
        assert skill_manager.set_pinned("foo", True) is True
        assert skill_manager.get_skill("foo")["pinned"] is True  # type: ignore[index]
        assert skill_manager.set_pinned("foo", False) is True
        assert skill_manager.get_skill("foo")["pinned"] is False  # type: ignore[index]

    def test_set_pinned_unknown_returns_false(self, skill_manager: SkillManager) -> None:
        assert skill_manager.set_pinned("does_not_exist", True) is False

    def test_archive_skill_moves_file(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(_make_skill("foo", "x"))
        assert skill_manager.archive_skill("foo") is True
        # skills/ 已无
        assert skill_manager.get_skill("foo") is None
        # archive 目录至少有 1 个文件
        import os

        files = os.listdir(skill_manager.archive_dir)
        assert any("foo" in f for f in files)
