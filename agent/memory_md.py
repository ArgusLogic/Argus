"""MD 文件式持久记忆（Hermes 风格）。

两个文件：
- MEMORY.md  — Agent 的工作笔记（环境事实、项目惯例、踩坑、任务日志）
- USER.md    — 用户画像（偏好、沟通风格、技能水平、雷区）

格式：
    # Argus Memory

    第一条记忆内容
    可以多行
    §
    第二条记忆内容
    §
    第三条记忆内容

§ 是 entry 分隔符（U+00A7 SECTION SIGN）。
冻结注入：会话开始时读一次注入到 system prompt，中途修改不影响 prompt（保 prefix cache）。
"""

import os
from typing import Literal

from utils.logger import log_info, log_warning
from utils.paths import MEMORIES_DIR, MEMORY_MD_PATH, USER_MD_PATH

SEP = "§"
TARGET = Literal["memory", "user"]

# 字符容量上限
CAP_MEMORY = 2200
CAP_USER = 1500

# 文件头部标题
_HEADERS = {
    "memory": "# Argus Memory",
    "user": "# User Profile",
}


class MemoryMD:
    """读/写 MEMORY.md 和 USER.md，提供 add / replace / remove / 容量统计。"""

    def __init__(self):
        os.makedirs(MEMORIES_DIR, exist_ok=True)

    # ─── 路径 / 容量 ─────────────────────────────────────────────────

    @staticmethod
    def _path(target: str) -> str:
        if target == "memory":
            return MEMORY_MD_PATH
        if target == "user":
            return USER_MD_PATH
        raise ValueError(f"未知 target: {target}（可用: memory / user）")

    @staticmethod
    def _cap(target: str) -> int:
        return CAP_MEMORY if target == "memory" else CAP_USER

    # ─── 读取 / 解析 ─────────────────────────────────────────────────

    def _read_raw(self, target: str) -> str:
        path = self._path(target)
        if not os.path.exists(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            log_warning(f"读取 {target} 记忆失败: {e}")
            return ""

    def list_entries(self, target: str) -> list[str]:
        """返回所有条目（已剔除头部，按 § 切分，去空白）。

        热路径：优先使用 Rust 实现 (argus_native.parse_entries)，加速 3-5×。
        """
        raw = self._read_raw(target)
        if not raw.strip():
            return []

        # Rust 加速路径
        from utils._native import parse_entries as _native_parse
        if _native_parse is not None:
            return _native_parse(raw)

        # 纯 Python fallback
        body_lines = []
        for line in raw.splitlines():
            if line.startswith("#") and not body_lines:
                continue
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if not body:
            return []
        return [e.strip() for e in body.split(SEP) if e.strip()]

    def used_chars(self, target: str) -> int:
        """已用字符数（按 entry 内容计算，不算分隔符）。"""
        return sum(len(e) for e in self.list_entries(target))

    def stats(self, target: str) -> dict:
        used = self.used_chars(target)
        cap = self._cap(target)
        pct = round(used / cap * 100) if cap else 0
        return {"used": used, "cap": cap, "pct": pct, "count": len(self.list_entries(target))}

    # ─── 写入 ───────────────────────────────────────────────────────

    def _write_entries(self, target: str, entries: list[str]) -> None:
        path = self._path(target)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        header = _HEADERS[target]
        body = f"\n{SEP}\n".join(entries)
        content = f"{header}\n\n{body}\n" if entries else f"{header}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ─── 操作 ───────────────────────────────────────────────────────

    def add(self, target: str, content: str, silent: bool = False) -> dict:
        """新增条目，返回 {ok, msg, stats}。silent=True 时不打印日志（用于迁移）。"""
        content = (content or "").strip()
        if not content:
            return {"ok": False, "msg": "content 不能为空"}

        entries = self.list_entries(target)

        # 精确去重
        if content in entries:
            return {"ok": False, "msg": "duplicate, no entry added", "stats": self.stats(target)}

        # 容量检查
        cap = self._cap(target)
        new_used = sum(len(e) for e in entries) + len(content)
        if new_used > cap:
            return {
                "ok": False,
                "msg": f"memory full ({new_used}/{cap}), please replace or remove first",
                "stats": self.stats(target),
            }

        entries.append(content)
        self._write_entries(target, entries)
        if not silent:
            log_info(f"记忆已添加 [{target}]: {content[:60]}")
        return {"ok": True, "msg": "added", "stats": self.stats(target)}

    def replace(self, target: str, old_text: str, content: str) -> dict:
        """子串匹配旧条目，整条替换为新 content。"""
        old_text = (old_text or "").strip()
        content = (content or "").strip()
        if not old_text or not content:
            return {"ok": False, "msg": "old_text 和 content 都不能为空"}

        entries = self.list_entries(target)
        matched_idx = None
        for i, e in enumerate(entries):
            if old_text in e:
                matched_idx = i
                break
        if matched_idx is None:
            return {"ok": False, "msg": f"no entry matched old_text: {old_text[:40]}"}

        # 容量检查
        cap = self._cap(target)
        new_used = sum(len(e) for e in entries) - len(entries[matched_idx]) + len(content)
        if new_used > cap:
            return {
                "ok": False,
                "msg": f"memory would overflow ({new_used}/{cap})",
                "stats": self.stats(target),
            }

        old_entry = entries[matched_idx]
        entries[matched_idx] = content
        self._write_entries(target, entries)
        log_info(f"记忆已替换 [{target}]: {old_entry[:40]} → {content[:40]}")
        return {"ok": True, "msg": "replaced", "stats": self.stats(target)}

    def remove(self, target: str, old_text: str) -> dict:
        """子串匹配并删除整条。"""
        old_text = (old_text or "").strip()
        if not old_text:
            return {"ok": False, "msg": "old_text 不能为空"}

        entries = self.list_entries(target)
        matched_idx = None
        for i, e in enumerate(entries):
            if old_text in e:
                matched_idx = i
                break
        if matched_idx is None:
            return {"ok": False, "msg": f"no entry matched old_text: {old_text[:40]}"}

        removed = entries.pop(matched_idx)
        self._write_entries(target, entries)
        log_info(f"记忆已删除 [{target}]: {removed[:60]}")
        return {"ok": True, "msg": "removed", "stats": self.stats(target)}

    # ─── 渲染（供 system prompt 注入） ─────────────────────────────────

    def render_block(self, target: str) -> str:
        """生成带容量条的注入块。"""
        s = self.stats(target)
        label = {"memory": "MEMORY (你的工作笔记)", "user": "USER (用户画像)"}[target]
        bar = "═" * 46
        header = f"{bar}\n{label} [{s['pct']}% — {s['used']}/{s['cap']} chars]\n{bar}"
        entries = self.list_entries(target)
        if not entries:
            return f"{header}\n(空)"
        body = f"\n{SEP}\n".join(entries)
        return f"{header}\n{body}"

    def render_full(self) -> str:
        """同时渲染 memory + user 两块。"""
        return self.render_block("memory") + "\n\n" + self.render_block("user")
