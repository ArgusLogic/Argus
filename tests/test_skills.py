"""SkillManager 测试。"""

from __future__ import annotations

import os
from typing import Any

from agent.skills import SkillManager


class TestBasicCRUD:
    def test_save_and_get(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        loaded = skill_manager.get_skill("sample_recon")
        assert loaded is not None
        assert loaded["name"] == "sample_recon"
        assert loaded["description"] == "示例侦察技能"
        assert len(loaded["steps"]) == 2

    def test_get_nonexistent_returns_none(self, skill_manager: SkillManager) -> None:
        assert skill_manager.get_skill("does_not_exist") is None

    def test_save_adds_created_at(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        loaded = skill_manager.get_skill("sample_recon")
        assert loaded is not None
        assert "created_at" in loaded

    def test_save_initializes_success_count(
        self, skill_manager: SkillManager, sample_skill: dict[str, Any]
    ) -> None:
        skill = {"name": "no_count_skill", "description": "x", "steps": []}
        skill_manager.save_skill(skill)
        loaded = skill_manager.get_skill("no_count_skill")
        assert loaded is not None
        assert loaded.get("success_count", -1) == 0


class TestList:
    def test_empty_list(self, skill_manager: SkillManager) -> None:
        assert skill_manager.list_skills() == []

    def test_list_summary_fields(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        summary = skill_manager.list_skills()
        assert len(summary) == 1
        s = summary[0]
        assert s["name"] == "sample_recon"
        assert s["steps_count"] == 2
        assert s["success_count"] == 0

    def test_list_skips_invalid_json(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        # 写入一个坏 JSON 文件
        bad = os.path.join(skill_manager.skills_dir, "broken.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("not json {")
        # list_skills 应静默跳过
        result = skill_manager.list_skills()
        assert len(result) == 1
        assert result[0]["name"] == "sample_recon"


class TestDelete:
    def test_delete_existing(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        assert skill_manager.delete_skill("sample_recon") is True
        assert skill_manager.get_skill("sample_recon") is None

    def test_delete_nonexistent(self, skill_manager: SkillManager) -> None:
        assert skill_manager.delete_skill("ghost") is False


class TestIncrementSuccess:
    def test_increment(self, skill_manager: SkillManager, sample_skill: dict[str, Any]) -> None:
        skill_manager.save_skill(sample_skill)
        skill_manager.increment_success("sample_recon")
        loaded = skill_manager.get_skill("sample_recon")
        assert loaded is not None
        assert loaded["success_count"] == 1

    def test_increment_nonexistent_silent(self, skill_manager: SkillManager) -> None:
        # 不应抛错
        skill_manager.increment_success("ghost")


class TestFormatForPrompt:
    def test_empty_returns_empty_string(self, skill_manager: SkillManager) -> None:
        assert skill_manager.format_for_prompt() == ""

    def test_format_includes_name_and_description(
        self, skill_manager: SkillManager, sample_skill: dict[str, Any]
    ) -> None:
        skill_manager.save_skill(sample_skill)
        block = skill_manager.format_for_prompt()
        assert "sample_recon" in block
        assert "示例侦察技能" in block

    def test_sort_by_success_count_desc(self, skill_manager: SkillManager) -> None:
        skill_manager.save_skill(
            {
                "name": "low",
                "description": "x",
                "steps": [],
                "success_count": 1,
            }
        )
        skill_manager.save_skill(
            {
                "name": "high",
                "description": "y",
                "steps": [],
                "success_count": 100,
            }
        )
        block = skill_manager.format_for_prompt()
        # high 应在 low 之前
        assert block.index("high") < block.index("low")

    def test_limit(self, skill_manager: SkillManager) -> None:
        for i in range(10):
            skill_manager.save_skill(
                {
                    "name": f"skill_{i}",
                    "description": "x",
                    "steps": [],
                    "success_count": i,
                }
            )
        block = skill_manager.format_for_prompt(limit=3)
        # 只应包含最高 success_count 的 3 个
        assert "skill_9" in block
        assert "skill_0" not in block


class TestExtractStepsFromMessages:
    def test_extracts_tool_calls(self, skill_manager: SkillManager) -> None:
        messages = [
            {"role": "user", "content": "do recon"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "http_get", "arguments": '{"url": "https://x.com"}'}},
                ],
            },
            {"role": "tool", "content": "result"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "scan", "arguments": '{"target": "x.com"}'}},
                ],
            },
        ]
        steps = skill_manager.extract_steps_from_messages(messages)
        assert len(steps) == 2
        assert steps[0]["tool"] == "http_get"
        assert steps[1]["tool"] == "scan"

    def test_handles_invalid_args_json(self, skill_manager: SkillManager) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "broken", "arguments": "not json"}},
                ],
            },
        ]
        steps = skill_manager.extract_steps_from_messages(messages)
        assert len(steps) == 1
        assert steps[0]["args_template"] == {}

    def test_skips_assistant_without_tool_calls(self, skill_manager: SkillManager) -> None:
        messages = [
            {"role": "assistant", "content": "thinking..."},
        ]
        assert skill_manager.extract_steps_from_messages(messages) == []
