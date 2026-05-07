"""B2 — 轻量用户建模（Honcho 替代）。

输入：最近 N 个 session 的对话片段。
输出：1-4 条用户画像条目，写入 MemoryMD.user。

要点：
- 复用主 LLM（无独立配置）
- 默认关闭（需 LLM 调用）
- 失败静默吞掉（log_warning）

只调一次 LLM，prompt 极简（每会话仅取首尾两条 user/assistant 文本，避免上下文爆炸）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm_client import LLMClient
from agent.memory_md import MemoryMD
from utils.logger import file_logger, log_warning

_USER_PROFILE_SYSTEM_PROMPT = """你是 Argus Agent 的"用户建模助手"。

输入：用户最近若干次会话的简短摘要（每条含 user 提问 + assistant 回复首尾片段）。
任务：归纳出 1-4 条**稳定的、可跨会话沿用**的用户画像（preferences/profile），格式严格如下：

只回复一个 JSON 数组（无任何其它文字）：

[
  "短句 1（≤80 字）",
  "短句 2",
  ...
]

判断准则：
- 偏好语言、报告格式、沟通风格（如"喜欢中文""偏好简洁回答"）
- 关注的领域 / 目标类型（如"主要做电商站点侦察""关注 SSRF 漏洞"）
- 工作时段、技术背景

绝**不**写：
- 单次具体目标域名 / IP
- 任何敏感数据（API Key、Token、密码）
- 临时上下文

如果信息不足以归纳出任何稳定偏好，返回空数组 []。
"""


def summarize_session_messages(messages: list[dict[str, Any]], max_chars: int = 600) -> str:
    """把一个 session 的 messages 压缩成一段简短摘要。"""
    if not messages:
        return ""
    snippets: list[str] = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role == "user" and content:
            snippets.append(f"USER: {content[:200]}")
        elif role == "assistant" and content:
            snippets.append(f"AGENT: {content[:200]}")
    text = "\n".join(snippets)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(截断)"


async def update_user_profile_async(
    llm: LLMClient,
    memory_md: MemoryMD,
    session_summaries: list[str],
    timeout: float = 30.0,
) -> list[str]:
    """跑一次用户建模；返回新增条目列表。

    fire-and-forget 用法：调用方应吞掉异常。
    """
    import asyncio

    if not session_summaries:
        return []

    payload = "\n\n--- session ---\n".join(session_summaries[-10:])
    user_msg = f"以下是最近会话摘要：\n{payload}"
    messages = [
        {"role": "system", "content": _USER_PROFILE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    try:
        response = await asyncio.wait_for(
            llm.chat(messages=messages, temperature=0.0),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""  # type: ignore[attr-defined]
        m = re.search(r"\[.*?\]", content, re.DOTALL)
        if not m:
            return []
        entries: Any = json.loads(m.group(0))
        if not isinstance(entries, list):
            return []
        added: list[str] = []
        for entry in entries:
            if not isinstance(entry, str) or not entry.strip():
                continue
            res = memory_md.add("user", entry.strip(), silent=True)
            if res.get("ok"):
                added.append(entry.strip())
        if added:
            file_logger.write("INFO", f"自演化 B2: user profile 新增 {len(added)} 条")
        return added
    except Exception as e:
        log_warning(f"user profile 更新失败: {e}")
        return []
