"""Skills 技能系统：从成功执行中自动提炼可复用侦察流程。"""

import json
import os
from datetime import datetime
from typing import Any

from utils.logger import log_error, log_info, log_warning
from utils.paths import SKILLS_DIR


class SkillManager:
    """管理 Agent 的可复用技能。"""

    def __init__(self, skills_dir: str = SKILLS_DIR):
        self.skills_dir = skills_dir
        os.makedirs(self.skills_dir, exist_ok=True)

    def _skill_path(self, name: str) -> str:
        safe_name = name.replace("/", "_").replace("\\", "_")
        return os.path.join(self.skills_dir, f"{safe_name}.json")

    def list_skills(self) -> list[dict[str, Any]]:
        """返回所有技能的摘要列表。"""
        skills = []
        for filename in sorted(os.listdir(self.skills_dir)):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.skills_dir, filename), encoding="utf-8") as f:
                    skill = json.load(f)
                skills.append(
                    {
                        "name": skill["name"],
                        "description": skill.get("description", ""),
                        "steps_count": len(skill.get("steps", [])),
                        "success_count": skill.get("success_count", 0),
                    }
                )
            except Exception:
                continue
        return skills

    def get_skill(self, name: str) -> dict[str, Any] | None:
        """获取技能详情。"""
        path = self._skill_path(name)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"读取技能失败 {name}: {e}")
            return None

    def save_skill(self, skill: dict[str, Any]) -> None:
        """保存技能。"""
        name = skill.get("name", "unnamed")
        skill.setdefault("created_at", datetime.now().isoformat())
        skill.setdefault("success_count", 0)
        path = self._skill_path(name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(skill, f, ensure_ascii=False, indent=2)
            log_info(f"技能已保存: {name} ({len(skill.get('steps', []))} 步)")
        except Exception as e:
            log_error(f"保存技能失败 {name}: {e}")

    def delete_skill(self, name: str) -> bool:
        """删除技能。"""
        path = self._skill_path(name)
        if os.path.exists(path):
            os.remove(path)
            log_info(f"技能已删除: {name}")
            return True
        log_warning(f"技能不存在: {name}")
        return False

    def increment_success(self, name: str) -> None:
        """增加技能的成功计数。"""
        skill = self.get_skill(name)
        if skill:
            skill["success_count"] = skill.get("success_count", 0) + 1
            self.save_skill(skill)

    def format_for_prompt(self, limit: int = 5) -> str:
        """格式化技能列表供 system prompt 注入。"""
        skills = self.list_skills()
        if not skills:
            return ""

        # 按成功次数降序，取 top N
        skills.sort(key=lambda s: s.get("success_count", 0), reverse=True)
        skills = skills[:limit]

        lines = ["## 可复用技能", "以下是你之前成功提炼的侦察技能，遇到类似任务时可以参考这些步骤：", ""]
        for s in skills:
            lines.append(
                f"- **{s['name']}**: {s['description']} ({s['steps_count']} 步, 成功 {s['success_count']} 次)"
            )

        return "\n".join(lines)

    def extract_steps_from_messages(self, messages: list[dict]) -> list[dict]:
        """从对话消息中提取工具调用序列。"""
        steps = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args_str = func.get("arguments", "{}")
                if not name:
                    continue
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args = {}
                steps.append({"tool": name, "args_template": args})
        return steps
