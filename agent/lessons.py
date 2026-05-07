"""A3 — 失败学习启发式提取器。

零 LLM 调用：扫描本轮 tool 消息内容，按关键词识别失败模式（WAF / 限流 /
403 / 超时 / captcha 等），生成简短 lesson 写入 LESSONS.md。

设计目标：
- **零成本**：纯字符串匹配，不调 LLM
- **低噪音**：同一目标 + 同一工具的失败合并为单条 lesson
- **可注入**：lesson 通过 MemoryMD.render_block("lessons") 进 system prompt
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urlparse

# 关键词 → 失败类型 映射
_FAILURE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:status[_\s]?code|http)?\s*4?03\b|forbidden", re.I), "403 Forbidden"),
    (
        re.compile(r"\b(?:status[_\s]?code|http)?\s*4?29\b|too many requests|rate[\s-]?limit", re.I),
        "限流 429",
    ),
    (re.compile(r"\b5\d\d\b|internal server error|bad gateway", re.I), "5xx 服务端错误"),
    (re.compile(r"timeout|timed[\s-]?out|执行超时", re.I), "超时"),
    (re.compile(r"\bwaf\b|cloudflare|akamai|incapsula|sucuri|aws[\s-]?waf", re.I), "WAF 拦截"),
    (re.compile(r"captcha|recaptcha|hcaptcha|cf[\s-]?challenge|verify you are human", re.I), "Captcha 验证"),
    (re.compile(r"connection refused|name (?:or service )?not known|net::err_", re.I), "连接错误"),
    (re.compile(r"blocked|denied|access\s+denied", re.I), "访问拒绝"),
]

# 工具名 → 该工具失败时常见目标参数键
_TARGET_KEYS = ("url", "domain", "target", "host")


def _extract_target(args_str: str | dict) -> str:
    """从工具参数中拿"目标"标识（域名/URL）。"""
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(args, dict):
        return ""
    for key in _TARGET_KEYS:
        val = args.get(key)
        if val and isinstance(val, str):
            # 把 URL 归一到 host
            if "://" in val:
                try:
                    return urlparse(val).netloc.split(":")[0].lower()
                except Exception:
                    return val
            return val.split(":")[0].lower()
    return ""


def _classify(content: str) -> str:
    """返回首个匹配的失败标签；没匹配返回空字符串。"""
    if not content:
        return ""
    for pattern, label in _FAILURE_PATTERNS:
        if pattern.search(content):
            return label
    return ""


def extract_lessons(messages: Iterable[dict]) -> list[str]:
    """扫描本轮 messages，返回失败 lesson 文本列表。

    一条 lesson 形如：`[2026-05] subdomain_enum on example.com → WAF 拦截`
    同一 (tool, target, label) 三元组只产出 1 条。
    """
    from datetime import datetime

    # 索引最近一次 assistant tool_calls，便于 tool result 配对
    pending: dict[str, tuple[str, str]] = {}  # tool_call_id → (tool_name, target)
    seen: set[tuple[str, str, str]] = set()
    lessons: list[str] = []

    msgs = list(messages)
    for msg in msgs:
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls", []) or []:
                tcid = tc.get("id", "")
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                target = _extract_target(func.get("arguments", "{}"))
                if tcid and tool_name:
                    pending[tcid] = (tool_name, target)
        elif role == "tool":
            tcid = msg.get("tool_call_id", "")
            content = msg.get("content", "") or ""
            label = _classify(content)
            if not label or tcid not in pending:
                continue
            tool_name, target = pending[tcid]
            key = (tool_name, target, label)
            if key in seen:
                continue
            seen.add(key)
            month = datetime.now().strftime("%Y-%m")
            target_str = target or "(unknown)"
            lessons.append(f"[{month}] {tool_name} on {target_str} → {label}（避免重复尝试或换策略）")

    return lessons
