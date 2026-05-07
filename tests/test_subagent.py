"""SubAgent / SubAgentOrchestrator 测试（mock LLM，不发真实请求）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.subagent import (
    SubAgent,
    SubAgentOrchestrator,
    SubAgentTask,
    parse_tasks_from_args,
)
from agent.tool_registry import ToolRegistry

# 注意: TestParseTasks 是同步测试类，不应用 asyncio mark；因此这里不在模块级设 pytestmark。
# 异步测试类显式用 @pytest.mark.asyncio。


def _make_message(content: str = "", tool_calls: list | None = None) -> SimpleNamespace:
    """构造类似 LiteLLM 返回 message 的对象。"""
    msg = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=None,
    )
    return msg


def _make_response(message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.tool(name="dummy", description="x", params={})
    async def _dummy() -> str:
        return "dummy result"

    return reg


@pytest.fixture
def fake_llm() -> MagicMock:
    """返回单次 chat 即给出最终回复（无 tool_calls）的假 LLM。"""
    llm = MagicMock()
    llm.model = "mock"
    llm.chat = AsyncMock(return_value=_make_response(_make_message(content="子任务完成结论")))
    return llm


class TestParseTasks:
    def test_string_list(self) -> None:
        tasks = parse_tasks_from_args(["扫 a.com", "扫 b.com"])
        assert len(tasks) == 2
        assert tasks[0].goal == "扫 a.com"
        assert tasks[1].goal == "扫 b.com"

    def test_dict_list(self) -> None:
        tasks = parse_tasks_from_args([
            {"goal": "扫 a.com", "max_subturns": 5, "allowed_tools": ["http_get"]},
        ])
        assert tasks[0].goal == "扫 a.com"
        assert tasks[0].max_subturns == 5
        assert tasks[0].allowed_tools == ["http_get"]

    def test_json_string(self) -> None:
        tasks = parse_tasks_from_args('[{"goal": "x"}]')
        assert tasks[0].goal == "x"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON"):
            parse_tasks_from_args("not json")

    def test_missing_goal_raises(self) -> None:
        with pytest.raises(ValueError, match="goal"):
            parse_tasks_from_args([{"max_subturns": 5}])

    def test_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="列表"):
            parse_tasks_from_args({"goal": "x"})  # type: ignore


class TestSubAgentRun:
    async def test_simple_text_response(self, registry: ToolRegistry, fake_llm: MagicMock) -> None:
        agent = SubAgent(llm=fake_llm, registry=registry)
        result = await agent.run(SubAgentTask(goal="问个问题"))
        assert result.success is True
        assert "子任务完成结论" in result.final_text
        assert result.turns == 1
        assert result.tool_calls_count == 0

    async def test_with_tool_call(self, registry: ToolRegistry) -> None:
        # 第一轮: 调用 dummy 工具；第二轮: 给出最终回复
        tc = SimpleNamespace(
            id="tc1",
            function=SimpleNamespace(name="dummy", arguments="{}"),
        )
        responses = [
            _make_response(_make_message(content="", tool_calls=[tc])),
            _make_response(_make_message(content="基于工具结果的结论")),
        ]
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=responses)

        agent = SubAgent(llm=llm, registry=registry)
        result = await agent.run(SubAgentTask(goal="用 dummy 工具"))
        assert result.success is True
        assert result.tool_calls_count == 1
        assert result.turns == 2

    async def test_filters_delegate_subagents_from_tools(
        self, registry: ToolRegistry, fake_llm: MagicMock
    ) -> None:
        # 注入一个名为 delegate_subagents 的工具到 registry
        @registry.tool(name="delegate_subagents", description="x", params={})
        async def _fake_delegate(tasks: list) -> str:
            return "should never be called"

        agent = SubAgent(llm=fake_llm, registry=registry)
        await agent.run(SubAgentTask(goal="x"))

        # 验证传给 LLM 的 tools 列表里没有 delegate_subagents
        call_kwargs = fake_llm.chat.await_args.kwargs
        tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
        assert "delegate_subagents" not in tool_names
        assert "dummy" in tool_names

    async def test_allowed_tools_whitelist(self, registry: ToolRegistry, fake_llm: MagicMock) -> None:
        @registry.tool(name="other_tool", description="x", params={})
        async def _other() -> str:
            return "y"

        agent = SubAgent(llm=fake_llm, registry=registry)
        await agent.run(SubAgentTask(goal="x", allowed_tools=["dummy"]))

        call_kwargs = fake_llm.chat.await_args.kwargs
        tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
        assert tool_names == ["dummy"]

    async def test_max_subturns_terminates(self, registry: ToolRegistry) -> None:
        # 永远调用工具的 LLM
        tc = SimpleNamespace(
            id="tc",
            function=SimpleNamespace(name="dummy", arguments="{}"),
        )
        infinite_response = _make_response(_make_message(content="", tool_calls=[tc]))
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=infinite_response)

        agent = SubAgent(llm=llm, registry=registry)
        result = await agent.run(SubAgentTask(goal="x", max_subturns=3))
        assert result.success is False
        assert "最大轮次" in (result.error or "")
        assert result.turns == 3

    async def test_memory_block_in_system_prompt(
        self, registry: ToolRegistry, fake_llm: MagicMock
    ) -> None:
        agent = SubAgent(
            llm=fake_llm, registry=registry, memory_block="重要：xxx 漏洞"
        )
        await agent.run(SubAgentTask(goal="x"))

        sys_msg = fake_llm.chat.await_args.kwargs["messages"][0]["content"]
        assert "只读" in sys_msg
        assert "xxx 漏洞" in sys_msg


class TestOrchestrator:
    async def test_runs_in_parallel(self, registry: ToolRegistry, fake_llm: MagicMock) -> None:
        orch = SubAgentOrchestrator(llm=fake_llm, registry=registry, max_concurrency=4)
        tasks = [
            SubAgentTask(goal="任务 A"),
            SubAgentTask(goal="任务 B"),
            SubAgentTask(goal="任务 C"),
        ]
        results = await orch.run_parallel(tasks)
        assert len(results) == 3
        assert all(r.success for r in results)
        # 顺序保留
        assert [r.goal for r in results] == ["任务 A", "任务 B", "任务 C"]

    async def test_empty_tasks(self, registry: ToolRegistry, fake_llm: MagicMock) -> None:
        orch = SubAgentOrchestrator(llm=fake_llm, registry=registry)
        results = await orch.run_parallel([])
        assert results == []

    async def test_format_results_for_main(self, registry: ToolRegistry, fake_llm: MagicMock) -> None:
        orch = SubAgentOrchestrator(llm=fake_llm, registry=registry)
        results = await orch.run_parallel(
            [SubAgentTask(goal="X"), SubAgentTask(goal="Y")]
        )
        formatted = SubAgentOrchestrator.format_results_for_main(results)
        assert "已完成 2 个子任务" in formatted
        assert "目标: X" in formatted
        assert "目标: Y" in formatted

    async def test_concurrency_semaphore(self, registry: ToolRegistry) -> None:
        """验证 max_concurrency 真的限制了并发。"""
        import asyncio
        running_count = {"current": 0, "peak": 0}

        async def slow_chat(*args, **kwargs):
            running_count["current"] += 1
            running_count["peak"] = max(running_count["peak"], running_count["current"])
            await asyncio.sleep(0.05)
            running_count["current"] -= 1
            return _make_response(_make_message(content="ok"))

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=slow_chat)
        orch = SubAgentOrchestrator(llm=llm, registry=registry, max_concurrency=2)
        tasks = [SubAgentTask(goal=f"t{i}") for i in range(5)]

        await orch.run_parallel(tasks)
        assert running_count["peak"] <= 2


class TestGlobalOrchestrator:
    async def test_set_get(self) -> None:
        from agent.subagent import (
            get_global_orchestrator,
            set_global_orchestrator,
        )

        assert get_global_orchestrator() is None or get_global_orchestrator() is not None
        # 设置一个
        orch = SubAgentOrchestrator(llm=MagicMock(), registry=ToolRegistry())
        set_global_orchestrator(orch)
        assert get_global_orchestrator() is orch
        # 清空
        set_global_orchestrator(None)
        assert get_global_orchestrator() is None
