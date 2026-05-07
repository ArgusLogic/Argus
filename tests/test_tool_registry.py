"""ToolRegistry 测试：注册、Schema、execute 路径。"""

from __future__ import annotations

import asyncio

import pytest

from agent.tool_registry import ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    """每个测试使用独立的注册表实例。"""
    return ToolRegistry()


class TestRegister:
    def test_register_async_tool(self, registry: ToolRegistry) -> None:
        @registry.tool(name="echo", description="echo")
        async def _echo(text: str = "x") -> str:
            return text

        assert "echo" in registry.list_tools()

    def test_register_sync_tool(self, registry: ToolRegistry) -> None:
        @registry.tool(name="add", description="add")
        def _add(a: int = 1, b: int = 2) -> int:
            return a + b

        assert "add" in registry.list_tools()

    def test_get_tools_schema_format(self, registry: ToolRegistry) -> None:
        @registry.tool(
            name="ping",
            description="health check",
            params={"target": {"type": "string", "description": "目标地址"}},
        )
        async def _ping(target: str) -> str:
            return "pong"

        schemas = registry.get_tools_schema()
        assert len(schemas) == 1
        fn = schemas[0]["function"]
        assert fn["name"] == "ping"
        assert fn["description"] == "health check"
        assert "target" in fn["parameters"]["properties"]
        assert "target" in fn["parameters"]["required"]


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_execute_async_returns_str(self, registry: ToolRegistry) -> None:
        @registry.tool(name="hello", description="x")
        async def _hello(name: str = "world") -> str:
            return f"hello {name}"

        result = await registry.execute("hello", {"name": "argus"})
        assert "hello argus" in result

    @pytest.mark.asyncio
    async def test_execute_dict_arguments(self, registry: ToolRegistry) -> None:
        @registry.tool(name="multi", description="x")
        async def _multi(a: int, b: int) -> int:
            return a * b

        result = await registry.execute("multi", {"a": 3, "b": 4})
        assert result == "12"

    @pytest.mark.asyncio
    async def test_execute_string_arguments(self, registry: ToolRegistry) -> None:
        @registry.tool(name="combine", description="x")
        async def _combine(a: str, b: str) -> str:
            return a + b

        result = await registry.execute("combine", '{"a": "foo", "b": "bar"}')
        assert result == "foobar"

    @pytest.mark.asyncio
    async def test_execute_invalid_json_args_treated_as_empty(self, registry: ToolRegistry) -> None:
        @registry.tool(name="default_only", description="x")
        async def _default_only(name: str = "fallback") -> str:
            return name

        result = await registry.execute("default_only", "not valid json")
        assert result == "fallback"


class TestExecuteErrors:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_tool_not_found(self, registry: ToolRegistry) -> None:
        result = await registry.execute("ghost_tool", {})
        assert "TOOL_NOT_FOUND" in result
        assert "ghost_tool" in result

    @pytest.mark.asyncio
    async def test_timeout(self, registry: ToolRegistry) -> None:
        @registry.tool(name="slow", description="x")
        async def _slow() -> str:
            await asyncio.sleep(2)
            return "done"

        result = await registry.execute("slow", {}, timeout=1)
        assert "TOOL_TIMEOUT" in result
        assert "slow" in result

    @pytest.mark.asyncio
    async def test_runtime_exception_wrapped_as_tool_error(self, registry: ToolRegistry) -> None:
        @registry.tool(name="boom", description="x")
        async def _boom() -> str:
            raise RuntimeError("KABOOM")

        result = await registry.execute("boom", {})
        assert "TOOL_ERROR" in result
        assert "KABOOM" in result

    @pytest.mark.asyncio
    async def test_param_error_no_retry(self, registry: ToolRegistry) -> None:
        """TypeError/ValueError 是参数错误，不应消耗重试预算。"""
        call_count = {"n": 0}

        @registry.tool(name="bad_args", description="x")
        async def _bad_args() -> str:
            call_count["n"] += 1
            raise ValueError("invalid params")

        result = await registry.execute("bad_args", {}, max_retries=3)
        assert "TOOL_ERROR" in result
        assert call_count["n"] == 1, "ValueError 不应触发重试"

    @pytest.mark.asyncio
    async def test_runtime_exception_does_retry(self, registry: ToolRegistry) -> None:
        call_count = {"n": 0}

        @registry.tool(name="flaky", description="x")
        async def _flaky() -> str:
            call_count["n"] += 1
            raise RuntimeError("transient")

        await registry.execute("flaky", {}, max_retries=2)
        assert call_count["n"] == 3, "RuntimeError 应被重试 max_retries 次"

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, registry: ToolRegistry) -> None:
        attempts = {"n": 0}

        @registry.tool(name="recovers", description="x")
        async def _recovers() -> str:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("first try fails")
            return "ok"

        result = await registry.execute("recovers", {}, max_retries=2)
        assert result == "ok"
        assert attempts["n"] == 2
