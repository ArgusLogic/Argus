"""A2 — 任务结束后自动提炼技能。

流程：
1. 启发式过滤（is_extraction_worthwhile）— 不调 LLM
2. LLM judge — 一次调用同时判断"值不值得提炼" + 给出 name + description
3. 去重 — 名称归一后查重；命中则跳过
4. 写入 skills/ — 调 SkillManager.save_skill

被 [skills] auto_extract 开关控制（默认关）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm_client import LLMClient
from agent.skills import SkillManager
from utils.logger import file_logger, log_warning

# 启发式阈值
MIN_TOOL_CALLS = 3  # 少于这么多次调用直接跳过
TOTAL_TIMEOUT_S = 60.0  # 整个提炼流程的硬上限（#15.9：防 fire-and-forget task 悬挂）

# LLM 提炼提示词
_EXTRACT_SYSTEM_PROMPT = """你是 Argus Agent 的"技能提炼助手"。

输入：一次会话中 Agent 完成的工具调用序列 + 最终回复。
任务：判断这次会话是否值得保存为可复用技能（skill），如果值得，给出简短的技能名和描述。

只回复一个 JSON 对象（不要任何额外文字、不要 markdown）：

{
  "worth_saving": true | false,
  "name": "蛇形命名_技能_名（仅在 worth_saving=true 时给出，3-5 个词，全小写下划线）",
  "description": "一句话描述这个技能做什么、什么场景用（仅在 worth_saving=true 时给出，<=60 字）"
}

判断准则（worth_saving=true 当且仅当）：
- 步骤 ≥3 步且形成清晰流程
- 流程通用（未来类似任务可复用）
- 不只是一次性调试或简单查询

否则 worth_saving=false。
"""


def is_extraction_worthwhile(messages: list[dict], final_text: str) -> bool:
    """启发式预过滤：避免无谓的 LLM 调用。"""
    if not final_text or not final_text.strip():
        return False
    tool_call_count = 0
    has_error = False
    for msg in messages:
        if msg.get("role") == "assistant":
            tool_call_count += len(msg.get("tool_calls", []) or [])
        elif msg.get("role") == "tool":
            content = msg.get("content", "") or ""
            # 简单判断：超过 30% 工具结果含 error/失败 → 视为失败回合
            if "error" in content.lower()[:200] or "执行失败" in content[:50]:
                has_error = True
    if tool_call_count < MIN_TOOL_CALLS:
        return False
    # 失败居多的会话不值得提炼成"成功流程"
    return not has_error


def normalize_name(name: str) -> str:
    """归一化技能名：lower + 仅保留字母数字下划线。"""
    s = (name or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return s.strip("_") or "unnamed_skill"


async def _judge_with_llm(
    llm: LLMClient,
    tool_names: list[str],
    final_text: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """调 LLM 判断 + 命名。返回 dict 或抛异常。"""
    import asyncio

    # 构建用户消息：仅传工具序列摘要 + final 摘要，避免泄露敏感数据
    final_snippet = final_text[:600]
    payload = {
        "tool_sequence": tool_names,
        "final_text_snippet": final_snippet,
    }
    user_msg = (
        "工具调用序列与最终回复摘要如下，请按系统提示词的规则判断:\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    response = await asyncio.wait_for(
        llm.chat(messages=messages, temperature=0.0),
        timeout=timeout,
    )
    content = response.choices[0].message.content or ""  # type: ignore[attr-defined]
    # 抽 JSON（可能被 markdown 包裹）
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise ValueError(f"LLM 返回非 JSON: {content[:200]}")
    return json.loads(m.group(0))


async def extract_skill_async(
    llm: LLMClient,
    skills: SkillManager,
    messages: list[dict],
    final_text: str,
) -> str | None:
    """主入口：自动提炼技能；返回新增/更新的技能名（或 None 表示跳过）。

    fire-and-forget：本函数捕获所有异常后写日志，不向调用方抛出。
    外层 `asyncio.wait_for` 兜底超时（#15.9），避免 LLM 底层卡住悬挂 task。
    """
    import asyncio

    try:
        return await asyncio.wait_for(
            _extract_skill_inner(llm, skills, messages, final_text),
            timeout=TOTAL_TIMEOUT_S,
        )
    except TimeoutError:
        log_warning(f"skill 自动提炼超时 (>{TOTAL_TIMEOUT_S}s)")
        return None
    except Exception as e:
        log_warning(f"skill 自动提炼失败: {e}")
        return None


async def _extract_skill_inner(
    llm: LLMClient,
    skills: SkillManager,
    messages: list[dict],
    final_text: str,
) -> str | None:
    try:
        if not is_extraction_worthwhile(messages, final_text):
            return None

        # 拿步骤序列 + 工具名
        steps = skills.extract_steps_from_messages(messages)
        tool_names = [s["tool"] for s in steps if s.get("tool")]
        if not tool_names:
            return None

        # LLM judge
        judgment = await _judge_with_llm(llm, tool_names, final_text)
        if not judgment.get("worth_saving"):
            file_logger.write("INFO", "自演化 A2: LLM 判定不值得提炼")
            return None

        raw_name = judgment.get("name", "")
        description = (judgment.get("description") or "").strip()
        name = normalize_name(raw_name)
        if not name or not description:
            file_logger.write("WARN", f"自演化 A2: LLM 返回不完整 name={raw_name!r} desc={description!r}")
            return None

        # 去重：名称完全相同 → 跳过；前缀匹配 → 也跳过避免越攒越多
        existing = skills.list_skills()
        existing_names = {s["name"] for s in existing}
        if name in existing_names:
            file_logger.write("INFO", f"自演化 A2: 跳过同名技能 {name}")
            return None

        # 保存新技能
        from datetime import datetime

        skill = {
            "name": name,
            "description": description,
            "steps": steps,
            "content": "",  # 留给 LLM 后续 patch/edit 补充
            "created_at": datetime.now().isoformat(),
            "success_count": 0,
            "extracted_by": "auto",
        }
        skills.save_skill(skill)
        file_logger.write("INFO", f"自演化 A2: 新技能已提炼 → {name}")
        return name
    except Exception as e:
        log_warning(f"skill 自动提炼失败: {e}")
        return None
