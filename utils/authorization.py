"""vuln_scan 工具的授权门：只有"已声明授权"的目标才能跑漏洞探测。

判定逻辑（命中任一即放行）：
  1. URL 的 host 命中 config.toml [security] allowed_domains
  2. URL 的 host 命中 ~/.argus/credentials.toml 的 [targets.*]
     （能给出登录凭据 = 用户对该目标拥有授权）

返回 (allowed: bool, reason: str)。reason 给 LLM/用户清晰提示如何放行。

⚠ 这是 vuln_scan 系列工具的最终守门员；engine 层的 _check_domain_whitelist
不一定校验所有 vuln_* 工具（参数名各异），所以必须在工具内部再核对一次。
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


def is_authorized_target(url: str) -> tuple[bool, str]:
    """判断 url 的目标主机是否被授权进行漏洞探测。"""
    host = _extract_host(url)
    if not host:
        return False, f"无法从 URL 解析 host: {url!r}"

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
        f"目标 {host!r} 未授权进行漏洞探测。请二选一：\n"
        f"  ① 在 config.toml [security] 添加 allowed_domains = [{host!r}]\n"
        f"  ② 在 ~/.argus/credentials.toml 添加 [targets.{host!r}] 节（证明持有该目标凭据）",
    )
