"""持久记忆管理工具：暴露给主 LLM 主动调用，更新 MEMORY.md / USER.md。

设计参考 Hermes Agent (https://github.com/NousResearch/hermes-agent)：
LLM 在对话中**主动**决定何时保存什么，避免后台静默提取造成的滥保存。
"""

import json

from agent.memory_md import MemoryMD
from agent.tool_registry import registry

_store = MemoryMD()


@registry.tool(
    name="memory_manage",
    description=(
        "管理你的持久记忆。两类目标：\n"
        "  - target='memory'：你的工作笔记（环境事实、项目惯例、踩过的坑、任务日志）\n"
        "  - target='user'：用户画像（持久偏好、沟通风格、技能水平、雷区）\n"
        "三种 action：\n"
        "  - add：新增条目（content 必填）\n"
        "  - replace：用 old_text 子串匹配定位旧条目，整条替换为 content（old_text + content 必填）\n"
        "  - remove：用 old_text 子串匹配并删除（old_text 必填）\n"
        "保存原则：只记录跨会话仍有价值的高密度事实；不保存临时上下文、原始数据、易再发现的事实。"
        "重复内容会被自动拒绝。每个文件有字符上限，满时需先 replace/remove。"
    ),
    params={
        "action": {
            "type": "string",
            "description": "操作类型: add / replace / remove",
            "required": True,
        },
        "target": {
            "type": "string",
            "description": "目标文件: memory 或 user",
            "required": True,
        },
        "content": {
            "type": "string",
            "description": "新条目内容（add / replace 时必填）",
            "required": False,
        },
        "old_text": {
            "type": "string",
            "description": "要匹配的旧条目子串（replace / remove 时必填）",
            "required": False,
        },
    },
)
async def memory_manage(
    action: str,
    target: str,
    content: str = "",
    old_text: str = "",
) -> str:
    if target not in ("memory", "user"):
        return json.dumps({"ok": False, "msg": "target 必须是 memory 或 user"}, ensure_ascii=False)

    action = (action or "").lower().strip()
    if action == "add":
        result = _store.add(target, content)
    elif action == "replace":
        result = _store.replace(target, old_text, content)
    elif action == "remove":
        result = _store.remove(target, old_text)
    else:
        return json.dumps(
            {"ok": False, "msg": f"未知 action: {action}（可用: add / replace / remove）"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False)
