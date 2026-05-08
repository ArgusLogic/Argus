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
        "【作用】并行启动 ≤8 个子代理（subagent），每个独立跑自己的 goal，主代理拿到汇总文本继续。"
        "比 for 循环串行省 N 倍墙钟时间，且不占主代理上下文（每个子 agent 有自己的窗口）。"
        "【关键参数】tasks——子任务列表，每项 {goal, allowed_tools?, max_subturns?, timeout_seconds?}，或简化为 goal 字符串列表。"
        "allowed_tools 可限制子代理可用工具（推荐传以收敛行为）；max_subturns 默认 20；timeout_seconds 默认 600。"
        "【何时用】(1) 多目标同类侦察（'对 a.com / b.com / c.com 都做信息收集'）；"
        "(2) 同目标多个独立维度（DNS + 端口 + WHOIS 互不依赖）；(3) 探索性发散（多个子方向各跑）。"
        "【避坑】(1) 任务有顺序依赖（A 结果决定 B 输入）→ 不要 delegate，主代理串行；"
        "(2) 单一聚焦目标 → 直接做，delegate 反而增 overhead；"
        "(3) 子代理不能再 delegate（防递归爆炸）；"
        "(4) MEMORY 对子代理只读——它们不能写入持久记忆；"
        "(5) 一次最多 8 个，更多要分批；"
        "(6) 复杂任务建议把 max_subturns 调到 30+，默认 20 容易截断。"
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
