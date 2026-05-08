"""DEPRECATED shim — `agent.memory` 在 issue #10 里改名为 `agent.session_index`。

之前的 `MemoryStore` 暗示这是"主记忆"，但其实只是 session_search 的 FTS5 索引。
真正的持久记忆是 `agent/memory_md.py`（MEMORY/USER/LESSONS 三个 MD 文件）。

本 shim 仅为兼容老代码 / 老 import：

    from agent.memory import MemoryStore   # 仍可用，但触发 DeprecationWarning

下个 minor 版本会删除本文件，请改用：

    from agent.session_index import SessionIndex
"""

from __future__ import annotations

import warnings

from agent.session_index import SessionIndex as _SessionIndex
from agent.session_index import _ensure_dir as _ensure_dir
from agent.session_index import _write_lock as _write_lock

warnings.warn(
    "agent.memory.MemoryStore 已重命名为 agent.session_index.SessionIndex，"
    "请更新 import；本兼容 shim 将在下一个 minor 版本删除。",
    DeprecationWarning,
    stacklevel=2,
)

# 类别名 —— 行为完全一致
MemoryStore = _SessionIndex

__all__ = ["MemoryStore"]
