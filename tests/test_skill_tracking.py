"""A1 — Skill usage tracking 单元测试。

覆盖：
- match_used_skills 的命中阈值与边界
- extract_tool_names 从消息中正确提取
- AgentEngine._track_skill_usage_after_run 增量 success_count 行为
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.skills import SkillManager


def _msg_with_calls(*tool_names: str) -> dict[str, Any]:
    """构造一条带 tool_calls 的 assistant 消息。"""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"tc{i}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for i, name in enumerate(tool_names)
        ],
    }


# ─── extract_tool_names ─────────────────────────────────────────────────────


class TestExtractToolNames:
    def test_extract_from_single_assistant(self, skill_manager: SkillManager) -> None:
        msgs = [_msg_with_calls("dns_lookup", "whois_lookup")]
        assert skill_manager.extract_tool_names(msgs) == ["dns_lookup", "whois_lookup"]

    def test_skips_user_and_tool_messages(self, skill_manager: SkillManager) -> None:
        msgs = [
            {"role": "user", "content": "hi"},
            _msg_with_calls("dns_lookup"),
            {"role": "tool", "tool_call_id": "tc0", "content": "result"},
        ]
        assert skill_manager.extract_tool_names(msgs) == ["dns_lookup"]

    def test_handles_missing_tool_calls(self, skill_manager: SkillManager) -> None:
        msgs = [{"role": "assistant", "content": "no tools used"}]
        assert skill_manager.extract_tool_names(msgs) == []


# ─── match_used_skills ──────────────────────────────────────────────────────


class TestMatchUsedSkills:
    def test_no_skills_no_match(self, skill_manager: SkillManager) -> None:
        assert skill_manager.match_used_skills(["dns_lookup", "whois_lookup"]) == []

    def test_low_overlap_below_threshold(self, skill_manager: SkillManager) -> None:
        # 技能需 5 工具，仅 1 个执行（20% < 60%）→ 不匹配
        skill_manager.save_skill(
            {
                "name": "deep_recon",
                "description": "5-step deep recon",
                "steps": [
                    {"tool": "dns_lookup", "args_template": {}},
                    {"tool": "whois_lookup", "args_template": {}},
                    {"tool": "subdomain_enum", "args_template": {}},
                    {"tool": "port_scan", "args_template": {}},
                    {"tool": "header_analysis", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        assert skill_manager.match_used_skills(["dns_lookup", "browser_navigate"]) == []

    def test_high_overlap_matches(self, skill_manager: SkillManager) -> None:
        # 5 工具中 3 个执行（60% = 阈值）→ 匹配
        skill_manager.save_skill(
            {
                "name": "deep_recon",
                "description": "5-step deep recon",
                "steps": [
                    {"tool": "dns_lookup", "args_template": {}},
                    {"tool": "whois_lookup", "args_template": {}},
                    {"tool": "subdomain_enum", "args_template": {}},
                    {"tool": "port_scan", "args_template": {}},
                    {"tool": "header_analysis", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        matched = skill_manager.match_used_skills(["dns_lookup", "whois_lookup", "subdomain_enum"])
        assert matched == ["deep_recon"]

    def test_single_step_skill_skipped(self, skill_manager: SkillManager) -> None:
        # 单步技能不参与匹配（避免无差别命中）
        skill_manager.save_skill(
            {
                "name": "trivial",
                "description": "1-step",
                "steps": [{"tool": "dns_lookup", "args_template": {}}],
                "success_count": 0,
            }
        )
        assert skill_manager.match_used_skills(["dns_lookup", "whois_lookup"]) == []

    def test_multiple_skills_can_match(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "skill_a",
                "description": "",
                "steps": [
                    {"tool": "dns_lookup", "args_template": {}},
                    {"tool": "whois_lookup", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        skill_manager.save_skill(
            {
                "name": "skill_b",
                "description": "",
                "steps": [
                    {"tool": "browser_navigate", "args_template": {}},
                    {"tool": "browser_get_text", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        matched = skill_manager.match_used_skills(
            ["dns_lookup", "whois_lookup", "browser_navigate", "browser_get_text"]
        )
        assert sorted(matched) == ["skill_a", "skill_b"]

    def test_empty_executed_returns_empty(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "any",
                "description": "",
                "steps": [
                    {"tool": "a", "args_template": {}},
                    {"tool": "b", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        assert skill_manager.match_used_skills([]) == []


# ─── AgentEngine._track_skill_usage_after_run ──────────────────────────────


class TestTrackSkillUsageAfterRun:
    """测试 engine 钩子 — 用最小 mock 避开异步 LLM 初始化。"""

    def _make_engine(self, skill_manager: SkillManager) -> Any:
        from agent.engine import AgentEngine

        # 不走 __init__，手动塞最小依赖
        eng = AgentEngine.__new__(AgentEngine)
        eng.skills = skill_manager
        eng.track_skill_usage = True
        eng._turn_start_idx = 0
        eng.messages = []
        return eng

    def test_increments_matched_skill(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "recon_pair",
                "description": "",
                "steps": [
                    {"tool": "dns_lookup", "args_template": {}},
                    {"tool": "whois_lookup", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        eng = self._make_engine(skill_manager)
        eng.messages = [
            {"role": "user", "content": "go"},
            _msg_with_calls("dns_lookup", "whois_lookup"),
        ]
        matched = eng._track_skill_usage_after_run("done")
        assert matched == ["recon_pair"]
        loaded = skill_manager.get_skill("recon_pair")
        assert loaded is not None
        assert loaded["success_count"] == 1

    def test_disabled_flag_skips_tracking(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "x",
                "description": "",
                "steps": [
                    {"tool": "a", "args_template": {}},
                    {"tool": "b", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        eng = self._make_engine(skill_manager)
        eng.track_skill_usage = False
        eng.messages = [_msg_with_calls("a", "b")]
        assert eng._track_skill_usage_after_run("done") == []
        loaded = skill_manager.get_skill("x")
        assert loaded is not None
        assert loaded["success_count"] == 0

    def test_empty_final_text_skips(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "x",
                "description": "",
                "steps": [
                    {"tool": "a", "args_template": {}},
                    {"tool": "b", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        eng = self._make_engine(skill_manager)
        eng.messages = [_msg_with_calls("a", "b")]
        assert eng._track_skill_usage_after_run("") == []
        loaded = skill_manager.get_skill("x")
        assert loaded is not None
        assert loaded["success_count"] == 0

    def test_too_few_tool_calls_skips(self, skill_manager: SkillManager) -> None:
        # 仅 1 工具调用 → 跳过（< 2 阈值）
        skill_manager.save_skill(
            {
                "name": "x",
                "description": "",
                "steps": [
                    {"tool": "a", "args_template": {}},
                    {"tool": "b", "args_template": {}},
                ],
                "success_count": 0,
            }
        )
        eng = self._make_engine(skill_manager)
        eng.messages = [_msg_with_calls("a")]
        assert eng._track_skill_usage_after_run("done") == []

    def test_swallows_exceptions(self, skill_manager: SkillManager) -> None:
        # skills.match_used_skills 抛异常时应静默返回 []
        eng = self._make_engine(skill_manager)
        eng.skills = MagicMock()
        eng.skills.extract_tool_names.return_value = ["a", "b"]
        eng.skills.match_used_skills.side_effect = RuntimeError("boom")
        eng.messages = [_msg_with_calls("a", "b")]
        assert eng._track_skill_usage_after_run("done") == []
