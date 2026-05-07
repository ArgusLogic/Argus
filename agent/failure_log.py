"""C2 — 失败请求结构化记录。

补充 A3 lessons（人类可读的避坑文本）的不足：C2 存的是**结构化、可复查**的失败记录：
- 工具名、参数（URL/domain/target）、失败标签、时间戳
- 写入 `~/.argus/failure_replays.jsonl`（追加日志，最多 N 条 FIFO）
- 提供按域名查询 + 渲染摘要给 system prompt

被 [memory] track_failure_replays 控制（默认关）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from agent.lessons import _classify, _extract_target
from utils.logger import file_logger
from utils.paths import SECAGENT_HOME

FAILURE_LOG_PATH = os.path.join(SECAGENT_HOME, "failure_replays.jsonl")
MAX_ENTRIES = 500


def _path() -> str:
    """返回当前 SECAGENT_HOME 下的 failure_replays.jsonl 路径。

    重新读 paths.SECAGENT_HOME 以兼容 conftest 的 monkeypatch。
    """
    from utils import paths as _paths

    return os.path.join(_paths.SECAGENT_HOME, "failure_replays.jsonl")


def append_failure(
    tool: str,
    target: str,
    label: str,
    args: str | dict[str, Any] | None = None,
    excerpt: str = "",
) -> None:
    """追加一条失败记录到 jsonl。"""
    if not tool or not label:
        return
    entry = {
        "ts": datetime.now().isoformat(),
        "tool": tool,
        "target": target or "",
        "label": label,
        "args": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False),
        "excerpt": (excerpt or "")[:200],
    }
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # FIFO 截断（条数超过 MAX_ENTRIES → 重写保留最后 MAX_ENTRIES 条）
        _rotate_if_needed(path)
    except Exception as e:
        file_logger.write("WARN", f"failure_log 写入失败: {e}")


def _rotate_if_needed(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_ENTRIES:
            lines = lines[-MAX_ENTRIES:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except Exception:
        pass


def load_failures() -> list[dict[str, Any]]:
    """读取所有失败记录（按时间升序）。"""
    path = _path()
    if not os.path.exists(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return out


def query_by_target(target: str, limit: int = 5) -> list[dict[str, Any]]:
    """按域名查询近 N 条失败（最新优先）。"""
    if not target:
        return []
    target = target.lower()
    matches = [f for f in load_failures() if (f.get("target") or "").lower() == target]
    return matches[-limit:][::-1]


def render_block_for_target(target: str, limit: int = 5) -> str:
    """生成给 system prompt 注入的失败摘要块（无目标命中则返回空串）。"""
    rows = query_by_target(target, limit=limit)
    if not rows:
        return ""
    bar = "═" * 46
    lines = [
        bar,
        f"FAILURE REPLAYS for {target} (历史避坑参考，最近 {len(rows)} 条)",
        bar,
    ]
    for r in rows:
        lines.append(f"- [{r.get('ts', '')[:16]}] {r.get('tool', '')} → {r.get('label', '')}")
    return "\n".join(lines)


def extract_and_log_failures(messages: list[dict[str, Any]]) -> int:
    """从一轮 messages 中扫描失败并写入 jsonl。返回新增条数。

    与 A3 lessons 的去重独立（C2 是逐条结构化记录，不去重）。
    """
    pending: dict[str, tuple[str, str, str]] = {}  # tcid → (tool, target, args)
    count = 0
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls", []) or []:
                tcid = tc.get("id", "")
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args_str = func.get("arguments", "{}")
                target = _extract_target(args_str)
                if tcid and tool_name:
                    pending[tcid] = (tool_name, target, args_str if isinstance(args_str, str) else "")
        elif role == "tool":
            tcid = msg.get("tool_call_id", "")
            content = msg.get("content", "") or ""
            label = _classify(content)
            if not label or tcid not in pending:
                continue
            tool_name, target, args_str = pending[tcid]
            append_failure(
                tool=tool_name,
                target=target,
                label=label,
                args=args_str,
                excerpt=content,
            )
            count += 1
    return count
