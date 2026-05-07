"""输入/输出清洗工具。

核心能力：
- truncate:        过长文本截断（首尾保留 + 中间标记）
- sanitize_url:    URL 协议补全
- sanitize_filename: 文件名安全化（防路径穿越）
- sanitize_domain: 域名标准化（剥协议/路径，校验合法性）
- strip_ansi:      去除 ANSI 颜色和控制字符
- redact_secrets:  扫描敏感信息并替换为 [REDACTED:type] 占位符

性能：truncate / strip_ansi / redact_secrets 优先使用 Rust 实现（argus_native），
不可用时自动 fallback 到本文件中的纯 Python 版本。
"""

from __future__ import annotations

import re

from utils import _native

# ─── 文本截断 ──────────────────────────────────────────────────────────


def _py_truncate(text: str, max_len: int = 8000) -> str:
    """纯 Python 截断实现。"""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n\n... [truncated {len(text) - max_len} chars] ...\n\n" + text[-half:]


def truncate(text: str, max_len: int = 8000) -> str:
    """截断过长的文本，保留首尾并标注被截断。"""
    if _native.truncate is not None:
        return _native.truncate(text, max_len)
    return _py_truncate(text, max_len)


# ─── URL / 域名 / 文件名 ──────────────────────────────────────────────


def sanitize_url(url: str) -> str:
    """确保 URL 包含协议前缀。"""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


_FILENAME_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FILENAME_DOTSEG = re.compile(r"^\.+|\.+$")


def sanitize_filename(name: str, max_len: int = 200) -> str:
    """清洗文件名：剥离路径分隔符、控制字符和首尾点；用 _ 替换非法字符。

    始终返回非空字符串（兜底为 'unnamed'）。
    """
    name = (name or "").strip()
    if not name:
        return "unnamed"
    # 仅保留 basename，防止路径穿越
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # 替换非法字符
    name = _FILENAME_BAD.sub("_", name)
    # 去除首尾的点（Windows 不允许）
    name = _FILENAME_DOTSEG.sub("", name)
    if not name or name in {".", ".."}:
        return "unnamed"
    if len(name) > max_len:
        # 保留扩展名
        if "." in name[-30:]:
            base, ext = name.rsplit(".", 1)
            name = base[: max_len - len(ext) - 1] + "." + ext
        else:
            name = name[:max_len]
    return name


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)


def sanitize_domain(value: str) -> str | None:
    """从 URL 或裸字符串中提取并校验域名。

    返回小写 ASCII 域名；非法或为空返回 None。
    """
    if not value:
        return None
    s = value.strip().lower()
    # 剥协议
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    # 剥用户信息和路径/查询/锚点
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        s = s.split("@", 1)[1]
    # 剥端口
    s = s.split(":", 1)[0]
    if not s or not _DOMAIN_RE.match(s):
        return None
    return s


# ─── ANSI 剥离 ─────────────────────────────────────────────────────────

# CSI 序列 + OSC + 单字符控制
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07]*\x07"        # OSC ... BEL
    r"|\x1b[@-Z\\-_]"             # Fe (单字节 ESC)
)


def _py_strip_ansi(text: str) -> str:
    """纯 Python ANSI 剥离实现。"""
    return _ANSI_RE.sub("", text or "")


def strip_ansi(text: str) -> str:
    """去除 ANSI 转义序列（颜色、光标控制）。"""
    if _native.strip_ansi is not None and text:
        return _native.strip_ansi(text)
    return _py_strip_ansi(text)


# ─── 敏感信息脱敏 ──────────────────────────────────────────────────────

# 模式按特异性优先：越具体越先匹配，避免被通用模式吃掉
_REDACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # 高确信度 token（带前缀，几乎不会误判）
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{36,}\b")),
    ("slack_bot_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_session_token", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # JWT（三段 base64url 用 . 连接）
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    # Bearer / Authorization
    ("bearer_token", re.compile(r"\b(?:Bearer|Token)\s+[A-Za-z0-9_\-\.=]{20,}", re.IGNORECASE)),
    # password=xxx / pwd=xxx / passwd=xxx
    (
        "password",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"&,;]{4,})",
        ),
    ),
    # api_key=xxx / api-key=xxx
    (
        "api_key",
        re.compile(
            r"(?i)\b(?:api[_\-]?key|apikey|access[_\-]?token|secret[_\-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})",
        ),
    ),
    # 私钥块
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]+?-----END[^-]+-----",
        ),
    ),
]


def _py_redact_secrets(text: str) -> str:
    """纯 Python 脱敏实现。"""
    if not text:
        return text
    for label, pattern in _REDACT_PATTERNS:
        if label in {"password", "api_key"}:
            text = pattern.sub(lambda m, lbl=label: m.group(0)[: m.start(1) - m.start(0)] + f"[REDACTED:{lbl}]", text)
        else:
            text = pattern.sub(f"[REDACTED:{label}]", text)
    return text


def redact_secrets(text: str) -> str:
    """扫描文本，把敏感信息替换为 [REDACTED:type]。

    对 password/api_key 等带捕获组的模式，仅 redact 值部分而非整个 key=value。
    其它模式直接替换整段匹配。
    """
    if not text:
        return text
    if _native.redact_secrets is not None:
        return _native.redact_secrets(text)
    return _py_redact_secrets(text)


__all__ = [
    "redact_secrets",
    "sanitize_domain",
    "sanitize_filename",
    "sanitize_url",
    "strip_ansi",
    "truncate",
]
