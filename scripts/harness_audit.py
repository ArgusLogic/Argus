"""B-1 量化审计：统计 BASE_PERSONA 段落分布 + 52 工具 description 分布。

运行：python scripts/harness_audit.py
输出：docs/harness_audit/persona_audit.json
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import tiktoken  # noqa: E402

from agent.prompts import BASE_PERSONA  # noqa: E402
from agent.tool_registry import registry  # noqa: E402

_enc = tiktoken.get_encoding("cl100k_base")


def tok(s: str) -> int:
    return len(_enc.encode(s))


def split_persona_sections(text: str) -> list[tuple[str, str]]:
    """按 markdown ## 标题切段，返回 [(title, body)]。第一段是 H1 之前的部分。"""
    parts: list[tuple[str, str]] = []
    lines = text.split("\n")
    cur_title = "(开头)"
    cur_buf: list[str] = []
    for line in lines:
        m = re.match(r"^##+\s+(.+?)$", line)
        if m:
            if cur_buf:
                parts.append((cur_title, "\n".join(cur_buf).strip()))
            cur_title = m.group(1).strip()
            cur_buf = []
        else:
            cur_buf.append(line)
    if cur_buf:
        parts.append((cur_title, "\n".join(cur_buf).strip()))
    return parts


def audit_base_persona() -> dict:
    sections = split_persona_sections(BASE_PERSONA)
    total_tok = tok(BASE_PERSONA)
    rows = []
    for title, body in sections:
        t = tok(body)
        rows.append({
            "title": title,
            "chars": len(body),
            "tokens": t,
            "ratio_pct": round(100 * t / max(1, total_tok), 1),
        })
    return {
        "total_chars": len(BASE_PERSONA),
        "total_tokens": total_tok,
        "sections": rows,
    }


def audit_tool_descriptions() -> dict:
    registry.auto_discover("tools")
    rows = []
    for name in sorted(registry._tools.keys()):
        info = registry._tools[name]
        desc = info.get("description", "")
        params = info.get("params", {}) or {}
        rows.append({
            "name": name,
            "desc_chars": len(desc),
            "desc_tokens": tok(desc),
            "param_count": len(params),
            "param_doc_chars": sum(
                len(p.get("description", "")) for p in params.values() if isinstance(p, dict)
            ),
        })
    desc_chars = [r["desc_chars"] for r in rows]
    desc_tokens = [r["desc_tokens"] for r in rows]
    desc_chars_sorted = sorted(rows, key=lambda r: r["desc_chars"])
    return {
        "tool_count": len(rows),
        "desc_chars": {
            "min": min(desc_chars),
            "p50": statistics.median(desc_chars),
            "p99": int(statistics.quantiles(desc_chars, n=100)[98])
            if len(desc_chars) > 1 else max(desc_chars),
            "max": max(desc_chars),
            "mean": round(statistics.mean(desc_chars), 1),
        },
        "desc_tokens_total": sum(desc_tokens),
        "bottom_10": [
            {"name": r["name"], "desc_chars": r["desc_chars"], "desc": registry._tools[r["name"]]["description"]}
            for r in desc_chars_sorted[:10]
        ],
        "top_10": [
            {"name": r["name"], "desc_chars": r["desc_chars"]}
            for r in desc_chars_sorted[-10:]
        ],
        "all": rows,
    }


def audit_run_logs() -> dict:
    """扫 docs/eval/* 找 *_log.txt，统计反复出现的失败模式 + 工具调用频率。"""
    eval_root = _REPO / "docs" / "eval"
    if not eval_root.exists():
        return {"log_count": 0}
    logs = list(eval_root.rglob("*_log.txt"))
    if not logs:
        return {"log_count": 0}

    # 失败模式 keyword
    failure_kws = {
        "timeout": r"timeout|超时|超过最大执行时间",
        "tool_not_registered": r"工具未注册|ToolNotFound",
        "param_error": r"参数错误|TypeError|missing.*argument",
        "json_parse": r"JSONDecodeError|Expecting value",
        "auth_fail": r"登录失败|auth_login.*失败|认证失败",
        "early_stop_waf": r"WAF|rate.?limit|限流",
        "early_stop_wildcard": r"wildcard-filter|wildcard_dns",
        "browser_closed": r"target.?closed|broken.?pipe|page.*closed",
        "404_path": r"404 ",
        "json_invalid_tool_call": r"invalid.*tool.*call|tool_calls.*invalid",
    }
    counts = dict.fromkeys(failure_kws, 0)
    tool_freq: dict[str, int] = {}
    log_data = []
    for log_path in sorted(logs)[-30:]:  # 取最近 30 个
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for kw, pat in failure_kws.items():
            if re.search(pat, text, re.IGNORECASE):
                counts[kw] += 1
        for m in re.finditer(r"\[Tool\] (\w+)", text):
            tool_freq[m.group(1)] = tool_freq.get(m.group(1), 0) + 1
        log_data.append({
            "path": str(log_path.relative_to(_REPO)),
            "size": len(text),
        })
    return {
        "log_count": len(logs),
        "scanned": len(log_data),
        "failure_modes": counts,
        "tool_frequency_top15": sorted(tool_freq.items(), key=lambda x: -x[1])[:15],
    }


def main() -> int:
    out_dir = _REPO / "docs" / "harness_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "base_persona": audit_base_persona(),
        "tool_descriptions": audit_tool_descriptions(),
        "run_logs": audit_run_logs(),
    }
    (out_dir / "persona_audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 打印摘要
    bp = report["base_persona"]
    td = report["tool_descriptions"]
    rl = report["run_logs"]
    print("=== BASE_PERSONA ===")
    print(f"total: {bp['total_chars']} chars / {bp['total_tokens']} tokens")
    print(f"sections: {len(bp['sections'])}")
    for s in bp["sections"]:
        print(f"  {s['ratio_pct']:>5}% [{s['tokens']:>4}t] {s['title']}")

    print("\n=== TOOL DESCRIPTIONS ===")
    print(f"count={td['tool_count']}, total_tokens={td['desc_tokens_total']}")
    print(f"chars: min={td['desc_chars']['min']}, p50={td['desc_chars']['p50']}, "
          f"max={td['desc_chars']['max']}, mean={td['desc_chars']['mean']}")
    print("Bottom 10 (shortest):")
    for r in td["bottom_10"]:
        print(f"  {r['desc_chars']:>3}c  {r['name']:<28} {r['desc'][:60]}")

    print("\n=== RUN LOGS ===")
    print(f"logs={rl.get('log_count')}, scanned={rl.get('scanned', 0)}")
    if "failure_modes" in rl:
        print("Failure modes (count of logs hit):")
        for k, v in sorted(rl["failure_modes"].items(), key=lambda x: -x[1]):
            print(f"  {v:>3}  {k}")
    if "tool_frequency_top15" in rl:
        print("Top 15 tools (by call freq across logs):")
        for name, cnt in rl["tool_frequency_top15"]:
            print(f"  {cnt:>4}  {name}")

    print(f"\nJSON: {out_dir / 'persona_audit.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
