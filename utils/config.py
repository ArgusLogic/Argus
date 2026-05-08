"""issue #9：统一的 config.toml 加载入口。

替换之前 6 个文件各自 toml.load(CONFIG_PATH) 的复制粘贴。

设计要点：
  - 进程级缓存：第一次调用读盘，后续从 dict 读
  - 文件不存在 → 缓存 {} 而非抛异常（多数模块只想取可选 section）
  - reload() 显式清缓存：测试用、运行时未来如果支持热重载也用这个
  - 读盘失败（malformed toml 等）记 warning 后回退 {} —— 不让一个坏配置文件
    把整个 agent 拖崩
"""

from __future__ import annotations

import os
import threading
from typing import Any

from utils.logger import log_warning

_cache: dict[str, Any] | None = None
_lock = threading.Lock()


def _resolve_config_path() -> str | None:
    """优先 ~/.argus/config.toml；fallback 项目根 config.toml；都没有返回 None。

    legacy 项目根 fallback 仅在 CONFIG_PATH **未被改写过**时才生效，避免
    测试 monkeypatch 到不存在的 tmp 路径时意外回落到仓库根的真实配置。
    """
    from utils.paths import CONFIG_PATH

    if os.path.exists(CONFIG_PATH):
        return CONFIG_PATH

    default_path = os.path.join(os.path.expanduser("~"), ".argus", "config.toml")
    if os.path.abspath(CONFIG_PATH) != os.path.abspath(default_path):
        # 被测试或调用方显式指向其它路径，文件不在就当没配置，不偷换。
        return None

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    legacy = os.path.join(here, "config.toml")
    if os.path.exists(legacy):
        return legacy
    return None


def _load_from_disk() -> dict[str, Any]:
    path = _resolve_config_path()
    if path is None:
        return {}
    try:
        import toml

        with open(path, encoding="utf-8") as f:
            return toml.load(f)
    except Exception as e:
        log_warning(f"config.toml 解析失败，使用空配置: {e}")
        return {}


def get_config() -> dict[str, Any]:
    """返回进程级缓存的 config dict（线程安全，懒加载）。"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is None:  # 双重检查
            _cache = _load_from_disk()
        return _cache


def get_section(name: str) -> dict[str, Any]:
    """快捷：get_config().get(name, {}) 并保证返回 dict。"""
    val = get_config().get(name, {})
    return val if isinstance(val, dict) else {}


def reload() -> None:
    """清空缓存（测试 + 未来热重载）。"""
    global _cache
    with _lock:
        _cache = None
