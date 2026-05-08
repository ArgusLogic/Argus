"""SQLite + FTS5 索引：仅为 session_search 工具的全文检索后端服务。

此模块**不**等同于 Argus 的"持久记忆"。三层记忆架构详见 `docs/architecture.md`：

  - ContextManager (agent/context.py)        : 单次会话内的对话历史 + token 压缩
  - SessionIndex   (agent/session_index.py)  : 跨会话 SQLite/FTS5 倒排索引
  - MemoryMD       (agent/memory_md.py)      : LLM 主动维护的 MD 文件型记忆
                                              （MEMORY/USER/LESSONS）

issue #10：原名 `agent.memory.MemoryStore` 容易让人误以为它就是"主记忆"。
真实职责只是给 `session_search` 工具做关键词检索。原名保留 deprecation
shim（agent/memory.py）一两个版本后删除。
"""

import asyncio
import contextlib
import os
from datetime import datetime

import aiosqlite

from utils.logger import log_info, log_warning
from utils.paths import DB_PATH, SESSIONS_DIR

# issue #15.3：多协程串行化写入，避免并发写损坏数据库。
_write_lock = asyncio.Lock()


def _ensure_dir() -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)


class SessionIndex:
    """跨会话的 SQLite + FTS5 关键词索引（仅供 session_search 使用）。"""

    def __init__(self):
        self._initialized = False

    async def _get_db(self) -> aiosqlite.Connection:
        """获取数据库连接并确保记忆表已创建。启用 WAL 提高并发安全 (#15.3)。"""
        _ensure_dir()
        db = await aiosqlite.connect(DB_PATH)
        # WAL: 读写并发不互斥，减少锁冲突
        with contextlib.suppress(Exception):
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
        if not self._initialized:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            # FTS5 全文检索虚拟表
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content=memories, content_rowid=id)
            """)
            # 同步触发器：insert/delete 时自动更新 FTS 索引
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END
            """)
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.id, old.content);
                END
            """)
            await db.commit()
            self._initialized = True
        return db

    async def add(self, category: str, content: str, source: str = "") -> int:
        """新增一条记忆。返回记忆 ID。

        Args:
            category: fact / user / target
            content: 记忆内容
            source: 来源（如会话名或目标域名）
        """
        async with _write_lock:
            db = await self._get_db()
            try:
                now = datetime.now().isoformat()
                cursor = await db.execute(
                    "INSERT INTO memories (category, content, source, created_at) VALUES (?, ?, ?, ?)",
                    (category, content, source, now),
                )
                await db.commit()
                memory_id = cursor.lastrowid
                log_info(f"记忆已保存 [#{memory_id} {category}]: {content[:60]}")
                return memory_id or 0
            finally:
                await db.close()

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """FTS5 全文检索记忆。"""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                """
                SELECT m.id, m.category, m.content, m.source, m.created_at
                FROM memories m
                JOIN memories_fts f ON m.id = f.rowid
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "category": r[1],
                    "content": r[2],
                    "source": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            log_warning(f"记忆检索失败: {e}")
            return []
        finally:
            await db.close()

    async def get_by_category(self, category: str, limit: int = 20) -> list[dict]:
        """按类别获取记忆。"""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT id, category, content, source, created_at FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "category": r[1],
                    "content": r[2],
                    "source": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        finally:
            await db.close()

    async def get_recent(self, limit: int = 20) -> list[dict]:
        """获取最近的记忆。"""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT id, category, content, source, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "category": r[1],
                    "content": r[2],
                    "source": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        finally:
            await db.close()

    async def delete(self, memory_id: int) -> bool:
        """删除指定记忆。"""
        async with _write_lock:
            db = await self._get_db()
            try:
                cursor = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                await db.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    log_info(f"记忆已删除: #{memory_id}")
                return deleted
            finally:
                await db.close()

    async def clear(self) -> int:
        """清空所有记忆，返回删除数量。"""
        async with _write_lock:
            db = await self._get_db()
            try:
                cursor = await db.execute("SELECT COUNT(*) FROM memories")
                row = await cursor.fetchone()
                count = row[0] if row else 0
                await db.execute("DELETE FROM memories")
                await db.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
                await db.commit()
                log_info(f"已清空 {count} 条记忆")
                return count
            finally:
                await db.close()

    async def count(self) -> int:
        """返回记忆总数。"""
        db = await self._get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM memories")
            row = await cursor.fetchone()
            return row[0] if row else 0
        finally:
            await db.close()

    async def export_markdown(self) -> str:
        """导出所有记忆为 Markdown 格式。"""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT id, category, content, source, created_at FROM memories ORDER BY category, created_at DESC"
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()

        if not rows:
            return "# Argus 记忆库\n\n暂无记忆。\n"

        lines = [f"# Argus 记忆库\n\n导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        current_cat = None
        cat_labels = {"fact": "事实发现", "user": "用户偏好", "target": "目标情报"}

        for _mid, cat, content, source, _created in rows:
            if cat != current_cat:
                current_cat = cat
                lines.append(f"\n## {cat_labels.get(cat, cat)}\n")
            source_tag = f" ({source})" if source else ""
            lines.append(f"- {content}{source_tag}")

        return "\n".join(lines) + "\n"

    async def get_relevant(self, task: str, limit: int = 10) -> list[dict]:
        """根据任务描述检索相关记忆。先尝试 FTS5，不足时补充最近记忆。"""
        results = []
        if task.strip():
            # 用空格分词作为 OR 查询，过滤特殊字符防止 FTS5 语法错误
            import re

            tokens = task.strip().split()
            # 只保留中文、字母、数字组成的 token
            safe_tokens = [t for t in tokens if re.match(r"^[\w\u4e00-\u9fff]+$", t)]
            if safe_tokens:
                # FTS5 需要用双引号包裹每个 token；内部 " 需要双化转义 (#15.5)
                fts_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in safe_tokens[:5])
                with contextlib.suppress(Exception):
                    results = await self.search(fts_query, limit=limit)

        if len(results) < limit:
            recent = await self.get_recent(limit=limit - len(results))
            seen_ids = {r["id"] for r in results}
            for r in recent:
                if r["id"] not in seen_ids:
                    results.append(r)

        return results[:limit]
