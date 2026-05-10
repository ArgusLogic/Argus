"""子代理并行系统（Hermes 风格的 Subagent Delegation）。

设计要点：
- 主代理通过 `delegate_subagents` 工具一次启动 N 个独立子任务
- 每个子代理是轻量化 engine：独立 messages 列表 + 共享 LLM/registry/BrowserPool
- 浏览器并发安全：tools.browser._navigation_lock 序列化所有页面操作（Argus 自报告 Bug #1）
  注意：BrowserPool._lock 只保护资源生命周期（创建/销毁），不保护 page 操作；
  并发的 browser_navigate 必须靠 _navigation_lock 串行才能避免互相覆盖
- MEMORY 共享只读：子代理拿到主代理的 memory_block 注入 system prompt，但不能写
- 防递归：子代理工具集排除 `delegate_subagents`，避免无限分裂
- 防失控：每个子代理有 max_subturns（默认 20）和总 timeout

典型场景：
    "对 a.com / b.com / c.com 都做信息收集" → 主代理一次发 3 个子任务并行扫描
    时间从 3T → ~T（取决于 LLM 串行 + 浏览器锁竞争）
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.errors import APIBalanceError, classify_llm_error
from utils.logger import log_info, log_warning

if TYPE_CHECKING:
    from agent.llm_client import LLMClient
    from agent.tool_registry import ToolRegistry


# Bug 2 (Coco 报告): 子代理硬黑名单——这些工具会污染主代理持久状态
# 即使 system prompt 说"只读"，LLM 也可能违反；必须工具层硬隔离
_SUBAGENT_BLOCKED_TOOLS: frozenset[str] = frozenset({
    "delegate_subagents",   # 防递归分裂
    "memory_manage",        # 不能改主 MEMORY.md / USER.md / LESSONS.md
    "skill_manage",         # 不能改 skills/
    "project_delete",       # 不能删主项目存档
})


SUBAGENT_SYSTEM_PROMPT = """你是 Argus 主 Agent 派出的子代理（subagent），负责完成一个**聚焦的子任务**。

# 角色约束
- 只完成你被分配的具体目标，不要扩展任务范围
- 不要再调用 delegate_subagents 工具（防止无限分裂）
- 完成后给出**简明扼要的结论**（最多几段话），主 agent 会汇总你和兄弟子代理的结果
- 你看到的 MEMORY 是只读的：可以参考，但不能调用 memory_manage 修改

