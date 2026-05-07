"""会话搜索工具：让 LLM 检索过去保存的会话内容。

后端是 agent/session.py 的 SQLite messages 表（保存过 /session save 的会话）。
默认用简单 LIKE 模糊匹配，结果按相关性（命中次数）+ 时间排序。
"""

import json

import aiosqlite

from agent.tool_registry import registry
from utils.paths import DB_PATH


@registry.tool(
    name="session_search",
    description=(
        "搜索过去已保存的会话历史。当用户提到「我之前说过」「上次那个目标」「忘了之前怎么处理」等内容时使用。\n"
        "返回匹配的会话片段（含会话名、时间、消息摘要）。"
    ),
    params={
        "query": {
            "type": "string",
            "description": "搜索关键词，支持中英文",
            "required": True,
        },
        "limit": {
            "type": "integer",
            "description": "最多返回结果数（默认 5）",
            "required": False,
        },
    },
)
async def session_search(query: str, limit: int = 5) -> str:
    query = (query or "").strip()
    if not query:
        return json.dumps({"ok": False, "msg": "query 不能为空"}, ensure_ascii=False)

    limit = max(1, min(int(limit) if limit else 5, 20))

    try:
        db = await aiosqlite.connect(DB_PATH)
    except Exception as e:
        return json.dumps({"ok": False, "msg": f"无法打开会话库: {e}"}, ensure_ascii=False)

    try:
        # 检查 messages 表是否存在
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not await cursor.fetchone():
            return json.dumps(
                {"ok": True, "results": [], "msg": "no saved sessions"},
                ensure_ascii=False,
            )

        # 关键词模糊匹配（content LIKE）
        like_pattern = f"%{query}%"
        cursor = await db.execute(
            """
            SELECT m.session_name, m.idx, m.role, m.content, s.updated_at
            FROM messages m
            JOIN sessions s ON s.name = m.session_name
            WHERE m.content LIKE ? AND m.role IN ('user', 'assistant')
            ORDER BY s.updated_at DESC, m.idx ASC
            LIMIT ?
            """,
            (like_pattern, limit * 3),  # 先取多点，再按 session 聚合
        )
        rows = await cursor.fetchall()

        if not rows:
            return json.dumps(
                {"ok": True, "results": [], "msg": "no matches"},
                ensure_ascii=False,
            )

        # 按 session 聚合，每个 session 取首个命中片段
        seen_sessions = {}
        for session_name, _idx, role, content, updated_at in rows:
            if session_name in seen_sessions:
                continue
            snippet = (content or "").strip()
            if len(snippet) > 200:
                # 截取命中关键词周围
                pos = snippet.lower().find(query.lower())
                if pos > 0:
                    start = max(0, pos - 50)
                    end = min(len(snippet), pos + 150)
                    snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(snippet) else "")
                else:
                    snippet = snippet[:200] + "..."

            seen_sessions[session_name] = {
                "session": session_name,
                "updated_at": updated_at,
                "role": role,
                "snippet": snippet,
            }
            if len(seen_sessions) >= limit:
                break

        return json.dumps(
            {"ok": True, "results": list(seen_sessions.values())},
            ensure_ascii=False,
        )
    finally:
        await db.close()
