"""issue #15.6 — classify_llm_error 新增网络/超时分类测试。"""

from __future__ import annotations

import pytest

from agent.errors import (
    APIAuthError,
    APIBalanceError,
    APINetworkError,
    APIRateLimit,
    APITimeout,
    LLMError,
    classify_llm_error,
)


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("Insufficient balance", APIBalanceError),
        ("quota exceeded", APIBalanceError),
        ("Rate limit exceeded", APIRateLimit),
        ("Too Many Requests (429)", APIRateLimit),
        ("Unauthorized 401 - invalid api key", APIAuthError),
        # 新增网络/超时分类
        ("Read timeout after 30s", APITimeout),
        ("deadline exceeded", APITimeout),
        ("connection refused", APINetworkError),
        ("ECONNRESET", APINetworkError),
        ("EPIPE: broken pipe", APINetworkError),
        ("getaddrinfo failed", APINetworkError),
        ("SSL handshake failed", APINetworkError),
        # 兜底
        ("some unknown error", LLMError),
    ],
)
def test_classify(msg: str, expected: type) -> None:
    err = classify_llm_error(Exception(msg))
    assert isinstance(err, expected)


def test_timeout_is_recoverable() -> None:
    err = classify_llm_error(Exception("read timeout"))
    assert err.recoverable is True


def test_network_is_recoverable() -> None:
    err = classify_llm_error(Exception("connection reset"))
    assert err.recoverable is True


def test_auth_is_not_recoverable() -> None:
    err = classify_llm_error(Exception("invalid api key 401"))
    assert err.recoverable is False
