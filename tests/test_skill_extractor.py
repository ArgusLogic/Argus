"""A2 — 自动技能提炼测试。

避免真实 LLM 调用：用 mock_llm fixture + monkeypatch _judge_with_llm。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.skill_extractor import (
    extract_skill_async,
    is_extraction_worthwhile,
    normalize_name,
)
from agent.skills import SkillManager


def _assistant_call(tcid: str, tool: str, args: str = "{}") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tcid,
                "type": "function",
                "function": {"name": tool, "arguments": args},
            }
        ],
    }


def _tool_result(tcid: str, content: str = "ok") -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tcid, "content": content}


# ─── normalize_name ─────────────────────────────────────────────────────────


class TestNormalizeName:
    def test_basic(self) -> None:
        assert normalize_name("Recon Pipeline") == "recon_pipeline"

    def test_special_chars_stripped(self) -> None:
        # `/` 和 `!` 被剥离；`-` 转为 `_`
        assert normalize_name("Web/Recon-v2!") == "webrecon_v2"

    def test_empty_fallback(self) -> None:
        assert normalize_name("") == "unnamed_skill"

    def test_lowercase_underscore(self) -> None:
        assert normalize_name("ALREADY_CLEAN") == "already_clean"


# ─── is_extraction_worthwhile ───────────────────────────────────────────────


class TestIsWorthwhile:
    def test_too_few_calls(self) -> None:
        msgs = [_assistant_call("tc0", "a"), _tool_result("tc0")]
        assert is_extraction_worthwhile(msgs, "done") is False

    def test_empty_final_text(self) -> None:
        msgs = [
            _assistant_call("tc0", "a"),
            _tool_result("tc0"),
            _assistant_call("tc1", "b"),
            _tool_result("tc1"),
            _assistant_call("tc2", "c"),
            _tool_result("tc2"),
        ]
        assert is_extraction_worthwhile(msgs, "") is False

    def test_enough_calls_passes(self) -> None:
        msgs = [
            _assistant_call("tc0", "a"),
            _tool_result("tc0"),
            _assistant_call("tc1", "b"),
            _tool_result("tc1"),
            _assistant_call("tc2", "c"),
            _tool_result("tc2"),
        ]
        assert is_extraction_worthwhile(msgs, "summary done") is True

    def test_failure_heavy_session_skipped(self) -> None:
        msgs = [
            _assistant_call("tc0", "a"),
            _tool_result("tc0", "工具执行失败：超时"),
            _assistant_call("tc1", "b"),
            _tool_result("tc1", "ok"),
            _assistant_call("tc2", "c"),
            _tool_result("tc2", "ok"),
        ]
        assert is_extraction_worthwhile(msgs, "done") is False


# ─── extract_skill_async ────────────────────────────────────────────────────


class TestExtractSkillAsync:
    """全部 mock LLM，不真实调用。"""

    @pytest.fixture
    def mock_llm(self) -> Any:
        llm = MagicMock()
        llm.chat = AsyncMock()
        return llm

    def _good_messages(self) -> list[dict[str, Any]]:
        return [
            _assistant_call("tc0", "dns_lookup", '{"domain": "example.com"}'),
            _tool_result("tc0"),
            _assistant_call("tc1", "whois_lookup", '{"domain": "example.com"}'),
            _tool_result("tc1"),
            _assistant_call("tc2", "header_analysis", '{"url": "https://example.com"}'),
            _tool_result("tc2"),
        ]

    @pytest.mark.asyncio
    async def test_skips_when_unworthwhile(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        # 仅 1 次 tool call → unworthwhile
        msgs = [_assistant_call("tc0", "x"), _tool_result("tc0")]
        result = await extract_skill_async(mock_llm, skill_manager, msgs, "done")
        assert result is None
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_judges_not_worth_saving(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"worth_saving": false}'
        mock_llm.chat.return_value = mock_resp

        result = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert result is None
        assert skill_manager.list_skills() == []

    @pytest.mark.asyncio
    async def test_creates_new_skill(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = (
            '{"worth_saving": true, "name": "Basic Recon Flow", '
            '"description": "DNS+WHOIS+安全头一站式基础侦察"}'
        )
        mock_llm.chat.return_value = mock_resp

        name = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert name == "basic_recon_flow"
        skills = skill_manager.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "basic_recon_flow"

    @pytest.mark.asyncio
    async def test_dedup_skips_existing_name(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        # 先存一个同名技能
        skill_manager.save_skill(
            {
                "name": "basic_recon_flow",
                "description": "已存在",
                "steps": [],
                "success_count": 5,
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[
            0
        ].message.content = '{"worth_saving": true, "name": "Basic Recon Flow", "description": "重复"}'
        mock_llm.chat.return_value = mock_resp

        name = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert name is None
        # 不动现存的 success_count
        existing = skill_manager.get_skill("basic_recon_flow")
        assert existing is not None
        assert existing["success_count"] == 5

    @pytest.mark.asyncio
    async def test_handles_invalid_json_response(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "this is not JSON"
        mock_llm.chat.return_value = mock_resp

        # 应当静默失败（不抛异常）
        result = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_llm_exception(self, mock_llm: Any, skill_manager: SkillManager) -> None:
        mock_llm.chat.side_effect = RuntimeError("API down")
        # 静默吞掉
        result = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert result is None

    @pytest.mark.asyncio
    async def test_outer_timeout_swallowed(
        self, mock_llm: Any, skill_manager: SkillManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#15.9: 外层 wait_for 兜底，LLM 卡死也不会悬挂。"""
        import asyncio

        monkeypatch.setattr("agent.skill_extractor.TOTAL_TIMEOUT_S", 0.05)

        async def _hang(**_: Any) -> Any:
            await asyncio.sleep(2.0)

        mock_llm.chat.side_effect = _hang
        result = await extract_skill_async(mock_llm, skill_manager, self._good_messages(), "done")
        assert result is None
