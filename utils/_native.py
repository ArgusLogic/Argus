"""Native (Rust) acceleration shim — 透明探测 + Python fallback。

加速规则：
1. 启动时尝试 `import argus_native`（pip install argus-native 或本地 maturin develop）
2. 失败则使用纯 Python 实现，无任何用户感知差异

热路径覆盖：
- truncate, strip_ansi, redact_secrets   → utils.sanitizer
- parse_entries, dedup_check, format_block → agent.memory_md
"""

from __future__ import annotations

import os

# 用户可通过 ARGUS_NO_NATIVE=1 强制禁用，便于排查
_DISABLED = os.environ.get("ARGUS_NO_NATIVE", "").lower() in {"1", "true", "yes"}

NATIVE_AVAILABLE = False
NATIVE_VERSION: str | None = None

_native = None  # type: ignore[assignment]

if not _DISABLED:
    try:
        import argus_native as _candidate  # type: ignore[import-not-found]

        # 严格校验：必须是真正构建的 cdylib，含实际函数 + __version__
        if (
            hasattr(_candidate, "__version__")
            and getattr(_candidate, "__version__", "") != ""
            and callable(getattr(_candidate, "truncate", None))
        ):
            _native = _candidate
            NATIVE_AVAILABLE = True
            NATIVE_VERSION = _candidate.__version__
    except ImportError:
        pass


def has_native() -> bool:
    """检查 Rust 加速模块是否可用。"""
    return NATIVE_AVAILABLE


def native_info() -> str:
    """供 /version 命令使用的状态描述。"""
    if NATIVE_AVAILABLE:
        return f"Rust 加速已启用 (argus_native v{NATIVE_VERSION})"
    if _DISABLED:
        return "Rust 加速被环境变量禁用 (ARGUS_NO_NATIVE=1)"
    return "Rust 加速未安装，使用纯 Python 实现"


# ─── 函数代理 ────────────────────────────────────────────────────────


def _get(name: str):
    """安全获取 native 函数。可用时返回，不可用时返回 None。"""
    if not NATIVE_AVAILABLE or _native is None:
        return None
    return getattr(_native, name, None)


# 公开的代理函数：调用方使用这些，自动 fallback
truncate = _get("truncate")
strip_ansi = _get("strip_ansi")
redact_secrets = _get("redact_secrets")
parse_entries = _get("parse_entries")
dedup_check = _get("dedup_check")
format_block = _get("format_block")


__all__ = [
    "NATIVE_AVAILABLE",
    "NATIVE_VERSION",
    "dedup_check",
    "format_block",
    "has_native",
    "native_info",
    "parse_entries",
    "redact_secrets",
    "strip_ansi",
    "truncate",
]
