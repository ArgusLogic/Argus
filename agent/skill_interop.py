"""C3 — agentskills.io 兼容（导入/导出）。

agentskills.io 标准（[spec](https://agentskills.io/specification)）：
- 目录 `<skill-name>/SKILL.md`
- YAML frontmatter：name / description / license / compatibility / metadata / allowed-tools
- Markdown body

Argus 内部格式（JSON）：name / description / steps / content / success_count / pinned / ...

本模块提供：
- `to_agentskills(skill)` → 返回 SKILL.md 字符串（不写文件）
- `export_skill(skill, dest_dir)` → 写入 `dest_dir/<safe-name>/SKILL.md`
- `from_agentskills(text)` → 解析为 Argus skill dict
- `import_skill(path)` → 从 `<dir>/SKILL.md` 或单 .md 文件读入

只用标准库，避免 PyYAML 依赖（frontmatter 仅支持简单 key: value）。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from datetime import datetime
from typing import Any

# Argus name 用下划线，agentskills 用连字符。
_NAME_HYPHEN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def _argus_to_hyphen(name: str) -> str:
    """`recon_pipeline` → `recon-pipeline`，并校验长度 1-64。"""
    s = (name or "").strip().lower().replace("_", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] or "unnamed-skill"


def _hyphen_to_argus(name: str) -> str:
    """`recon-pipeline` → `recon_pipeline`。"""
    s = (name or "").strip().lower().replace("-", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed_skill"


# ─── Export: Argus → SKILL.md ───────────────────────────────────────────────


def to_agentskills(skill: dict[str, Any]) -> str:
    """渲染单个 Argus skill 为 SKILL.md 文本。"""
    name = _argus_to_hyphen(skill.get("name", "unnamed"))
    description = (skill.get("description") or "").strip()
    if not description:
        description = "No description provided."
    # frontmatter
    lines = ["---", f"name: {name}", f"description: {description}"]

    metadata_pairs: list[tuple[str, str]] = []
    if skill.get("success_count"):
        metadata_pairs.append(("argus-success-count", str(skill["success_count"])))
    steps = skill.get("steps", []) or []
    if steps:
        metadata_pairs.append(("argus-steps-count", str(len(steps))))
    if skill.get("created_at"):
        metadata_pairs.append(("argus-created-at", str(skill["created_at"])))
    if skill.get("pinned"):
        metadata_pairs.append(("argus-pinned", "true"))

    if metadata_pairs:
        lines.append("metadata:")
        for k, v in metadata_pairs:
            # 简化的 YAML：用 quote 包裹 value
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)}")

    lines.append("---")
    lines.append("")

    body_parts: list[str] = []
    content = (skill.get("content") or "").strip()
    if content:
        body_parts.append(content)
    if steps:
        body_parts.append("\n## Steps (auto-extracted)\n")
        for i, step in enumerate(steps, 1):
            tool = step.get("tool", "?")
            args = step.get("args_template", {})
            body_parts.append(f"{i}. `{tool}` — `{json.dumps(args, ensure_ascii=False)}`")
    if not body_parts:
        body_parts.append("(no body content)")

    lines.append("\n".join(body_parts))
    return "\n".join(lines) + "\n"


def export_skill(skill: dict[str, Any], dest_dir: str) -> str:
    """把 skill 导出到 `dest_dir/<name-hyphen>/SKILL.md`，返回写入的文件路径。"""
    name = _argus_to_hyphen(skill.get("name", "unnamed"))
    out_dir = os.path.join(dest_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_agentskills(skill))
    return path


# ─── Import: SKILL.md → Argus dict ──────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """极简 YAML frontmatter 解析。

    支持：
    - `key: value`
    - `key:` 后跟缩进 2 空格的 key: value 子项（仅 1 层嵌套，metadata 用）

    不支持：列表、多行字符串、复杂引用——这些在 agentskills 中也罕用。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_block, body = m.group(1), m.group(2)
    fm: dict[str, Any] = {}
    current_parent: str | None = None
    for raw in fm_block.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  ") and current_parent:
            sub_line = raw.strip()
            if ":" in sub_line:
                k, v = sub_line.split(":", 1)
                fm.setdefault(current_parent, {})[k.strip()] = _strip_quotes(v.strip())
            continue
        if ":" in raw:
            k, v = raw.split(":", 1)
            k = k.strip()
            v = v.strip()
            if not v:
                # 父键，准备接收子项
                current_parent = k
                fm[k] = {}
            else:
                current_parent = None
                fm[k] = _strip_quotes(v)
    return fm, body


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def from_agentskills(text: str) -> dict[str, Any]:
    """解析 SKILL.md 文本为 Argus skill dict。"""
    fm, body = _parse_frontmatter(text)
    raw_name = fm.get("name", "")
    if not raw_name:
        raise ValueError("SKILL.md frontmatter 缺 name 字段")
    if not _NAME_HYPHEN_RE.match(raw_name):
        raise ValueError(f"name 字段不符合 agentskills 规范: {raw_name!r}")

    metadata = fm.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    skill: dict[str, Any] = {
        "name": _hyphen_to_argus(raw_name),
        "description": fm.get("description", "").strip()[:1024],
        "content": body.strip(),
        "steps": [],
        "success_count": 0,
        "created_at": datetime.now().isoformat(),
        "imported_from": "agentskills.io",
    }
    # 还原 Argus 元数据
    if "argus-success-count" in metadata:
        with contextlib.suppress(ValueError, TypeError):
            skill["success_count"] = int(metadata["argus-success-count"])
    if metadata.get("argus-pinned") in ("true", "True", True):
        skill["pinned"] = True
    return skill


def import_skill(path: str) -> dict[str, Any]:
    """从 SKILL.md 文件路径或包含它的目录读入。"""
    if os.path.isdir(path):
        path = os.path.join(path, "SKILL.md")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"SKILL.md not found: {path}")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return from_agentskills(text)
