"""Argus Real-World Capability Eval — 一次性评测脚本。

实施 plan 文件 argus-real-world-eval-623653.md：
  A 段（垂直能力）3 run · scan
  B 段（多模型）   3 run · recon · 同 target
  C 段（边界）     2 run · scan/recon

每个 run 子进程跑 main.py，捕获指标，最终落盘到 docs/eval/<UTC>/。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent


@dataclass
class Run:
    run_id: str
    section: str  # A / B / C
    label: str
    target: str
    mode: str
    model: str | None  # None = 用 config 默认
    timeout: int
    note: str = ""
    # 填充结果
    status: str = ""
    elapsed_s: float = 0.0
    tokens: int = 0
    turns: int = 0
    tool_calls: int = 0
    report_path: str = ""
    report_bytes: int = 0
    top3_count: int = 0
    severe_keywords: int = 0
    sections: int = 0
    subdomains_found: int = 0
    ports_found: int = 0
    early_stop: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Run matrix
# ──────────────────────────────────────────────────────────────────────────

RUNS: list[Run] = [
    # A 段：scan 模式垂直深度
    Run("A1", "A", "DVWA local", "http://127.0.0.1:8080", "scan", None, 200,
        "本地 DVWA 容器，已知含 setup.php / MySQL / SQLi"),
    Run("A2", "A", "IBM Altoro", "http://demo.testfire.net", "scan", None, 200,
        "IBM 公开授权银行靶场（SQLi 登录绕过 / XSS）"),
    Run("A3", "A", "itsecgames", "http://www.itsecgames.com", "scan", None, 200,
        "bWAPP 作者站点，含 vuln demo 路径"),
    # B 段：同 target / 同 recon 模式 / 三模型对比
    Run("B1", "B", "DeepSeek V4 Flash", "http://demo.testfire.net", "recon",
        "deepseek/deepseek-v4-flash", 150, "性价比基线"),
    Run("B2", "B", "DeepSeek V4 Pro", "http://demo.testfire.net", "recon",
        "deepseek/deepseek-v4-pro", 200, "强推理对照"),
    Run("B3", "B", "MiMo V2.5 Pro", "http://demo.testfire.net", "recon",
        "xiaomi_mimo/mimo-v2.5-pro", 200, "百万上下文 / Token Plan"),
    # C 段：边界
    Run("C1", "C", "Cloudflare WAF", "https://cloudflare.com", "scan", None, 200,
        "首页直接 403，看 Argus 整链路对 WAF 反应"),
    Run("C2", "C", "Microsoft 大场", "https://microsoft.com", "recon", None, 150,
        "wildcard DNS 假阳性 + 子域规模考验"),
]


# ──────────────────────────────────────────────────────────────────────────
# 指标抽取
# ──────────────────────────────────────────────────────────────────────────


def _safe_target_filename(target: str) -> str:
    return target.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")


def _latest_report(target: str) -> Path | None:
    home = Path.home() / ".argus" / "output" / "reports"
    if not home.exists():
        return None
    safe = _safe_target_filename(target)
    matches = sorted(home.glob(f"report_{safe}*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _extract_token_total(log: str) -> int:
    matches = re.findall(r"Tokens:\s*~?(\d+)", log)
    return int(matches[-1]) if matches else 0


def _extract_turns(log: str) -> int:
    matches = re.findall(r"Turn\s+(\d+)\s*\|\s*Tokens", log)
    return int(matches[-1]) if matches else 0


def _extract_tool_calls(log: str) -> int:
    return len(re.findall(r"\[Tool\]", log))


def _extract_early_stop(log: str) -> list[str]:
    out = []
    if re.search(r"WAF|限流|rate.?limit", log, re.IGNORECASE):
        out.append("WAF/rate-limit")
    if re.search(r"墙钟|wall.?budget|wall.?clock", log, re.IGNORECASE):
        out.append("wall-budget")
    if re.search(r"不可达|unreachable", log, re.IGNORECASE):
        out.append("unreachable")
    if re.search(r"wildcard", log, re.IGNORECASE):
        out.append("wildcard-filter")
    return out


def _count_top3(text: str) -> int:
    m = re.search(r"##\s+🎯\s+执行摘要[^\n]*\n+((?:\|[^\n]*\n)+)", text)
    if not m:
        return 0
    rows = [line for line in m.group(1).splitlines() if line.lstrip().startswith("|")]
    return max(0, len(rows) - 2)


def _count_severe_keywords(text: str) -> int:
    return len(re.findall(r"🔴|🟠|严重|高危|critical", text, re.IGNORECASE))


def _count_sections(text: str) -> int:
    return len(re.findall(r"^##\s+", text, re.MULTILINE))


def _extract_findings(text: str) -> tuple[int, int]:
    sub_m = re.search(r"发现\s*(\d+)\s*/\s*\d+", text)
    subs = int(sub_m.group(1)) if sub_m else 0
    ports = len(re.findall(r"\b\d{1,5}/tcp\s+open\b", text, re.IGNORECASE))
    return subs, ports


# ──────────────────────────────────────────────────────────────────────────
# 跑一个 run
# ──────────────────────────────────────────────────────────────────────────


def execute_run(run: Run, *, eval_dir: Path) -> Run:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    cmd = [sys.executable, str(_REPO / "main.py"), "--yolo",
           "-t", run.target, "--mode", run.mode]
    if run.model:
        cmd.extend(["--model", run.model])

    print(f"\n[{run.run_id}] {run.label} → {run.target} ({run.mode})", flush=True)
    print(f"      model={run.model or '(default)'}  timeout={run.timeout}s", flush=True)

    t0 = time.monotonic()
    log_text = ""
    try:
        result = subprocess.run(
            cmd, cwd=str(_REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=run.timeout, env=env,
        )
        run.status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
        log_text = (result.stdout or "") + "\n" + (result.stderr or "")
    except subprocess.TimeoutExpired as e:
        run.status = "timeout"
        log_text = (str(e.stdout or "") + "\n" + str(e.stderr or ""))

    run.elapsed_s = round(time.monotonic() - t0, 1)
    run.tokens = _extract_token_total(log_text)
    run.turns = _extract_turns(log_text)
    run.tool_calls = _extract_tool_calls(log_text)
    run.early_stop = _extract_early_stop(log_text)

    # 写日志
    log_path = eval_dir / f"{run.run_id}_log.txt"
    log_path.write_text(log_text, encoding="utf-8", errors="replace")

    # 拷报告
    rp = _latest_report(run.target)
    if rp and rp.exists():
        dst = eval_dir / f"{run.run_id}_report.md"
        shutil.copy2(rp, dst)
        run.report_path = str(dst.name)
        run.report_bytes = dst.stat().st_size
        text = dst.read_text(encoding="utf-8", errors="replace")
        run.top3_count = _count_top3(text)
        run.severe_keywords = _count_severe_keywords(text)
        run.sections = _count_sections(text)
        subs, ports = _extract_findings(text)
        run.subdomains_found = subs
        run.ports_found = ports

    print(f"      → {run.status}  {run.elapsed_s}s  {run.tokens} tok  "
          f"turns={run.turns}  tools={run.tool_calls}  "
          f"top3={run.top3_count}  sections={run.sections}  "
          f"early={','.join(run.early_stop) or '-'}", flush=True)
    return run


# ──────────────────────────────────────────────────────────────────────────
# Summary 渲染
# ──────────────────────────────────────────────────────────────────────────


def _section_table(runs: list[Run], title: str, columns: list[tuple[str, str]]) -> str:
    """columns: list of (header, attr_path). attr_path is dot-notation."""
    lines = [f"## {title}", ""]
    lines.append("| " + " | ".join(c[0] for c in columns) + " |")
    lines.append("|" + "|".join("---" for _ in columns) + "|")
    for r in runs:
        cells: list[str] = []
        for _, path in columns:
            val: Any = r
            for k in path.split("."):
                val = getattr(val, k, "")
            if isinstance(val, list):
                val = ",".join(val) if val else "-"
            cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_summary(runs: list[Run], eval_dir: Path) -> str:
    a = [r for r in runs if r.section == "A"]
    b = [r for r in runs if r.section == "B"]
    c = [r for r in runs if r.section == "C"]

    out = [
        "# Argus Real-World Capability Eval",
        "",
        f"- 运行时间（UTC）: **{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}**",
        f"- 总 run 数: **{len(runs)}**",
        f"- 成功率: **{sum(1 for r in runs if r.status == 'ok')}/{len(runs)}**",
        f"- 总耗时: **{sum(r.elapsed_s for r in runs):.1f}s**",
        f"- 总 token: **{sum(r.tokens for r in runs):,}**",
        f"- 总报告大小: **{sum(r.report_bytes for r in runs):,} B**",
        "",
    ]

    out.append(_section_table(
        a,
        "A 段 — 垂直能力（scan 模式）",
        [
            ("ID", "run_id"),
            ("标的", "label"),
            ("耗时", "elapsed_s"),
            ("turns", "turns"),
            ("tools", "tool_calls"),
            ("token", "tokens"),
            ("报告(B)", "report_bytes"),
            ("Top-3", "top3_count"),
            ("章节", "sections"),
            ("严重词", "severe_keywords"),
            ("端口", "ports_found"),
            ("早停", "early_stop"),
            ("状态", "status"),
        ],
    ))

    out.append(_section_table(
        b,
        "B 段 — 多模型同题（recon · demo.testfire.net）",
        [
            ("ID", "run_id"),
            ("模型", "label"),
            ("耗时", "elapsed_s"),
            ("turns", "turns"),
            ("tools", "tool_calls"),
            ("token", "tokens"),
            ("报告(B)", "report_bytes"),
            ("Top-3", "top3_count"),
            ("章节", "sections"),
            ("状态", "status"),
        ],
    ))

    out.append(_section_table(
        c,
        "C 段 — 边界鲁棒性",
        [
            ("ID", "run_id"),
            ("场景", "label"),
            ("目标", "target"),
            ("耗时", "elapsed_s"),
            ("turns", "turns"),
            ("tools", "tool_calls"),
            ("token", "tokens"),
            ("早停", "early_stop"),
            ("子域", "subdomains_found"),
            ("状态", "status"),
        ],
    ))

    out.append("## 报告链接")
    out.append("")
    for r in runs:
        if r.report_path:
            out.append(f"- **{r.run_id}** {r.label}: [{r.report_path}](./{r.report_path})  ({r.report_bytes} B)")
        else:
            out.append(f"- **{r.run_id}** {r.label}: _无报告_（{r.status}）")
    out.append("")

    out.append("## 客观信号自动抽取")
    out.append("")

    # B 段对比洞察
    if len(b) >= 2:
        out.append("### B 段模型对比要点")
        out.append("")
        sorted_b = sorted(b, key=lambda r: r.elapsed_s)
        out.append(f"- 最快：**{sorted_b[0].label}** ({sorted_b[0].elapsed_s}s)")
        out.append(f"- 最省 token：**{min(b, key=lambda r: r.tokens or 1e9).label}** "
                   f"({min((r.tokens for r in b if r.tokens), default=0)} tok)")
        out.append(f"- 报告最丰富：**{max(b, key=lambda r: r.report_bytes).label}** "
                   f"({max(r.report_bytes for r in b)} B)")
        out.append(f"- 工具调用最多：**{max(b, key=lambda r: r.tool_calls).label}** "
                   f"({max(r.tool_calls for r in b)} 次)")
        out.append("")

    # C 段早停
    if c:
        out.append("### C 段早停触发情况")
        out.append("")
        for r in c:
            out.append(f"- **{r.run_id}** {r.label}: {','.join(r.early_stop) or '无'}")
        out.append("")

    out.append("## 主观评分（手工填补）")
    out.append("")
    out.append("> 此节预留给运行者结合各报告内容评分。")
    out.append("")
    out.append("| 维度 | 权重 | A1 | A2 | A3 | B1 | B2 | B3 | C1 | C2 |")
    out.append("|---|---:|---|---|---|---|---|---|---|---|")
    out.append("| 真实性（漏洞实存） | 30% | | | | | | | | |")
    out.append("| 可读性（卡片+建议） | 25% | | | | | | | | |")
    out.append("| 调度（工具切换合理） | 20% | | | | | | | | |")
    out.append("| 鲁棒性（早停/超时） | 15% | | | | | | | | |")
    out.append("| 成本（token/byte） | 10% | | | | | | | | |")
    out.append("| **总分** | 100% | | | | | | | | |")
    out.append("")

    return "\n".join(out) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    eval_dir = _REPO / "docs" / "eval" / stamp
    eval_dir.mkdir(parents=True, exist_ok=True)
    print("=== Argus Real-World Eval ===")
    print(f"输出目录: {eval_dir}")
    print(f"总 run 数: {len(RUNS)}")

    t0 = time.monotonic()
    completed: list[Run] = []
    for run in RUNS:
        completed.append(execute_run(run, eval_dir=eval_dir))

    total = time.monotonic() - t0

    # 写原始指标
    raw_path = eval_dir / "raw_metrics.json"
    raw_path.write_text(
        json.dumps([asdict(r) for r in completed], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 写 summary
    summary = render_summary(completed, eval_dir)
    summary_path = eval_dir / "summary.md"
    summary_path.write_text(summary, encoding="utf-8")

    print("\n=== 完成 ===")
    print(f"总耗时: {total:.1f}s")
    print(f"summary: {summary_path}")
    print(f"raw:     {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
