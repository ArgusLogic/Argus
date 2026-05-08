"""vuln_scan 工具的授权门——**默认放行**，可通过 config 开严格模式。

策略（v2）：
  默认 [security].strict_authorization = false：
    所有目标自动放行。LLM 想扫什么扫什么，由用户对目标合法性自负其责。
  严格模式 [security].strict_authorization = true：
    走原"双路授权门"——命中任一才放行：
      路径 1: host 命中 config.toml [security].allowed_domains
      路径 2: host 命中 ~/.argus/credentials.toml [targets.*]（凭据持有 = 授权证明）
    用于合规咨询 / 红蓝对抗 / 多人共享 Argus 时强约束目标范围。

返回 (allowed: bool, reason: str)。reason 提供给 LLM / 审计日志。

历史背景：v1 默认严格，每次新目标都要改 config.toml，交互体验差；v2 翻转默认，
代码护栏保留，开关一翻即恢复严格（无破坏性删除）。
"""

from __future__ import annotations

from urllib.parse import urlparse


def _extract_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host.lower()
    except Exception:
        return ""


def _is_strict_mode() -> bool:
    """读取 config.toml [security].strict_authorization；默认 False（放行）。"""
    try:
        from utils.config import get_section

        sec = get_section("security")
        return bool(sec.get("strict_authorization", False))
    except Exception:
        return False


def is_authorized_target(url: str) -> tuple[bool, str]:
    """判断 url 的目标主机是否被授权进行漏洞探测。

    默认放行（v2 行为）；仅当 [security].strict_authorization=true 时才走双路授权门。
    """
    host = _extract_host(url)
    if not host:
        return False, f"无法从 URL 解析 host: {url!r}"

    # 默认放行模式
    if not _is_strict_mode():
        return True, f"host {host!r} 已放行（strict_authorization=false，默认非严格模式）"

    # ── 严格模式 ──
    # 路径 1：config.toml [security] allowed_domains
    try:
        from utils.config import get_section

        sec = get_section("security")
        allowed = sec.get("allowed_domains") or []
        if isinstance(allowed, list):
            for d in allowed:
                d_l = str(d).lower().strip()
                if not d_l:
                    continue
                if host == d_l or host.endswith("." + d_l):
                    return True, f"host {host!r} 命中 config.toml allowed_domains [{d_l!r}]"
    except Exception:
        pass

    # 路径 2：credentials.toml [targets.*]（凭据持有 = 授权证明）
    try:
        from utils.credentials import _load

        creds = _load()
        for target_host in creds:
            t_l = str(target_host).lower().strip()
            # credentials.toml 的 key 可能是 'host:port'，剥端口对比
            t_host_only = t_l.split(":")[0]
            if host == t_host_only or host.endswith("." + t_host_only):
                return True, f"host {host!r} 命中 credentials.toml [targets.{target_host!r}]"
    except Exception:
        pass

    return (
        False,
        f"目标 {host!r} 未授权（严格模式）。请三选一：\n"
        f"  ① config.toml [security].strict_authorization = false  （关闭严格模式，最常用）\n"
        f"  ② config.toml [security].allowed_domains 加 {host!r}\n"
        f"  ③ ~/.argus/credentials.toml 加 [targets.{host!r}] 节（证明持有凭据）",
    )
