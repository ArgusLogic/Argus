"""Bug 3 回归：连续工具失败计数器 + 阈值 SYSTEM HINT 注入。

避免 LLM 在 N 次 tool_timeout 后陷入"换个参数再试"的死循环（用户场景：
浏览器 idle-close 后 console_exec 反复 60s 超时，LLM thinking 356s
未停）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _make_engine():
    """构造一个最小可用 Engine 实例。只为测 _track_consecutive_tool_failures。"""
    from agent.engine import AgentEngine
    from agent.llm_client import LLMClient
    from agent.tool_registry import ToolRegistry

    # 不会真发请求，因为该测试不调用 .run() / .chat
    llm = LLMClient(model="deepseek/deepseek-chat", api_keys={})
    registry = ToolRegistry()
    return AgentEngine(llm=llm, registry=registry)


async def test_initial_state_zero() -> None:
    eng = _make_engine()
    assert eng._consecutive_tool_failures == 0
    assert eng._max_consecutive_tool_failures == 3


async def test_business_failure_does_not_count() -> None:
    eng = _make_engine()
    # 业务级"失败"（404 / 用户拒绝 / 暂无网络记录）不应累加
    for txt in (
        "状态码: 404",
        "用户拒绝执行该操作",
        "暂无网络记录。请先访问页面后再查询",
        "操作被拒绝：目标不在允许的域名白名单内。",
    ):
        eng._track_consecutive_tool_failures(txt)
    assert eng._consecutive_tool_failures == 0


async def test_infra_failure_increments() -> None:
    eng = _make_engine()
    eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] 工具 X 执行超时 (60s): ...")
    assert eng._consecutive_tool_failures == 1
    eng._track_consecutive_tool_failures("[TOOL_ERROR] 工具 Y 执行失败: ...")
    assert eng._consecutive_tool_failures == 2


async def test_success_resets_counter() -> None:
    eng = _make_engine()
    eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] ...")
    eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] ...")
    assert eng._consecutive_tool_failures == 2
    # 任意非 infra 前缀的串都算成功（reset）
    eng._track_consecutive_tool_failures("状态码: 200\n响应头: ...")
    assert eng._consecutive_tool_failures == 0


async def test_threshold_triggers_hint_and_resets() -> None:
    eng = _make_engine()
    out1 = eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] 1")
    out2 = eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] 2")
    out3 = eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] 3")
    # 前两次未达阈值
    assert "[SYSTEM HINT]" not in out1
    assert "[SYSTEM HINT]" not in out2
    # 第三次达阈值 → 注入 hint
    assert "[SYSTEM HINT]" in out3
    assert "停止重试" in out3
    # 注入后立即重置，避免每轮都再加一遍
    assert eng._consecutive_tool_failures == 0


async def test_after_threshold_recover() -> None:
    """阈值触发后，新的失败计数从 0 重新开始累加。"""
    eng = _make_engine()
    for _ in range(3):
        eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] x")
    assert eng._consecutive_tool_failures == 0
    # 再来一次失败应只是 1，不会立刻又触发 hint
    out = eng._track_consecutive_tool_failures("[TOOL_TIMEOUT] x")
    assert "[SYSTEM HINT]" not in out
    assert eng._consecutive_tool_failures == 1


async def test_threshold_configurable() -> None:
    """允许通过实例属性调整阈值（例如更激进或更宽松的策略）。"""
    eng = _make_engine()
    eng._max_consecutive_tool_failures = 2
    eng._track_consecutive_tool_failures("[TOOL_ERROR] x")
    out = eng._track_consecutive_tool_failures("[TOOL_ERROR] x")
    assert "[SYSTEM HINT]" in out
