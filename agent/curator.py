"""B1/B2 — Autonomous skill curator + user profile updater.

定时整理 skills 目录：
- **同名/相似合并**：description 相似度 ≥ 0.85 的多技能 → 保留 success_count 最高的，
  其它归档；success_count 累加到保留者。
- **陈旧归档**：success_count == 0 且 created_at 超过 archive_after_days 的技能 → 归档。
- **pinned 保护**：pinned=true 的技能 curator 不会动。
- **dry-run 报告**：每次跑完输出 `curator_reports/YYYYMMDD_HHMMSS.md`。

CLI：
    python -m agent.curator run [--dry-run]
    python -m agent.curator daemon --interval 24h

相似度算法：difflib.SequenceMatcher（标准库，零依赖，纯本地确定性）。
**不**调用 LLM，避免成本与外部依赖。
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from agent.skills import SkillManager
from utils.logger import log_error, log_info
from utils.paths import CURATOR_REPORTS_DIR

DEFAULT_SIMILARITY_THRESHOLD = 0.85
DEFAULT_ARCHIVE_AFTER_DAYS = 30


@dataclass
class CuratorReport:
    """单次 curator 执行结果。"""

    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    merged: list[dict[str, Any]] = field(default_factory=list)
    archived_stale: list[str] = field(default_factory=list)
    skipped_pinned: list[str] = field(default_factory=list)
    total_before: int = 0
    total_after: int = 0
    dry_run: bool = False

    def render_markdown(self) -> str:
        """生成 Markdown 报告。"""
        lines = [
            "# Curator Report",
            "",
            f"- Started: {self.started_at}",
            f"- Dry-run: {self.dry_run}",
            f"- Total skills: {self.total_before} → {self.total_after}",
            "",
        ]
        if self.merged:
            lines.append("## 合并")
            for m in self.merged:
                lines.append(
                    f"- **{m['kept']}** ⇐ 合并 {m['merged_into_kept']}（success_count: {m['success_total']}）"
                )
            lines.append("")
        if self.archived_stale:
            lines.append("## 归档（陈旧 + success_count==0）")
            for n in self.archived_stale:
                lines.append(f"- {n}")
            lines.append("")
        if self.skipped_pinned:
            lines.append("## 跳过（pinned）")
            for n in self.skipped_pinned:
                lines.append(f"- {n}")
            lines.append("")
        if not (self.merged or self.archived_stale):
            lines.append("> 本次 curator 未做任何变更。")
        return "\n".join(lines)


def _similarity(a: str, b: str) -> float:
    """SequenceMatcher 相似度（0.0-1.0），不区分大小写、忽略前后空白。"""
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _is_stale(created_at: str, days: int) -> bool:
    """created_at（ISO 字符串）距今是否超过 days 天。"""
    if not created_at:
        return False
    try:
        dt = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return False
    return (datetime.now() - dt) > timedelta(days=days)


def _group_similar(skills: list[dict[str, Any]], threshold: float) -> list[list[str]]:
    """按 description 相似度分组（贪心、Union-Find）。返回每组的 skill name 列表。

    pinned 技能不参与分组（独立）。
    """
    eligible = [s for s in skills if not s.get("pinned")]
    n = len(eligible)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            desc_i = eligible[i].get("description", "")
            desc_j = eligible[j].get("description", "")
            if desc_i and desc_j and _similarity(desc_i, desc_j) >= threshold:
                union(i, j)

    groups: dict[int, list[str]] = {}
    for i, s in enumerate(eligible):
        root = find(i)
        groups.setdefault(root, []).append(s["name"])

    # 仅保留有 ≥ 2 成员的组
    return [members for members in groups.values() if len(members) >= 2]


def run_curator(
    skills: SkillManager,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
    dry_run: bool = False,
) -> CuratorReport:
    """执行一次完整 curator 流程，返回结构化报告。"""
    report = CuratorReport(dry_run=dry_run)
    all_summaries = skills.list_skills()
    report.total_before = len(all_summaries)

    # 记录 pinned
    report.skipped_pinned = [s["name"] for s in all_summaries if s.get("pinned")]

    # ── 1. 同/相似 merge ──
    groups = _group_similar(all_summaries, similarity_threshold)
    summary_by_name = {s["name"]: s for s in all_summaries}

    for group in groups:
        # 选 success_count 最大者保留
        sorted_grp = sorted(
            group,
            key=lambda n: summary_by_name[n].get("success_count", 0),
            reverse=True,
        )
        keeper, others = sorted_grp[0], sorted_grp[1:]
        success_total = sum(summary_by_name[n].get("success_count", 0) for n in group)

        if not dry_run:
            kept = skills.get_skill(keeper)
            if kept is not None:
                kept["success_count"] = success_total
                skills.save_skill(kept)
            for other in others:
                skills.archive_skill(other)

        report.merged.append(
            {
                "kept": keeper,
                "merged_into_kept": others,
                "success_total": success_total,
            }
        )

    # ── 2. 陈旧归档（在 merge 之后做，对剩余技能再扫一遍）──
    remaining = skills.list_skills() if not dry_run else all_summaries
    keepers_set = {m["kept"] for m in report.merged}
    merged_set = {n for m in report.merged for n in m["merged_into_kept"]}

    for s in remaining:
        if s.get("pinned"):
            continue
        # 避免重复归档已被 merge 处理掉的
        if s["name"] in merged_set:
            continue
        if (
            s.get("success_count", 0) == 0
            and _is_stale(s.get("created_at", ""), archive_after_days)
            and s["name"] not in keepers_set
        ):
            if not dry_run:
                skills.archive_skill(s["name"])
            report.archived_stale.append(s["name"])

    final = skills.list_skills() if not dry_run else all_summaries
    report.total_after = (
        len(final)
        if not dry_run
        else (
            report.total_before
            - sum(len(m["merged_into_kept"]) for m in report.merged)
            - len(report.archived_stale)
        )
    )

    return report


def write_report(report: CuratorReport, reports_dir: str = CURATOR_REPORTS_DIR) -> str:
    """把报告写入 curator_reports/YYYYMMDD_HHMMSS.md。返回文件路径。"""
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_dry" if report.dry_run else ""
    path = os.path.join(reports_dir, f"{ts}{suffix}.md")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(report.render_markdown())
    except Exception as e:
        log_error(f"写 curator 报告失败: {e}")
    return path


# ─── CLI ────────────────────────────────────────────────────────────────────


def _parse_interval(s: str) -> float:
    """把 '24h' / '30m' / '7d' / '600' 解析为秒。"""
    s = s.strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("d"):
        return float(s[:-1]) * 86400
    return float(s)


async def _daemon_loop(
    interval_seconds: float,
    similarity: float,
    archive_after_days: int,
) -> None:
    """每隔 interval_seconds 跑一次 curator。"""
    skills = SkillManager()
    log_info(
        f"curator daemon 启动 — 间隔 {interval_seconds:.0f}s, "
        f"similarity={similarity}, archive_after_days={archive_after_days}"
    )
    while True:
        try:
            report = run_curator(
                skills,
                similarity_threshold=similarity,
                archive_after_days=archive_after_days,
            )
            path = write_report(report)
            log_info(
                f"curator 完成: 合并 {len(report.merged)} 组、归档 {len(report.archived_stale)} 条 → {path}"
            )
        except Exception as e:
            log_error(f"curator 运行异常: {e}")
        await asyncio.sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Argus skill curator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="单次跑 curator")
    p_run.add_argument("--dry-run", action="store_true", help="只生成报告不动文件")
    p_run.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    p_run.add_argument("--archive-after-days", type=int, default=DEFAULT_ARCHIVE_AFTER_DAYS)

    p_daemon = sub.add_parser("daemon", help="后台定时跑 curator")
    p_daemon.add_argument("--interval", default="24h", help="间隔，如 24h / 30m / 7d")
    p_daemon.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    p_daemon.add_argument("--archive-after-days", type=int, default=DEFAULT_ARCHIVE_AFTER_DAYS)

    args = parser.parse_args(argv)

    if args.cmd == "run":
        skills = SkillManager()
        report = run_curator(
            skills,
            similarity_threshold=args.similarity,
            archive_after_days=args.archive_after_days,
            dry_run=args.dry_run,
        )
        path = write_report(report)
        print(report.render_markdown())
        print(f"\n报告已写入: {path}")
        return 0

    if args.cmd == "daemon":
        try:
            asyncio.run(
                _daemon_loop(
                    _parse_interval(args.interval),
                    args.similarity,
                    args.archive_after_days,
                )
            )
        except KeyboardInterrupt:
            log_info("curator daemon 退出")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
