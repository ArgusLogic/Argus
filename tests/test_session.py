"""Session 持久化测试：save / load / list / delete + tool_calls 往返。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_save_and_load_round_trip() -> None:
    from agent.session import load_session, save_session

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    name = await save_session(messages, name="test_basic")
    assert name == "test_basic"

    loaded = await load_session("test_basic")
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"
    assert loaded[0]["content"] == "hello"
    assert loaded[1]["content"] == "hi there"


async def test_load_nonexistent_returns_none() -> None:
    from agent.session import load_session

    assert await load_session("does_not_exist") is None


async def test_save_auto_generates_name() -> None:
    from agent.session import save_session

    messages = [{"role": "user", "content": "x"}]
    name = await save_session(messages)
    # 默认是 YYYYMMDD_HHMMSS 格式
    assert len(name) == 15
    assert "_" in name


async def test_tool_calls_round_trip() -> None:
    from agent.session import load_session, save_session

    messages = [
        {"role": "user", "content": "scan example.com"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "http_get", "arguments": '{"url": "https://x.com"}'},
                }
            ],
        },
        {"role": "tool", "content": "200 OK", "tool_call_id": "call_1"},
    ]
    await save_session(messages, name="with_tools")

    loaded = await load_session("with_tools")
    assert loaded is not None
    assert len(loaded) == 3
    assert "tool_calls" in loaded[1]
    assert loaded[1]["tool_calls"][0]["id"] == "call_1"
    assert loaded[2]["tool_call_id"] == "call_1"


async def test_save_overwrites_same_name() -> None:
    from agent.session import load_session, save_session

    await save_session([{"role": "user", "content": "v1"}], name="overwrite")
    await save_session(
        [{"role": "user", "content": "v2"}, {"role": "assistant", "content": "ack"}],
        name="overwrite",
    )

    loaded = await load_session("overwrite")
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["content"] == "v2"


async def test_list_sessions() -> None:
    from agent.session import list_sessions, save_session

    await save_session([{"role": "user", "content": "a"}], name="alpha")
    await save_session([{"role": "user", "content": "b"}], name="beta")

    names = await list_sessions()
    # list_sessions 返回 “name  (N msgs, timestamp)” 格式字符串
    assert any(s.startswith("alpha") for s in names)
    assert any(s.startswith("beta") for s in names)


async def test_delete_session() -> None:
    from agent.session import delete_session, list_sessions, load_session, save_session

    await save_session([{"role": "user", "content": "x"}], name="to_delete")
    assert any(s.startswith("to_delete") for s in await list_sessions())

    result = await delete_session("to_delete")
    assert result is True
    assert not any(s.startswith("to_delete") for s in await list_sessions())
    assert await load_session("to_delete") is None


async def test_delete_nonexistent_returns_false() -> None:
    from agent.session import delete_session

    result = await delete_session("ghost")
    # 实现允许删除不存在的会话（DELETE 影响 0 行），返回 False
    assert result is False
