"""端到端 eval：精准验收 Stage 1 / 2 / 3。

四个 run：
  A1 DVWA scan     — 验 Stage 1 信号库扩充（Top-3 是否真的上浮 setup.php / 3306）
  A2 AltoroJ scan  — 验 Stage 1（Top-3 是否上浮 swagger / jsessionid）
  D1 DVWA + auth   — 验 Stage 2 (auth_login) + Stage 3 (vuln_sqli_timing)
  D2 AltoroJ + auth— 验 Stage 2 + Stage 3 (vuln_xss_reflection)

A 段复用 eval_runner.execute_run（子进程跑 main.py）。
D 段直接调 AgentEngine（独立 prompt 控制工具调用顺序）。

输出：docs/eval/<UTC>/{A1,A2,D1,D2}_{log.txt,report.md} + summary.md + findings_e2e.md
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from scripts.eval_runner import (  # noqa: E402
    Run,
    _count_severe_keywords,
    _count_top3,
    _latest_report,
    execute_run,
)

# D 段的 prompt 设计：strict numbered steps，让 LLM 按顺序调工具
_D1_PROMPT = """对本机 DVWA 靶场执行授权漏洞验证（已配置 credentials.toml）。请严格按以下顺序：

1. 调 `credentials_lookup(host="127.0.0.1:8080")` 取占位符
2. 调 `auth_login(login_url="http://127.0.0.1:8080/login.php", username="${CRED_127_0_0_1_8080_USER}", password="${CRED_127_0_0_1_8080_PASS}", success_indicator="DVWA")` 登录
3. 登录成功后用 `browser_navigate("http://127.0.0.1:8080/security.php")` 把安全级别先降到 low（如有降级表单则用 browser_fill / browser_click）
4. 调 `vuln_sqli_timing(url="http://127.0.0.1:8080/vulnerabilities/sqli/?id=1&Submit=Submit", param="id")` 测时间盲注
5. 用 generate_report 汇总结果（target = "http://127.0.0.1:8080"）

完成后输出一句话总结，含 vuln_sqli_timing 是否检测到漏洞。"""

_D2_PROMPT = """对 demo.testfire.net 靶场执行授权 XSS 探测（已配置 credentials.toml）。请严格按以下顺序：

1. 调 `credentials_lookup(host="demo.testfire.net")` 取占位符
2. 调 `auth_login(login_url="http://demo.testfire.net/login.jsp", username="${CRED_demo_testfire_net_USER}", password="${CRED_demo_testfire_net_PASS}", success_indicator="logout")` 登录
3. 调 `vuln_xss_reflection(url="http://demo.testfire.net/search.jsp?query=test", param="query")` 探 XSS
4. 用 generate_report 汇总（target = "http://demo.testfire.net"）

