"""Day5: 冷烟基准 —— 对 N 个真实公网目标顺序跑 recon 模式，输出一张性能表。

用法：
    python scripts/cold_smoke.py                        # 默认目标列表
    python scripts/cold_smoke.py a.com b.com            # 自定义
    python scripts/cold_smoke.py --out bench.md         # 自定义输出文件

输出 markdown 表到 docs/benchmarks/<UTC-时间戳>.md（或 --out 指定路径）：

    | 目标 | 耗时 | tokens | 报告大小 | Top-3 | 子域 | 端口 | 状态 |

不做实时日志流（各目标独立进程），不重试，失败只记录退出码。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGETS = [
    "example.com",
    "iana.org",
    "cloudflare.com",
    "github.com",
    "python.org",
    "nginx.org",
    "apache.org",
    "rust-lang.org",
    "debian.org",
    "openssh.com",
]


def _latest_report(target: str) -> Path | None:
    """找 target 的最新 report_*.md（在 ~/.argus/output/reports/）。"""
    home = Path.home() / ".argus" / "output" / "reports"
    if not home.exists():
        return None
    safe = target.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
    matches = sorted(home.glob(f"report_{safe}_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _count_top3(report_text: str) -> int:
    """抓 "## 🎯 执行摘要 Top-3" 下的表格行数（不含 header）。"""
    m = re.search(r"##\s+🎯\s+执行摘要[^\n]*\n\n((?:\|[^\n]*\n)+)", report_text)
    if not m:
        return 0
    rows = [line for line in m.group(1).splitlines() if line.startswith("|")]
    # 去掉 header + separator
    return max(0, len(rows) - 2)


def _extract_token_total(log_text: str) -> int:
    """从日志里找最后一行 'Turn N | Tokens: ~XXXX' 的 tokens。"""
    matches = re.findall(r"Tokens:\s*~?(\d+)", log_text)
    if not matches:
        return 0
    return int(matches[-1])


def _extract_findings(report_text: str) -> dict[str, int]:
    """粗数子域 / 端口发现。"""
    out = {"subdomains": 0, "ports": 0}
    # 子域：look for "发现 N/M"
    m = re.search(r"发现\s*(\d+)\s*/\s*\d+", report_text)
    if m:
        out["subdomains"] = int(m.group(1))
    # 开放端口
    out["ports"] = len(re.findall(r"\b\d{1,5}/tcp\s+open\b", report_text, re.IGNORECASE))
    return out


def run_one(target: str, *, mode: str = "recon", timeout: int = 180) -> dict:
    """跑一个目标，返回指标 dict。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, str(_REPO_ROOT / "main.py"), "--yolo", "-t", target, "--mode", mode]
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
        log_text = (result.stdout or "") + "\n" + (result.stderr or "")
    except subprocess.TimeoutExpired as e:
        status = "timeout"

        def _to_str(x: object) -> str:
            if x is None:
                return ""
            if isinstance(x, bytes):
                return x.decode("utf-8", errors="replace")
            return str(x)

        log_text = _to_str(e.stdout) + "\n" + _to_str(e.stderr)
    elapsed = time.monotonic() - start

    tokens = _extract_token_total(log_text)
    report_path = _latest_report(target)
    report_size = 0
    top3 = 0
    findings = {"subdomains": 0, "ports": 0}
    if report_path and report_path.exists():
        report_size = report_path.stat().st_size
        report_text = report_path.read_text(encoding="utf-8", errors="replace")
        top3 = _count_top3(report_text)
        findings = _extract_findings(report_text)

    return {
        "target": target,
        "mode": mode,
        "elapsed_s": round(elapsed, 1),
        "tokens": tokens,
        "report_bytes": report_size,
        "top3": top3,
        "subdomains": findings["subdomains"],
        "ports": findings["ports"],
        "status": status,
    }


def render_table(rows: list[dict], *, meta: dict | None = None) -> str:
    lines: list[str] = []
    lines.append("# Argus Cold-Smoke Benchmark")
    lines.append("")
    if meta:
        lines.append(f"- 运行时间（UTC）: **{meta['ran_at']}**")
        lines.append(f"- 模型: `{meta.get('model', '(default)')}`")
        lines.append(f"- 模式: `{meta.get('mode', 'recon')}`")
        lines.append(f"- 目标数: **{len(rows)}**")
        lines.append("")

    lines.append("| # | 目标 | 耗时(s) | tokens | 报告(B) | Top-3 | 子域 | 端口 | 状态 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | `{r['target']}` | {r['elapsed_s']} | {r['tokens']} | "
            f"{r['report_bytes']} | {r['top3']} | {r['subdomains']} | "
            f"{r['ports']} | {r['status']} |"
        )

    ok = [r for r in rows if r["status"] == "ok"]
    if ok:
        avg_s = sum(r["elapsed_s"] for r in ok) / len(ok)
        avg_tok = sum(r["tokens"] for r in ok) / len(ok)
        avg_rep = sum(r["report_bytes"] for r in ok) / len(ok)
        lines.append("")
        lines.append("## 汇总（仅成功项）")
        lines.append("")
        lines.append(f"- 成功率: **{len(ok)}/{len(rows)}**")
        lines.append(f"- 平均耗时: **{avg_s:.1f}s**")
        lines.append(f"- 平均 tokens: **{avg_tok:.0f}**")
        lines.append(f"- 平均报告大小: **{avg_rep:.0f} B**")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Argus cold-smoke benchmark")
    parser.add_argument("targets", nargs="*", help="目标列表；留空 = 默认 10 个公网站点")
    parser.add_argument("--mode", default="recon", choices=["recon", "scan", "full"])
    parser.add_argument("--timeout", type=int, default=180, help="单目标超时（秒）")
    parser.add_argument("--out", help="输出文件；默认 docs/benchmarks/<UTC>.md")
    args = parser.parse_args()

    targets = args.targets or DEFAULT_TARGETS
    rows: list[dict] = []
    t0 = time.monotonic()
    for i, tgt in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {tgt} …", flush=True)
        row = run_one(tgt, mode=args.mode, timeout=args.timeout)
        print(
            f"    → {row['status']}  {row['elapsed_s']}s  {row['tokens']} tok  "
            f"report={row['report_bytes']}B  top3={row['top3']}",
            flush=True,
        )
        rows.append(row)

    print(f"\n总耗时: {time.monotonic() - t0:.1f}s")

    ran_at = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    md = render_table(rows, meta={"ran_at": ran_at, "mode": args.mode})

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = _REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"{stamp}.md"

    out_path.write_text(md, encoding="utf-8")
    print(f"\n✓ 已写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
