"""路径安全校验：防止 LLM 被诱导写到任意路径（issue #15.2）。

策略：将待写/读路径与允许的目录前缀做 prefix 匹配。

默认允许目录：
- `~/.argus/`           — Argus 主目录（输出、记忆、会话等）
- 当前工作目录（CWD）   — 便于本地调试

额外允许目录通过 `config.toml` 的 `[security] write_allowed_dirs` /
`read_allowed_dirs` 配置（路径列表，支持 `~` 展开）。

API:
    is_path_allowed(path, mode="write") -> bool
    require_safe_path(path, mode="write") -> str   # 返回 abspath 或抛 PermissionError

注意：本模块只防"误写到敏感路径"，不能替代 OS 级别的权限隔离。
"""

from __future__ import annotations

import os

from utils.paths import SECAGENT_HOME

_CACHE: dict[str, list[str]] | None = None


def _load_allowlist() -> dict[str, list[str]]:
    """从 config.toml 读取额外允许目录。失败时退回默认值。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    defaults = {
        "write": [os.path.abspath(SECAGENT_HOME), os.path.abspath(os.getcwd())],
        "read": [os.path.abspath(SECAGENT_HOME), os.path.abspath(os.getcwd())],
    }
    try:
        from utils.paths import CONFIG_PATH

        if os.path.exists(CONFIG_PATH):
            import toml

            cfg = toml.load(CONFIG_PATH)
            sec = cfg.get("security", {}) or {}
            for mode, key in (("write", "write_allowed_dirs"), ("read", "read_allowed_dirs")):
                extras = sec.get(key, []) or []
                if isinstance(extras, list):
                    for p in extras:
                        if isinstance(p, str) and p.strip():
                            defaults[mode].append(os.path.abspath(os.path.expanduser(p)))
    except Exception:
        pass

    _CACHE = defaults
    return defaults


def reset_cache() -> None:
    """测试用：清缓存以便重读 config。"""
    global _CACHE
    _CACHE = None


def is_path_allowed(path: str, mode: str = "write") -> bool:
    """判断给定路径是否落在白名单目录之下。

    Args:
        path: 待检查路径（任意形式：相对/绝对/含 ~）
        mode: "write" 或 "read"
    """
    if mode not in ("read", "write"):
        raise ValueError(f"mode must be 'read' or 'write', got: {mode!r}")
    abs_target = os.path.abspath(os.path.expanduser(path))
    allowed = _load_allowlist().get(mode, [])
    for base in allowed:
        # commonpath 防止 /foo/barbaz 被误认为属于 /foo/bar
        try:
            if os.path.commonpath([abs_target, base]) == base:
                return True
        except ValueError:
            # Windows 下不同盘符 commonpath 抛 ValueError
            continue
    return False


def require_safe_path(path: str, mode: str = "write") -> str:
    """同 `is_path_allowed`，但不通过则抛 `PermissionError`。返回规范化绝对路径。"""
    if not is_path_allowed(path, mode=mode):
        abs_target = os.path.abspath(os.path.expanduser(path))
        raise PermissionError(
            f"路径越界（{mode}）: {abs_target!r} 不在允许目录内。"
            "如需放行，可在 config.toml 添加 [security] "
            f'{"write" if mode == "write" else "read"}_allowed_dirs = ["..."]'
        )
    return os.path.abspath(os.path.expanduser(path))
