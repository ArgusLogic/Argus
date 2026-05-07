"""AgentEngine 工具级 ACL 测试（_check_tool_acl + _force_approval）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.engine import AgentEngine
from agent.tool_registry import ToolRegistry


def _make_engine(**kwargs) -> AgentEngine:
    llm = MagicMock()
    llm.model = "mock"
    return AgentEngine(llm=llm, registry=ToolRegistry(), **kwargs)


class TestToolACL:
    def test_default_no_lists_allows_everything(self) -> None:
        engine = _make_engine()
        ok, reason = engine._check_tool_acl("any_tool")
        assert ok is True
        assert reason == ""

    def test_blocklist_rejects(self) -> None:
        engine = _make_engine(tool_blocklist=["dangerous_tool"])
        ok, reason = engine._check_tool_acl("dangerous_tool")
        assert ok is False
        assert "blocklist" in reason

    def test_blocklist_does_not_affect_other_tools(self) -> None:
        engine = _make_engine(tool_blocklist=["dangerous_tool"])
        ok, _ = engine._check_tool_acl("safe_tool")
        assert ok is True

    def test_allowlist_rejects_unlisted(self) -> None:
        engine = _make_engine(tool_allowlist=["http_get", "dns_lookup"])
        ok, reason = engine._check_tool_acl("port_scan")
        assert ok is False
        assert "allowlist" in reason

    def test_allowlist_permits_listed(self) -> None:
        engine = _make_engine(tool_allowlist=["http_get"])
        ok, _ = engine._check_tool_acl("http_get")
        assert ok is True

    def test_blocklist_overrides_allowlist(self) -> None:
        """同时在两个列表中：blocklist 优先（最严格）。"""
        engine = _make_engine(
            tool_allowlist=["dangerous"],
            tool_blocklist=["dangerous"],
        )
        ok, reason = engine._check_tool_acl("dangerous")
        assert ok is False
        assert "blocklist" in reason

    def test_empty_allowlist_means_no_restriction(self) -> None:
        """allowlist=[] 表示不启用（不是「全部禁用」）。"""
        engine = _make_engine(tool_allowlist=[])
        ok, _ = engine._check_tool_acl("any_tool")
        assert ok is True


class TestForceApproval:
    def test_default_empty_list(self) -> None:
        engine = _make_engine()
        assert engine._force_approval("any_tool") is False

    def test_listed_tool_forces_approval(self) -> None:
        engine = _make_engine(require_approval_for=["http_get", "delegate_subagents"])
        assert engine._force_approval("http_get") is True
        assert engine._force_approval("delegate_subagents") is True

    def test_unlisted_tool_no_force(self) -> None:
        engine = _make_engine(require_approval_for=["http_get"])
        assert engine._force_approval("dns_lookup") is False
