"""agent.errors 结构化异常体系测试。"""

from __future__ import annotations

import pytest

from agent.errors import (
    APIAuthError,
    APIBalanceError,
    APIRateLimit,
    ArgusError,
    ConfigError,
    LLMError,
    MemoryFullError,
    SecurityBlock,
    ToolError,
    ToolNotFound,
    ToolTimeout,
    classify_llm_error,
)


class TestArgusError:
    def test_inherits_from_exception(self) -> None:
        err = ArgusError(message="test")
        assert isinstance(err, Exception)

    def test_default_code(self) -> None:
        err = ArgusError(message="test")
        assert err.code == "ARGUS_ERROR"

    def test_default_recoverable_true(self) -> None:
        err = ArgusError(message="test")
        assert err.recoverable is True

    def test_str_format(self) -> None:
        err = ArgusError(message="something failed", code="X")
        assert "[X]" in str(err)
        assert "something failed" in str(err)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ArgusError) as exc:
            raise ArgusError(message="boom")
        assert exc.value.message == "boom"


class TestToolError:
    def test_carries_tool_name(self) -> None:
        err = ToolError(message="failed", tool_name="http_get")
        assert err.tool_name == "http_get"
        assert "http_get" in str(err)

    def test_default_code(self) -> None:
        assert ToolError(message="x").code == "TOOL_ERROR"


class TestToolTimeout:
    def test_timeout_seconds_in_message(self) -> None:
        err = ToolTimeout(message="took too long", tool_name="scan", timeout_seconds=60)
        assert "60s" in str(err)
        assert "scan" in str(err)

    def test_recoverable(self) -> None:
        err = ToolTimeout(message="x", timeout_seconds=10)
        assert err.recoverable is True


class TestToolNotFound:
    def test_includes_tool_name(self) -> None:
        err = ToolNotFound(message="not registered", tool_name="ghost_tool")
        assert "ghost_tool" in str(err)

    def test_not_recoverable(self) -> None:
        assert ToolNotFound(message="x").recoverable is False


class TestSecurityBlock:
    def test_includes_reason(self) -> None:
        err = SecurityBlock(message="blocked", reason="domain not in whitelist")
        assert "whitelist" in str(err)

    def test_not_recoverable(self) -> None:
        assert SecurityBlock(message="x").recoverable is False


class TestLLMErrors:
    def test_balance_not_recoverable(self) -> None:
        assert APIBalanceError(message="x").recoverable is False

    def test_rate_limit_recoverable(self) -> None:
        assert APIRateLimit(message="x").recoverable is True

    def test_auth_not_recoverable(self) -> None:
        assert APIAuthError(message="x").recoverable is False


class TestMemoryFullError:
    def test_format_includes_used_cap(self) -> None:
        err = MemoryFullError(message="cap reached", target="memory", used=2200, cap=2200)
        s = str(err)
        assert "memory" in s
        assert "2200" in s


class TestClassifyLLMError:
    def test_balance_keywords(self) -> None:
        assert isinstance(classify_llm_error(Exception("Insufficient Balance")), APIBalanceError)
        assert isinstance(classify_llm_error(Exception("quota exceeded")), APIBalanceError)
        assert isinstance(classify_llm_error(Exception("not enough credit")), APIBalanceError)

    def test_rate_limit_keywords(self) -> None:
        assert isinstance(classify_llm_error(Exception("rate limit exceeded")), APIRateLimit)
        assert isinstance(classify_llm_error(Exception("HTTP 429 too many requests")), APIRateLimit)

    def test_auth_keywords(self) -> None:
        assert isinstance(classify_llm_error(Exception("401 unauthorized")), APIAuthError)
        assert isinstance(classify_llm_error(Exception("invalid api key")), APIAuthError)
        assert isinstance(classify_llm_error(Exception("authentication failed")), APIAuthError)

    def test_unknown_falls_back_to_llm_error(self) -> None:
        result = classify_llm_error(Exception("random network glitch"))
        assert isinstance(result, LLMError)
        # 不是任何具体子类
        assert not isinstance(result, (APIBalanceError, APIRateLimit, APIAuthError))

    def test_preserves_original_message(self) -> None:
        err = classify_llm_error(Exception("Insufficient Balance: code 402"))
        assert "402" in str(err)


class TestConfigError:
    def test_not_recoverable(self) -> None:
        assert ConfigError(message="x").recoverable is False
