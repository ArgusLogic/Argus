"""会话持久化：基于 SQLite 的会话保存与恢复。"""

import contextlib
import json
import os
from datetime import datetime

import aiosqlite

from utils.logger import log_error, log_info
from utils.paths import DB_PATH, SESSIONS_DIR


def _ensure_dir() -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)


async def _get_db() -> aiosqlite.Connection:
    """获取数据库连接并确保表已创建。"""
    _ensure_dir()
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            name TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT NOT NULL,
            idx INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            FOREIGN KEY (session_name) REFERENCES sessions(name) ON DELETE CASCADE
        )
    """)
    await db.commit()
    return db


async def save_session(messages: list[dict], name: str | None = None) -> str:
    """保存当前对话到 SQLite。"""
    if not name:
        name = datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().isoformat()

    db = await _get_db()
    try:
        # 插入或更新 session 记录
        await db.execute(
            "INSERT OR REPLACE INTO sessions (name, created_at, updated_at, message_count) VALUES (?, COALESCE((SELECT created_at FROM sessions WHERE name = ?), ?), ?, ?)",
            (name, name, now, now, len(messages)),
        )
        # 清除旧消息
        await db.execute("DELETE FROM messages WHERE session_name = ?", (name,))
        # 插入新消息
        for idx, msg in enumerate(messages):
            tool_calls_json = None
            if "tool_calls" in msg:
                with contextlib.suppress(TypeError, ValueError):
                    tool_calls_json = json.dumps(msg["tool_calls"], ensure_ascii=False)

            await db.execute(
                "INSERT INTO messages (session_name, idx, role, content, tool_call_id, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name,
                    idx,
                    msg.get("role", ""),
                    msg.get("content", ""),
                    msg.get("tool_call_id", ""),
                    tool_calls_json,
                ),
            )
        await db.commit()
        log_info(f"会话已保存: {name} ({len(messages)} 条消息)")
        return name
    finally:
        await db.close()


async def load_session(name: str) -> list[dict] | None:
    """从 SQLite 恢复对话历史。"""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT role, content, tool_call_id, tool_calls FROM messages WHERE session_name = ? ORDER BY idx",
            (name,),
        )
        rows = await cursor.fetchall()
        if not rows:
            log_error(f"会话不存在或为空: {name}")
            return None

        messages = []
        for role, content, tool_call_id, tool_calls_json in rows:
            msg: dict = {"role": role, "content": content or ""}
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            if tool_calls_json:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = json.loads(tool_calls_json)
            messages.append(msg)

        log_info(f"会话已加载: {name} ({len(messages)} 条消息)")
        return messages
    finally:
        await db.close()


async def list_sessions() -> list[str]:
    """列出所有已保存的会话。"""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT name, updated_at, message_count FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [f"{row[0]}  ({row[2]} msgs, {row[1]})" for row in rows]
    finally:
        await db.close()


async def delete_session(name: str) -> bool:
    """删除指定会话。"""
    db = await _get_db()
    try:
        await db.execute("DELETE FROM messages WHERE session_name = ?", (name,))
        cursor = await db.execute("DELETE FROM sessions WHERE name = ?", (name,))
        await db.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log_info(f"会话已删除: {name}")
        else:
            log_error(f"会话不存在: {name}")
        return deleted
    finally:
        await db.close()
