"""B5: 结构化项目存储。

每个项目对应 ~/.argus/projects/<name>.json，存任意 JSON 对象（目标 URL、已发现端点、
Cookie snapshot、备注等）。比 MEMORY.md 容量大、结构化、明确归属一个侦察目标。

与 MEMORY.md 的职责区分：
- MEMORY.md: LLM 自维护的非结构化笔记（短期、跨项目通用）
- project: 结构化目标状态（长期、单项目专用）
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from agent.tool_registry import registry
from utils.paths import SECAGENT_HOME
from utils.sanitizer import sanitize_filename

PROJECTS_DIR = os.path.join(SECAGENT_HOME, "projects")


def _project_path(name: str) -> str:
    safe = sanitize_filename(name)
    if not safe.endswith(".json"):
        safe += ".json"
    return os.path.join(PROJECTS_DIR, safe)


def _ensure_dir() -> None:
    os.makedirs(PROJECTS_DIR, exist_ok=True)


@registry.tool(
    name="project_save",
    description=(
        "保存项目侦察状态到 ~/.argus/projects/<name>.json。"
        "data 是任意 JSON 字符串：可存目标 URL、已发现端点、Cookie 快照、备注等。"
        "重复 save 同名项目会覆盖（同时记录 updated_at）。"
    ),
    params={
        "name": {
            "type": "string",
            "description": "项目名（如 'chaoxing-recon'），文件名会被规范化",
        },
        "data": {
            "type": "string",
            "description": "JSON 字符串，存项目结构化数据",
        },
    },
)
async def project_save(name: str, data: str) -> str:
    _ensure_dir()
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return f"data JSON 解析失败: {e}"

    if not isinstance(parsed, dict):
        return "data 必须是 JSON 对象 {}，不能是数组或基本类型"

    path = _project_path(name)
    now = datetime.now().isoformat(timespec="seconds")

    # 保留 created_at（如果文件已存在）
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            parsed.setdefault("created_at", old.get("created_at", now))
        except Exception:
            parsed.setdefault("created_at", now)
    else:
        parsed.setdefault("created_at", now)

    parsed["updated_at"] = now
    parsed["_project_name"] = name

    with open(path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    keys = ", ".join(k for k in parsed if not k.startswith("_") and k not in {"created_at", "updated_at"})
    return f"项目已保存: {name}\n文件: {path}\n键: {keys}"


@registry.tool(
    name="project_load",
    description="加载项目侦察状态。返回 JSON 字符串（含 created_at / updated_at 元信息）。",
    params={
        "name": {
            "type": "string",
            "description": "项目名",
        },
    },
)
async def project_load(name: str) -> str:
    path = _project_path(name)
    if not os.path.exists(path):
        return f"项目不存在: {name}"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"加载失败: {e}"
    return json.dumps(data, ensure_ascii=False, indent=2)


@registry.tool(
    name="project_list",
    description="列出所有已保存的项目（按 updated_at 倒序）。",
    params={},
)
async def project_list() -> str:
    _ensure_dir()
    items: list[tuple[str, str, str]] = []
    for f in os.listdir(PROJECTS_DIR):
        if not f.endswith(".json"):
            continue
        path = os.path.join(PROJECTS_DIR, f)
        try:
            with open(path, encoding="utf-8") as fh:
                obj: dict[str, Any] = json.load(fh)
            name = obj.get("_project_name", f[:-5])
            updated = obj.get("updated_at", "?")
            keys = ", ".join(
                k for k in obj if not k.startswith("_") and k not in {"created_at", "updated_at"}
            )
            items.append((updated, name, keys))
        except Exception:
            continue

    if not items:
        return "暂无项目。用 project_save 创建。"

    items.sort(reverse=True)  # 按 updated_at 降序
    lines = [f"共 {len(items)} 个项目:"]
    for updated, name, keys in items:
        lines.append(f"  {name:30s}  ({updated})  键: {keys}")
    return "\n".join(lines)


@registry.tool(
    name="project_delete",
    description="删除指定项目。",
    params={
        "name": {"type": "string", "description": "项目名"},
    },
)
async def project_delete(name: str) -> str:
    path = _project_path(name)
    if not os.path.exists(path):
        return f"项目不存在: {name}"
    try:
        os.remove(path)
        return f"项目已删除: {name}"
    except Exception as e:
        return f"删除失败: {e}"
