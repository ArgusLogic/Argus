"""技能管理工具：让主 LLM 主动 create/patch/edit/delete 自己的可复用技能。

设计参考 Hermes Agent 的 skill_manage：
- create：新建技能
- patch：用 old_string/new_string 局部修改（首选，token 高效）
- edit：完整重写 content
- delete：删除技能
"""

import json
from datetime import datetime

from agent.skills import SkillManager
from agent.tool_registry import registry

_skills = SkillManager()


@registry.tool(
    name="skill_manage",
    description=(
        "管理你的可复用侦察技能（程序性记忆）。\n"
        "完成一个**复杂任务**（5+ 工具调用、未来可能复用）后，应该把经验保存为 skill。\n"
        "actions:\n"
        "  - create: 新建（必填 name + description + content）\n"
        "  - patch: 局部修改，token 高效（必填 name + old_string + new_string）\n"
        "  - edit: 整体重写 content（必填 name + content）\n"
        "  - delete: 删除（必填 name）\n"
        "name 用英文 snake_case；content 是 markdown 格式的步骤说明（包含触发条件、工具调用顺序、注意事项）。"
    ),
    params={
        "action": {
            "type": "string",
            "description": "操作: create / patch / edit / delete",
            "required": True,
        },
        "name": {
            "type": "string",
            "description": "技能名称 (英文 snake_case)",
            "required": True,
        },
        "description": {
            "type": "string",
            "description": "技能简述 (create 时必填)",
            "required": False,
        },
        "content": {
            "type": "string",
            "description": "技能完整 markdown 内容 (create / edit 时必填)",
            "required": False,
        },
        "old_string": {
            "type": "string",
            "description": "patch 时要替换的旧文本（必须在 content 中唯一出现）",
            "required": False,
        },
        "new_string": {
            "type": "string",
            "description": "patch 时替换为的新文本",
            "required": False,
        },
    },
)
async def skill_manage(
    action: str,
    name: str,
    description: str = "",
    content: str = "",
    old_string: str = "",
    new_string: str = "",
) -> str:
    action = (action or "").lower().strip()
    name = (name or "").strip()

    if not name:
        return json.dumps({"ok": False, "msg": "name 不能为空"}, ensure_ascii=False)

    # ── create ──
    if action == "create":
        if not description or not content:
            return json.dumps(
                {"ok": False, "msg": "create 需要 description 和 content"},
                ensure_ascii=False,
            )
        if _skills.get_skill(name):
            return json.dumps(
                {"ok": False, "msg": f"技能 '{name}' 已存在，请用 patch 或 edit"},
                ensure_ascii=False,
            )
        skill = {
            "name": name,
            "description": description,
            "content": content,  # markdown 格式
            "created_at": datetime.now().isoformat(),
            "success_count": 0,
        }
        _skills.save_skill(skill)
        return json.dumps({"ok": True, "msg": f"技能 '{name}' 已创建"}, ensure_ascii=False)

    # ── patch ──
    if action == "patch":
        skill = _skills.get_skill(name)
        if not skill:
            return json.dumps({"ok": False, "msg": f"技能 '{name}' 不存在"}, ensure_ascii=False)
        if not old_string or not new_string:
            return json.dumps(
                {"ok": False, "msg": "patch 需要 old_string 和 new_string"},
                ensure_ascii=False,
            )
        old_content = skill.get("content", "") or json.dumps(skill.get("steps", []), ensure_ascii=False)
        if old_string not in old_content:
            return json.dumps(
                {"ok": False, "msg": "old_string 在技能中未找到"},
                ensure_ascii=False,
            )
        if old_content.count(old_string) > 1:
            return json.dumps(
                {"ok": False, "msg": "old_string 出现多次，请提供更具体的上下文"},
                ensure_ascii=False,
            )
        skill["content"] = old_content.replace(old_string, new_string, 1)
        skill["updated_at"] = datetime.now().isoformat()
        _skills.save_skill(skill)
        return json.dumps({"ok": True, "msg": f"技能 '{name}' 已 patch"}, ensure_ascii=False)

    # ── edit ──
    if action == "edit":
        skill = _skills.get_skill(name)
        if not skill:
            return json.dumps({"ok": False, "msg": f"技能 '{name}' 不存在"}, ensure_ascii=False)
        if not content:
            return json.dumps({"ok": False, "msg": "edit 需要 content"}, ensure_ascii=False)
        skill["content"] = content
        if description:
            skill["description"] = description
        skill["updated_at"] = datetime.now().isoformat()
        _skills.save_skill(skill)
        return json.dumps({"ok": True, "msg": f"技能 '{name}' 已重写"}, ensure_ascii=False)

    # ── delete ──
    if action == "delete":
        if _skills.delete_skill(name):
            return json.dumps({"ok": True, "msg": f"技能 '{name}' 已删除"}, ensure_ascii=False)
        return json.dumps({"ok": False, "msg": f"技能 '{name}' 不存在"}, ensure_ascii=False)

    return json.dumps(
        {"ok": False, "msg": f"未知 action: {action}（可用: create / patch / edit / delete）"},
        ensure_ascii=False,
    )
