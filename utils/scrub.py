"""敏感字段脱敏：日志 / session_db / 报告写入前调 scrub() 一次。

零依赖。命中以下模式时把 value 段替换为 ``***``：

  - ``password = xxx`` / ``passwd: xxx`` / ``pwd:xxx``
  - ``"password": "xxx"`` / ``'password': 'xxx'`` （JSON）
  - ``Authorization: Bearer xxxxxxx`` / ``Authorization: Basic xxxxxxx``
  - ``api[_-]?key = xxx``
"""

from __future__ import annotations

import re

# 同时覆盖 toml/yaml/JSON/k=v/k:v 多种语法
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JSON: "password": "xxx" / 'password': 'xxx' / "passwd":"xxx"（含转义反斜杠）
    (
        re.compile(
            r"""(\\?["'](?:password|passwd|pwd)\\?["']\s*:\s*\\?["'])([^"'\\]{1,200})(\\?["'])""",
            re.IGNORECASE,
        ),
        r"\1***\3",
    ),
    # k=v / k: v 形式（toml/yaml/k=v 均覆盖）
    (
        re.compile(
            r"""(\b(?:password|passwd|pwd)\b\s*[:=]\s*)("?)([^"\s,;}]+)("?)""",
            re.IGNORECASE,
        ),
        r"\1\2***\4",
    ),
    # Authorization: Bearer / Basic
    (
        re.compile(
            r"(\bAuthorization\s*[:=]\s*(?:Bearer|Basic)\s+)([A-Za-z0-9._\-+/=]+)",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # JSON: "api_key": "xxx" / 'api-key': 'xxx'
    (
        re.compile(
            r"""(\\?["']api[_-]?key\\?["']\s*:\s*\\?["'])([^"'\\]{1,200})(\\?["'])""",
            re.IGNORECASE,
        ),
        r"\1***\3",
    ),
    # api_key / apikey / api-key (k=v / k: v)
    (
        re.compile(
            r"""(\bapi[_-]?key\b\s*[:=]\s*)("?)([^"\s,;}]+)("?)""",
            re.IGNORECASE,
        ),
        r"\1\2***\4",
    ),
)


def scrub(text: str) -> str:
    """对一段文本做凭据脱敏。空值/非字符串原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out