完成后输出一句话总结，含 vuln_xss_reflection 的命中情况。"""


@dataclass
class DRun:
    run_id: str
    label: str
    target: str
    prompt: str
    timeout: int = 300
    # 填充
    status: str = ""
    elapsed_s: float = 0.0
    tokens: int = 0
    turns: int = 0
    tool_calls_total: int = 0
    tool_call_names: list[str] = field(default_factory=list)
    auth_login_called: bool = False
    auth_login_success: bool = False
    vuln_called: bool = False
    vuln_vulnerable: bool = False
    vuln_summary: str = ""
    report_path: str = ""
    report_bytes: int = 0
    top3_count: int = 0
    severe_keywords: int = 0
    final_text: str = ""


# ──────────────────────────────────────────────────────────────────────────
# D 段：直接调 AgentEngine
# ──────────────────────────────────────────────────────────────────────────


async def execute_d_run(d: DRun, *, eval_dir: Path, model: str) -> DRun:
    """在子进程外直接驱动 AgentEngine 跑 D 段 prompt。"""
    from agent.engine import AgentEngine
    from agent.llm_client import LLMClient
    from agent.tool_registry import registry
    from utils.config import get_config
    from utils.logger import file_logger

    # 自动发现工具
    registry.auto_discover("tools")

    cfg = get_config()
    api_keys = cfg.get("api_keys", {})
    api_bases = cfg.get("api_bases", {})

    print(f"\n[{d.run_id}] {d.label} → {d.target}", flush=True)
    print(f"      model={model}  timeout={d.timeout}s", flush=True)

    file_logger.enable()
    t0 = time.monotonic()
    final_text = ""
    try:
        llm = LLMClient(model=model, api_keys=api_keys, api_bases=api_bases)
        engine = AgentEngine(
            llm=llm,
            registry=registry,
            approval_mode=False,  # yolo
            verbose=True,
            tool_timeout=120,
            max_retries=1,
            allowed_domains=[],  # 走 credentials.toml 授权路径
            context_max_tokens=200000,
            track_skill_usage=False,
            track_lessons=False,
            auto_extract_skills=False,
        )
        try:
            final_text = await asyncio.wait_for(
                engine.run_stream(d.prompt, ui=None), timeout=d.timeout
            )
            d.status = "ok"
        except TimeoutError:
            d.status = "timeout"
            final_text = "[D 段超时]"

        # 抽工具调用记录
        tool_calls: list[str] = []
        tool_results: dict[str, list[str]] = {}
        for m in engine.messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fname = (tc.get("function") or {}).get("name", "")
                    if fname:
                        tool_calls.append(fname)
            elif m.get("role") == "tool" and tool_calls:
                # 反查最近一个 assistant 的 tool_calls 找 name
                fname = tool_calls[-1]
                content = str(m.get("content", ""))
                tool_results.setdefault(fname, []).append(content)

        d.tool_calls_total = len(tool_calls)
        d.tool_call_names = tool_calls
        d.auth_login_called = "auth_login" in tool_calls

        # 检测 auth_login 成功
        for content in tool_results.get("auth_login", []):
            if "登录成功" in content:
                d.auth_login_success = True
                break

        # 检测 vuln_* 调用 + vulnerable
        vuln_tools = ("vuln_sqli_timing", "vuln_xss_reflection",
                      "vuln_open_redirect", "vuln_cors_misconfig")
        d.vuln_called = any(t in tool_calls for t in vuln_tools)
        for vt in vuln_tools:
            if vt in tool_results:
                for content in tool_results[vt]:
                    try:
                        # 工具返回 JSON 字符串
                        # 先去掉可能的前缀
                        json_str = content[content.find("{"):content.rfind("}") + 1]
                        if json_str:
                            obj = json.loads(json_str)
                            if obj.get("vulnerable") is True:
                                d.vuln_vulnerable = True
                                d.vuln_summary = (
                                    f"{vt}: vulnerable=True"
                                    + (f", confidence={obj['confidence']}"
                                       if "confidence" in obj else "")
                                )
                                break
                            else:
                                d.vuln_summary = f"{vt}: vulnerable=False"
                    except (ValueError, json.JSONDecodeError):
                        continue

        # token / turns
        try:
            from agent.errors import classify_llm_error  # noqa: F401
            # turns ≈ assistant 消息数
            d.turns = sum(1 for m in engine.messages if m.get("role") == "assistant")
        except Exception:
            pass

    except Exception as e:
        d.status = f"exception: {type(e).__name__}: {e}"
        final_text = str(e)
    finally:
        file_logger.close()

    d.elapsed_s = round(time.monotonic() - t0, 1)
    d.final_text = final_text[:400] if final_text else ""

    # 写日志
    log_path = eval_dir / f"{d.run_id}_log.txt"
    log_lines = [
        f"=== {d.run_id} {d.label} ===",
        f"target: {d.target}",
        f"model: {model}",
        f"status: {d.status}",
        f"elapsed_s: {d.elapsed_s}",
        f"turns: {d.turns}",
        f"tool_calls ({d.tool_calls_total}): {' / '.join(d.tool_call_names)}",
        f"auth_login_called: {d.auth_login_called}",
        f"auth_login_success: {d.auth_login_success}",
        f"vuln_called: {d.vuln_called}",
        f"vuln_vulnerable: {d.vuln_vulnerable}",
        f"vuln_summary: {d.vuln_summary}",
        "",
        "--- final_text ---",
        d.final_text,
    ]
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    # 拷贝最新报告
    rp = _latest_report(d.target)
    if rp and rp.exists() and rp.stat().st_mtime >= t0:
        dst = eval_dir / f"{d.run_id}_report.md"
        shutil.copy2(rp, dst)
        d.report_path = dst.name
        d.report_bytes = dst.stat().st_size
        text = dst.read_text(encoding="utf-8", errors="replace")
        d.top3_count = _count_top3(text)
        d.severe_keywords = _count_severe_keywords(text)

    print(
        f"      → {d.status}  {d.elapsed_s}s  turns={d.turns}  "
        f"tools={d.tool_calls_total}  "
        f"auth={'✓' if d.auth_login_success else '✗'}  "
        f"vuln={'✓' if d.vuln_vulnerable else '✗'}",
        flush=True,
    )
    return d


# ──────────────────────────────────────────────────────────────────────────
# Top-3 提取：从报告 markdown 抓首位 key + severity
# ──────────────────────────────────────────────────────────────────────────


_SEVERITY_LABELS = {
    "🔴 严重": "critical",
    "🔴 高": "high",
    "🟠 中": "medium",
    "🟡 低": "low",
    "🔵 提示": "info",
}


def parse_top1(report_text: str) -> tuple[str, str]:
    """返回 (severity, risk_text)，未命中返回 ('', '')。"""
    m = re.search(r"##\s+🎯\s+执行摘要[^\n]*\n+\|[^\n]+\n\|[-:\s|]+\n\|([^\n]+)", report_text)
    if not m:
        return "", ""
    first_row = m.group(1)
    cells = [c.strip() for c in first_row.split("|") if c.strip()]
    if len(cells) < 2:
        return "", ""
    sev_cell, risk_cell = cells[0], cells[1]
    severity = ""
    for label, name in _SEVERITY_LABELS.items():
        if label in sev_cell:
            severity = name
            break
    return severity, risk_cell


# ──────────────────────────────────────────────────────────────────────────
# Findings 渲染
# ──────────────────────────────────────────────────────────────────────────


def render_findings(a_runs: list[Run], d_runs: list[DRun], eval_dir: Path) -> str:
    lines = [
        "# Argus 端到端 Eval — Stage 1+2+3 验收",
        "",
        f"- 时间（UTC）: **{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}**",
        "- 运行: A1+A2+D1+D2 = 4 run",
        f"- 总耗时: **{sum(r.elapsed_s for r in a_runs) + sum(d.elapsed_s for d in d_runs):.1f}s**",
        "",
    ]

    # ── A 段（Stage 1）──
    lines.append("## A 段 — Stage 1（Top-3 信号库扩充）验收")
    lines.append("")
    lines.append("| ID | 标的 | 状态 | 耗时 | turns | tools | Top-3 计数 | 报告 B |")
    lines.append("|---|---|---|---|---|---|---|---|")
    a_top1: dict[str, tuple[str, str]] = {}
    for r in a_runs:
        report_path = eval_dir / f"{r.run_id}_report.md"
        sev, risk = "", ""
        if report_path.exists():
            sev, risk = parse_top1(report_path.read_text(encoding="utf-8"))
        a_top1[r.run_id] = (sev, risk)
        lines.append(
            f"| {r.run_id} | {r.label} | {r.status} | {r.elapsed_s}s | "
            f"{r.turns} | {r.tool_calls} | {r.top3_count} | {r.report_bytes} |"
        )
    lines.append("")
    lines.append("### Stage 1 Top-1 验收")
    lines.append("")
    lines.append("| ID | severity | 风险 |")
    lines.append("|---|---|---|")
    stage1_pass = False
    for run_id, (sev, risk) in a_top1.items():
        lines.append(f"| {run_id} | {sev or '?'} | {risk[:80] if risk else '(no Top-1)'} |")
        if sev in ("critical", "high"):
            stage1_pass = True
    lines.append("")
    lines.append(
        f"**Stage 1 结论**: {'✅ PASS' if stage1_pass else '❌ FAIL'} — "
        f"{'A1 或 A2 至少一个 Top-1 升级到 critical/high' if stage1_pass else '所有 Top-1 仍在 medium 或更低'}"
    )
    lines.append("")

    # ── D 段（Stage 2 + 3）──
    lines.append("## D 段 — Stage 2 (auth_login) + Stage 3 (vuln_scan) 验收")
    lines.append("")
    lines.append(
        "| ID | 标的 | 状态 | 耗时 | turns | tools | auth_login | 登录✓ | vuln_called | vuln✓ | 报告 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in d_runs:
        lines.append(
            f"| {d.run_id} | {d.label} | {d.status} | {d.elapsed_s}s | "
            f"{d.turns} | {d.tool_calls_total} | "
            f"{'✓' if d.auth_login_called else '✗'} | "
            f"{'✓' if d.auth_login_success else '✗'} | "
            f"{'✓' if d.vuln_called else '✗'} | "
            f"{'✓' if d.vuln_vulnerable else '✗'} | "
            f"{d.report_bytes if d.report_bytes else '-'} |"
        )
    lines.append("")

    stage2_pass = any(d.auth_login_success for d in d_runs)
    stage3_pass = any(d.vuln_vulnerable for d in d_runs)
    lines.append(
        f"**Stage 2 结论**: {'✅ PASS' if stage2_pass else '❌ FAIL'} — "
        f"D 段 {'至少一次 auth_login 登录成功' if stage2_pass else '所有 auth_login 均未确认成功'}"
    )
    lines.append(
        f"**Stage 3 结论**: {'✅ PASS' if stage3_pass else '⚠ PARTIAL/FAIL'} — "
        f"D 段 {'至少一个 vuln_* 报 vulnerable=true' if stage3_pass else '所有 vuln_* 均未确认 vulnerable=true（有可能目标已修复或工具未触发）'}"
    )
    lines.append("")

    # ── D 段调用链详情 ──
    lines.append("## D 段工具调用链")
    lines.append("")
    for d in d_runs:
        lines.append(f"### {d.run_id} — {d.label}")
        lines.append(f"- 工具调用顺序: `{' → '.join(d.tool_call_names) or '（无）'}`")
        lines.append(f"- vuln_summary: `{d.vuln_summary or '（无）'}`")
        lines.append(f"- final_text 摘录: {d.final_text[:200].strip() or '（无）'}")
        lines.append("")

    # ── 总评 ──
    lines.append("## 总评")
    lines.append("")
    overall_pass = stage1_pass and stage2_pass and stage3_pass
    lines.append(
        f"- **三阶段全部 PASS**: {'✅ 是' if overall_pass else '❌ 否'}"
    )
    lines.append(
        f"- Stage 1: {'PASS' if stage1_pass else 'FAIL'} · "
        f"Stage 2: {'PASS' if stage2_pass else 'FAIL'} · "
        f"Stage 3: {'PASS' if stage3_pass else 'FAIL/PARTIAL'}"
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────


async def main_async() -> int:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    eval_dir = _REPO / "docs" / "eval" / f"{stamp}_e2e"
    eval_dir.mkdir(parents=True, exist_ok=True)
    print("=== Argus E2E Eval (Stage 1+2+3) ===")
    print(f"输出目录: {eval_dir}")

    model = "xiaomi_mimo/mimo-v2.5-pro"

    # A 段
    a_runs = [
        Run("A1", "A", "DVWA local", "http://127.0.0.1:8080", "scan", model, 240,
            "Stage 1 验收：DVWA Top-3 期望升级到 setup.php / 3306"),
        Run("A2", "A", "IBM AltoroJ", "http://demo.testfire.net", "scan", model, 240,
            "Stage 1 验收：AltoroJ Top-3 期望升级到 swagger / jsessionid"),
    ]
    for run in a_runs:
        execute_run(run, eval_dir=eval_dir)

    # D 段
    d_runs = [
        DRun("D1", "DVWA login + sqli", "http://127.0.0.1:8080", _D1_PROMPT, timeout=300),
        DRun("D2", "AltoroJ login + xss", "http://demo.testfire.net", _D2_PROMPT, timeout=300),
    ]
    for d in d_runs:
        await execute_d_run(d, eval_dir=eval_dir, model=model)

    # raw metrics
    raw = {
        "A": [asdict(r) for r in a_runs],
        "D": [asdict(d) for d in d_runs],
    }
    (eval_dir / "raw_metrics.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # findings
    findings_path = eval_dir / "findings_e2e.md"
    findings_path.write_text(render_findings(a_runs, d_runs, eval_dir), encoding="utf-8")

    print("\n=== 完成 ===")
    print(f"findings: {findings_path}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
