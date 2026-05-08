"""凭据管理：~/.argus/credentials.toml 读取 + placeholder 机制。

设计目标：让 LLM 在不接触明文密码的前提下完成自动登录。流程：

  1. 用户在 ``~/.argus/credentials.toml`` 维护 host -> {username, password, login_url}
  2. LLM 调 ``credentials_lookup(host)``；返回字符串里的密码字段是
     ``${CRED_<host>_PASS}`` 占位符，**不含明文**
  3. LLM 把占位符原样传给 ``auth_login``
  4. AgentEngine 在 ``registry.execute`` 之前调 ``expand_placeholders``
     把占位符就地替换为真值；这一步**只在工具子进程内可见**
  5. 所有日志 / session_db / 报告写入前过 ``utils.scrub.scrub``，再次保险

文件格式（toml）::

    [targets."127.0.0.1:8080"]
    username = "admin"
    password = "password"
    login_url = "/login.php"

    [targets."demo.testfire.net"]
    username = "jsmith"
    password = "demo1234"
    login_url = "/login.jsp"
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import tomllib  # py 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CRED_PATH = Path.home() / ".argus" / "credentials.toml"

# 占位符语法： ${CRED_<safe_host>_<field>}
# safe_host 把非 [A-Za-z0-9_] 字符全替换为 '_'
_PLACEHOLDER_RE = re.compile(r"\$\{CRED_([A-Za-z0-9_]+)_(USER|PASS|URL)\}")

_credentials_cache: dict[str, dict[str, str]] | None = None
_cache_path: Path | None = None


def _safe_host(host: str) -> str:
    """把 host:port 形式中非 [A-Za-z0-9_] 字符替换为 '_'，用于 placeholder key。"""
    return re.sub(r"[^A-Za-z0-9_]", "_", host.strip())


def _load(path: Path | None = None) -> dict[str, dict[str, str]]:
    """读取 credentials.toml；缓存按 path 分。任意异常退回空字典。"""
    global _credentials_cache, _cache_path
    real_path = path or DEFAULT_CRED_PATH
    if _credentials_cache is not None and _cache_path == real_path:
        return _credentials_cache
    out: dict[str, dict[str, str]] = {}
    if real_path.exists():
        try:
            with open(real_path, "rb") as f:
                data: dict[str, Any] = tomllib.load(f)
            targets = data.get("targets", {})
            if isinstance(targets, dict):
                for host, cred in targets.items():
                    if isinstance(cred, dict):
                        out[host] = {str(k): str(v) for k, v in cred.items()}
        except Exception:
            out = {}
    _credentials_cache = out
    _cache_path = real_path
    return out


def reset_cache() -> None:
    """清缓存（测试 / 用户改文件后用）。"""
    global _credentials_cache, _cache_path
    _credentials_cache = None
    _cache_path = None


def lookup(host: str, *, path: Path | None = None) -> dict[str, str] | None:
    """查 host 凭据。返回 {username, password, login_url}（含明文）或 None。"""
    return _load(path).get(host.strip())


def make_placeholder_hint(host: str, *, path: Path | None = None) -> str:
    """LLM 调 credentials_lookup 看到的字符串。**密码字段返 placeholder 而非明文**。"""
    host = host.strip()
    cred = lookup(host, path=path)
    if not cred:
        return f"未找到 {host!r} 的凭据。请在 ~/.argus/credentials.toml 中添加 [targets.\"{host}\"] 节。"
    safe = _safe_host(host)
    user = cred.get("username") or cred.get("user", "")
    login_url = cred.get("login_url", "")
    lines = [
        f"找到 {host} 凭据（明文已隔离，仅 placeholder 暴露给 LLM）。",
        "调用 auth_login 时按以下占位符传参（执行前自动展开为真值）：",
        f"  username   = ${{CRED_{safe}_USER}}     # 真值: {user!r}",
        f"  password   = ${{CRED_{safe}_PASS}}     # 真值: ***（不展示）",
    ]
    if login_url:
        lines.append(f"  login_url  = ${{CRED_{safe}_URL}}      # 真值: {login_url!r}")
    return "\n".join(lines)


def expand_placeholders(text: str, *, path: Path | None = None) -> str:
    """把 text 里所有 ``${CRED_<safe_host>_<field>}`` 替换为真值。

    匹配不到的占位符**保持原样**（不抛错），便于排查。
    """
    if not text or _PLACEHOLDER_PREFIX not in text:
        return text
    creds = _load(path)
    safe_to_orig = {_safe_host(k): k for k in creds}

    def _sub(m: re.Match[str]) -> str:
        safe_host, field = m.group(1), m.group(2)
        host = safe_to_orig.get(safe_host)
        if host is None:
            return m.group(0)
        c = creds[host]
        if field == "USER":
            return c.get("username") or c.get("user", "")
        if field == "PASS":
            return c.get("password", "")
        if field == "URL":
            return c.get("login_url", "")
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, text)


_PLACEHOLDER_PREFIX = "${CRED_"