# 输出要求
- 完成任务后直接结束（不要等待用户确认）
- 结论以 markdown 列表/段落呈现，便于主代理拼接
"""


@dataclass
class SubAgentTask:
    """一个子代理任务定义。"""

    goal: str
    """子代理要完成的具体目标（自然语言）。"""

    allowed_tools: list[str] | None = None
    """工具白名单。None 表示使用所有工具（除了 delegate_subagents）。"""

    max_subturns: int = 20
    """最大轮次。"""

    timeout_seconds: int = 600
    """整体超时（10 分钟）。"""


@dataclass
class SubAgentResult:
    """子代理执行结果。"""

    goal: str
    success: bool
    final_text: str
    turns: int = 0
    tool_calls_count: int = 0
    error: str | None = None
    elapsed_seconds: float = 0.0
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "success": self.success,
            "result": self.final_text,
            "turns": self.turns,
            "tool_calls": self.tool_calls_count,
            "elapsed": round(self.elapsed_seconds, 2),
            "error": self.error,
        }


class SubAgent:
    """轻量化子代理：独立循环，共享底层资源。"""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        memory_block: str = "",
        tool_timeout: int = 60,
        max_retries: int = 1,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.memory_block = memory_block
        self.tool_timeout = tool_timeout
        self.max_retries = max_retries

    def _build_system_prompt(self) -> str:
        parts = [SUBAGENT_SYSTEM_PROMPT]
        if self.memory_block.strip():
            parts.append("\n# 共享 MEMORY（只读）\n" + self.memory_block)
        return "\n".join(parts)

    def _filter_tools_schema(self, all_tools: list[dict], allowed: list[str] | None) -> list[dict]:
        """过滤工具：排除会污染主代理状态的工具，可选再叠加白名单。

        Bug 2 (Coco 报告) 修复：原版本只排除 delegate_subagents，但子代理仍然能调
        memory_manage / skill_manage / project_delete 篡改主代理的持久状态。
        子 agent 应只读使用主 agent 的 memory，不能写。
        """
        result = []
        for t in all_tools:
            name = t.get("function", {}).get("name", "")
            if name in _SUBAGENT_BLOCKED_TOOLS:
                continue
            if allowed is not None and name not in allowed:
                continue
            result.append(t)
        return result

    async def run(self, task: SubAgentTask) -> SubAgentResult:
        """执行一个子任务，返回结构化结果。"""
        import time

        start = time.monotonic()

        messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": task.goal},
        ]
        all_schema = self.registry.get_tools_schema()
        tools_schema = self._filter_tools_schema(all_schema, task.allowed_tools)

        turns = 0
        tool_calls_count = 0
        final_text = ""
        error: str | None = None

        try:
            while turns < task.max_subturns:
                turns += 1
                response = await self.llm.chat(
                    messages=messages,
                    tools=tools_schema if tools_schema else None,
                )
                if response is None:
                    error = "LLM 返回 None"
                    break

                choice = response.choices[0]  # type: ignore[attr-defined]
                msg = choice.message

                assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    assistant_msg["reasoning_content"] = reasoning

                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ]
                messages.append(assistant_msg)

                if not msg.tool_calls:
                    final_text = msg.content or ""
                    break

                for tc in msg.tool_calls:
                    tool_calls_count += 1
                    result = await self.registry.execute(
                        tc.function.name,
                        tc.function.arguments,
                        timeout=self.tool_timeout,
                        max_retries=self.max_retries,
                        silent=True,
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                error = f"达到最大轮次 {task.max_subturns}"
        except APIBalanceError as e:
            error = f"API 余额不足: {e.message}"
        except Exception as e:
            err = classify_llm_error(e) if "llm" in str(e).lower() else None
            error = f"{type(e).__name__}: {err or e}"
            log_warning(f"子代理 [{task.goal[:30]}...] 异常: {error}")

        elapsed = time.monotonic() - start
        return SubAgentResult(
            goal=task.goal,
            success=error is None and bool(final_text),
            final_text=final_text or "（无最终输出）",
            turns=turns,
            tool_calls_count=tool_calls_count,
            error=error,
            elapsed_seconds=elapsed,
            messages=messages,
        )


class SubAgentOrchestrator:
    """并行调度多个子代理。"""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        memory_block: str = "",
        max_concurrency: int = 4,
        tool_timeout: int = 60,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.memory_block = memory_block
        self.max_concurrency = max_concurrency
        self.tool_timeout = tool_timeout

    async def run_parallel(self, tasks: list[SubAgentTask]) -> list[SubAgentResult]:
        """并行运行所有子任务。返回与输入顺序对应的结果列表。"""
        if not tasks:
            return []

        log_info(f"子代理并行启动: {len(tasks)} 个任务，并发上限 {self.max_concurrency}")
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _runner(task: SubAgentTask) -> SubAgentResult:
            async with semaphore:
                agent = SubAgent(
                    llm=self.llm,
                    registry=self.registry,
                    memory_block=self.memory_block,
                    tool_timeout=self.tool_timeout,
                )
                try:
                    return await asyncio.wait_for(agent.run(task), timeout=task.timeout_seconds)
                except TimeoutError:
                    return SubAgentResult(
                        goal=task.goal,
                        success=False,
                        final_text="",
                        error=f"超时 ({task.timeout_seconds}s)",
                    )

        results = await asyncio.gather(*(_runner(t) for t in tasks), return_exceptions=False)

        ok = sum(1 for r in results if r.success)
        log_info(f"子代理并行完成: {ok}/{len(results)} 成功")
        return results

    @staticmethod
    def format_results_for_main(results: list[SubAgentResult]) -> str:
        """把子代理结果格式化成主代理可读的工具响应文本。"""
        lines = [f"已完成 {len(results)} 个子任务:\n"]
        for i, r in enumerate(results, 1):
            status = "✓" if r.success else "✗"
            lines.append(
                f"\n--- 子任务 {i} {status} ({r.turns} 轮, {r.tool_calls_count} 工具调用, {r.elapsed_seconds:.1f}s) ---"
            )
            lines.append(f"目标: {r.goal}")
            if r.error:
                lines.append(f"错误: {r.error}")
            if r.final_text:
                lines.append(f"结论:\n{r.final_text}")
        return "\n".join(lines)


__all__ = [
    "SUBAGENT_SYSTEM_PROMPT",
    "SubAgent",
    "SubAgentOrchestrator",
    "SubAgentResult",
    "SubAgentTask",
]


# 用于 ToolRegistry 注入的全局单例引用
# 主 engine 启动时注入 self.subagent_orchestrator
_global_orchestrator: SubAgentOrchestrator | None = None


def set_global_orchestrator(orch: SubAgentOrchestrator | None) -> None:
    """注入全局编排器实例（由 engine 启动时调用）。"""
    global _global_orchestrator
    _global_orchestrator = orch


def get_global_orchestrator() -> SubAgentOrchestrator | None:
    return _global_orchestrator


def parse_tasks_from_args(tasks_arg: list | str) -> list[SubAgentTask]:
    """把 LLM 传来的 tasks 参数解析为 SubAgentTask 列表。

    支持两种格式：
    - JSON 字符串: '[{"goal": "...", "allowed_tools": ["..."]}, ...]'
    - 已解析的列表: [{"goal": "...", ...}, ...]
    """
    if isinstance(tasks_arg, str):
        try:
            tasks_arg = json.loads(tasks_arg)
        except json.JSONDecodeError as e:
            raise ValueError(f"tasks 不是合法 JSON: {e}") from e

    if not isinstance(tasks_arg, list):
        raise ValueError("tasks 必须是列表")

    result = []
    for i, item in enumerate(tasks_arg):
        if isinstance(item, str):
            # 简化形式：直接传 goal 字符串
            result.append(SubAgentTask(goal=item))
        elif isinstance(item, dict):
            goal = item.get("goal", "").strip()
            if not goal:
                raise ValueError(f"任务 {i}: goal 不能为空")
            result.append(
                SubAgentTask(
                    goal=goal,
                    allowed_tools=item.get("allowed_tools"),
                    max_subturns=int(item.get("max_subturns", 20)),
                    timeout_seconds=int(item.get("timeout_seconds", 600)),
                )
            )
        else:
            raise ValueError(f"任务 {i}: 必须是字符串或字典")
    return result
