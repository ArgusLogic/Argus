"""Day2-3: 从 LESSONS.md 选取与本次目标相关的 Top-N 教训，渲染成报告底部块。

启发式选择：按目标域名/IP 关键词出现次数排序，无相关时随机取最近 3 条。
零 LLM 调用。设计目标：让用户看到 "Argus 记得这次教训了"。
"""

from __future__ import annotations

import re
from pathlib import Path

# LESSONS.md 用 § 作为条目分隔符（见 agent/memory_md.py SEP）
_SEP = "§"


def _lessons_path() -> Path:
    """运行时解析 LESSONS_MD_PATH，配合测试 fixture 的路径隔离。"""
    from utils.paths import LESSONS_MD_PATH

    return Path(LESSONS_MD_PATH)


def _read_lessons_entries() -> list[str]:
    """读取所有 lesson 条目；文件不存在或为空返 []。"""
    p = _lessons_path()
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    # 跳过首部 "# Lessons Learned" 标题
    body = re.sub(r"^#[^\n]*\n", "", text, count=1).strip()
    if not body:
        return []
    raw = [chunk.strip() for chunk in body.split(_SEP)]
    return [r for r in raw if r]


def _score_lesson(lesson: str, keywords: list[str]) -> int:
    """命中关键词数 + 启发式信号，越高越相关。"""
    if not keywords:
        return 0
    score = 0
    lower = lesson.lower()
    for kw in keywords:
        kw = kw.lower().strip()
        if kw and kw in lower:
            score += 2
    return score


def _extract_keywords(target: str) -> list[str]:
    """从 target 提取可匹配关键词：root domain + tld + 类型词。"""
    target = target.strip().lower()
    target = re.sub(r"^https?://", "", target)
    target = target.split("/")[0]
    if not target:
        return []
    keywords: list[str] = [target]
    parts = target.split(".")
    if len(parts) >= 2:
        keywords.append(".".join(parts[-2:]))  # root domain
        keywords.append(parts[-1])  # tld
    return list(set(keywords))


def select_relevant_lessons(target: str, top_n: int = 3) -> list[str]:
    """挑选与目标相关的 top_n 条 lessons。无相关或无文件返回 []。"""
    entries = _read_lessons_entries()
    if not entries:
        return []
    keywords = _extract_keywords(target)
    scored = [(e, _score_lesson(e, keywords)) for e in entries]
    # 优先有命中的；同分按文件里的原始顺序保留
    relevant = [(e, s) for e, s in scored if s > 0]
    relevant.sort(key=lambda x: x[1], reverse=True)
    if relevant:
        return [e for e, _ in relevant[:top_n]]
    # 无相关 → 不渲染（避免噪声）
    return []


def render_lessons_block(target: str, top_n: int = 3) -> str:
    """渲染 lessons 命中 markdown 块；无命中返空串。"""
    items = select_relevant_lessons(target, top_n=top_n)
    if not items:
        return ""
    lines = ["## 💡 本次命中的避坑教训\n"]
    lines.append("> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。\n")
    for i, item in enumerate(items, 1):
        # 单条 lesson 可能跨多行 —— 保留首行作为标题，其余缩进
        lines_in_lesson = item.splitlines()
        lines.append(f"{i}. {lines_in_lesson[0].strip()}")
        for line in lines_in_lesson[1:]:
            stripped = line.strip()
            if stripped:
                lines.append(f"   {stripped}")
    return "\n".join(lines) + "\n"
