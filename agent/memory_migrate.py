"""一次性迁移：把旧 SQLite memories 表导出到新的 MEMORY.md / USER.md。

策略（按 category 分流）：
  fact / target  → MEMORY.md
  user           → USER.md

迁移完成后给原表加标记，避免重复迁移。
"""

import asyncio
import os

import aiosqlite

from agent.memory_md import MemoryMD
from utils.logger import log_info, log_warning
from utils.paths import DB_PATH

_MIGRATION_FLAG_TABLE = "memory_migrated_flag"


async def _is_migrated(db: aiosqlite.Connection) -> bool:
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (_MIGRATION_FLAG_TABLE,),
    )
    return await cursor.fetchone() is not None


async def _mark_migrated(db: aiosqlite.Connection) -> None:
    await db.execute(f"CREATE TABLE IF NOT EXISTS {_MIGRATION_FLAG_TABLE} (id INTEGER)")
    await db.commit()


async def migrate_once() -> dict:
    """执行迁移。返回 {migrated, skipped, errors} 统计。"""
    if not os.path.exists(DB_PATH):
        return {"migrated": 0, "skipped": 0, "errors": 0, "msg": "no old db"}

    try:
        db = await aiosqlite.connect(DB_PATH)
    except Exception as e:
        log_warning(f"迁移跳过：无法打开旧数据库: {e}")
        return {"migrated": 0, "skipped": 0, "errors": 1}

    try:
        # 检查是否已迁移
        if await _is_migrated(db):
            return {"migrated": 0, "skipped": -1, "msg": "already migrated"}

        # 检查 memories 表是否存在
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
        if not await cursor.fetchone():
            await _mark_migrated(db)
            return {"migrated": 0, "skipped": 0, "msg": "no old memories table"}

        cursor = await db.execute("SELECT category, content FROM memories ORDER BY id")
        rows = await cursor.fetchall()

        if not rows:
            await _mark_migrated(db)
            return {"migrated": 0, "skipped": 0, "msg": "old memories table empty"}

        store = MemoryMD()
        migrated = 0
        skipped = 0
        errors = 0

        for category, content in rows:
            if not content:
                skipped += 1
                continue

            target = "user" if category == "user" else "memory"
            result = store.add(target, content.strip(), silent=True)
            if result.get("ok"):
                migrated += 1
            else:
                # 重复或满了，都算 skipped
                skipped += 1

        # 关键：DROP 旧表，物理上消灭再次迁移的可能
        await db.execute("DROP TABLE IF EXISTS memories")
        await db.commit()
        await _mark_migrated(db)

        if migrated > 0:
            log_info(f"记忆迁移完成: {migrated} 条迁入 MD，{skipped} 条跳过；旧表已清理")
        return {"migrated": migrated, "skipped": skipped, "errors": errors}

    except Exception as e:
        log_warning(f"迁移异常: {e}")
        return {"migrated": 0, "skipped": 0, "errors": 1, "msg": str(e)}
    finally:
        await db.close()


def migrate_sync() -> dict:
    """同步包装，方便启动时调用。"""
    try:
        return asyncio.run(migrate_once())
    except RuntimeError:
        # 已在 event loop 中
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(migrate_once())
