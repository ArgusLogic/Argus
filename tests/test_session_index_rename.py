"""issue #10 — agent.memory → agent.session_index 重命名 + shim 测试。"""

from __future__ import annotations

import warnings


def test_session_index_class_exists() -> None:
    from agent.session_index import SessionIndex

    assert SessionIndex is not None
    inst = SessionIndex()
    # 至少有 _initialized 属性（用于懒初始化）
    assert hasattr(inst, "_initialized")


def test_legacy_memory_module_warns_and_re_exports() -> None:
    """from agent.memory import MemoryStore 仍然能 import，但触发 DeprecationWarning。"""
    import importlib
    import sys

    # 强制重新 import 以触发顶层 warnings.warn
    sys.modules.pop("agent.memory", None)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import agent.memory as legacy

        assert any(issubclass(wi.category, DeprecationWarning) for wi in w)

    # MemoryStore 别名仍可用
    from agent.session_index import SessionIndex

    assert legacy.MemoryStore is SessionIndex
    # 老测试可能依赖的内部对象也保留
    assert hasattr(legacy, "_write_lock")
    assert hasattr(legacy, "_ensure_dir")

    # 清理 import 缓存以免影响其它测试
    importlib.invalidate_caches()


def test_engine_uses_session_index_attribute() -> None:
    """AgentEngine 现在挂的是 self.session_index，不再是 self.memory。"""
    import inspect

    from agent.engine import AgentEngine

    src = inspect.getsource(AgentEngine.__init__)
    assert "session_index" in src
    # 不再用旧名（避免回归）
    assert "self.memory =" not in src
