"""B2 — 用户建模测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.memory_md import MemoryMD
from agent.user_profile import summarize_session_messages, update_user_profile_async


@pytest.fixture
def memory_md(_isolate_argus_home: Path) -> MemoryMD:
    return MemoryMD()


@pytest.fixture
def mock_llm() -> Any:
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


# ─── summarize_session_messages ─────────────────────────────────────────────


class TestSummarize:
    def test_basic_user_assistant(self) -> None:
        msgs = [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "如何侦察 example.com"},
            {"role": "assistant", "content": "我先做 DNS 查询..."},
        ]
        out = summarize_session_messages(msgs)
        assert "USER: 如何侦察 example.com" in out
        assert "AGENT: 我先做 DNS 查询" in out

    def test_empty(self) -> None:
        assert summarize_session_messages([]) == ""

    def test_truncates_long(self) -> None:
        msgs = [{"role": "user", "content": "x" * 1000}]
        out = summarize_session_messages(msgs, max_chars=200)
        assert len(out) <= 220  # 200 + "...(截断)"
        assert "(截断)" in out


# ─── update_user_profile_async ──────────────────────────────────────────────


class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_no_summaries_returns_empty(self, mock_llm: Any, memory_md: MemoryMD) -> None:
        result = await update_user_profile_async(mock_llm, memory_md, [])
        assert result == []
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_entries_to_user_md(self, mock_llm: Any, memory_md: MemoryMD) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '["偏好中文输出", "关注电商站点 SSRF 漏洞"]'
        mock_llm.chat.return_value = mock_resp
        added = await update_user_profile_async(mock_llm, memory_md, ["USER: hi\nAGENT: ok"])
        assert added == ["偏好中文输出", "关注电商站点 SSRF 漏洞"]
        entries = memory_md.list_entries("user")
        assert "偏好中文输出" in entries
        assert "关注电商站点 SSRF 漏洞" in entries

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, mock_llm: Any, memory_md: MemoryMD) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "not JSON at all"
        mock_llm.chat.return_value = mock_resp
        result = await update_user_profile_async(mock_llm, memory_md, ["session 1"])
        assert result == []
        assert memory_md.list_entries("user") == []

    @pytest.mark.asyncio
    async def test_handles_llm_exception(self, mock_llm: Any, memory_md: MemoryMD) -> None:
        mock_llm.chat.side_effect = RuntimeError("API down")
        result = await update_user_profile_async(mock_llm, memory_md, ["session 1"])
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_empty_strings(self, mock_llm: Any, memory_md: MemoryMD) -> None:
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '["", "  ", "实际偏好"]'
        mock_llm.chat.return_value = mock_resp
        added = await update_user_profile_async(mock_llm, memory_md, ["x"])
        assert added == ["实际偏好"]
