"""主代理调用：delegate_subagents — 并行运行 N 个子代理完成独立子任务。"""

from __future__ import annotations

from agent.subagent import (
    SubAgentOrchestrator,
    get_global_orchestrator,
    parse_tasks_from_args,
)
from agent.tool_registry import registry


@registry.tool(
    name="delegate_subagents",
    description=(
        "并行启动多个子代理（subagent）完成独立子任务。"
        "适用场景：需要对多个目标做相同/相似侦察（如 3 个域名分别做信息收集）、"
        "或一次任务可拆分为多个互不依赖的子目标。"
        "限制：子代理不能再调用 delegate_subagents（防递归）；MEMORY 是只读的。"
        "返回：所有子任务的结论汇总文本。"
    ),
    params={
        "tasks": {
            "type": "array",
            "description": (
                "子任务列表，每项为 {goal, allowed_tools?, max_subturns?, timeout_seconds?}。"
                "goal 是必需的自然语言目标描述。"
                "allowed_tools 可选，限制子代理可用的工具名列表。"
                "max_subturns 可选，默认 20。"
                "timeout_seconds 可选，默认 600。"
                "也支持简化形式：直接传字符串列表，每项当作 goal。"
            ),
        }
    },
)
async def delegate_subagents(tasks: list | str) -> str:
    """并行运行子代理。"""
    orch = get_global_orchestrator()
    if orch is None:
        return "错误: 子代理系统未初始化（engine 未注入 orchestrator）"

    try:
        task_list = parse_tasks_from_args(tasks)
    except ValueError as e:
        return f"错误: {e}"

    if len(task_list) == 0:
        return "错误: tasks 不能为空"
    if len(task_list) > 8:
        return f"错误: 一次最多 8 个子任务，当前 {len(task_list)} 个"

    results = await orch.run_parallel(task_list)
    return SubAgentOrchestrator.format_results_for_main(results)
