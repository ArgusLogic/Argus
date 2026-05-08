"""Day2-1: 启发式扫描各 section 文本，抽取 Top-3 风险并渲染成 Markdown 卡片。

零 LLM 调用，纯字符串/正则扫描。设计目标：让用户打开报告 5 秒能看到"最该关注的 3 件事"。

风险信号库 (signal name -> severity / description / suggestion)：
  - missing_hsts          high   缺 HSTS         开启 max-age>=31536000
  - missing_csp           medium 缺 CSP          至少 default-src 'self'
  - missing_xfo           medium 缺 X-Frame-Opt  设置 SAMEORIGIN/DENY
  - server_disclosure     medium Server 头泄漏   隐藏中间件版本
  - powered_by_disclosure low    X-Powered-By    隐藏框架版本
  - dir_listing           high   目录索引开启   关闭 Apache Indexes
  - admin_panel_open      high   /admin 200/403  限制访问 + 强密码 + 2FA
  - exposed_git           critical .git 泄漏     立即移除 .git/config
  - exposed_env           critical .env 泄漏     立即移除并轮换密钥
  - phpmyadmin_open       high   pma 暴露        IP 白名单 + 认证
  - cleartext_http        medium 仅 HTTP         强制跳转 HTTPS
  - low_security_score    high   安全评分 ≤3/10  补齐缺失安全头
  - cdn_exposure          info   CDN 兜底       (无操作)
  - whois_expiring_soon   high   域名 90 天内到期 续费
  - whois_expired         critical 域名已过期    立即续费
  - port_db_exposed       critical 数据库端口对外 防火墙限制访问
  - port_admin_exposed    high   管理端口对外    SSH key + 限源 IP
  - subdomain_devops      medium dev/staging 暴露 防火墙 + 认证
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# ──────────────────────────────────────────────────────────────────────────
# 严重度排序：critical > high > medium > low > info
# ──────────────────────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_SEVERITY_LABEL = {
    "critical": "🔴 严重",
    "high": "🔴 高",
    "medium": "🟠 中",
    "low": "🟡 低",
    "info": "🔵 提示",
}


# ──────────────────────────────────────────────────────────────────────────
# 信号检测函数：返回 list[dict(severity,risk,evidence,suggestion)]
# ──────────────────────────────────────────────────────────────────────────

_SECURITY_HEADERS_INFO = (
    ("Strict-Transport-Security", "missing_hsts", "high", "HSTS 缺失",
     "强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000`"),
    ("Content-Security-Policy", "missing_csp", "medium", "CSP 缺失",
     "至少配置 `default-src 'self'`，逐步收紧到允许列表"),
    ("X-Frame-Options", "missing_xfo", "medium", "X-Frame-Options 缺失",
     "防止点击劫持；设置 `X-Frame-Options: SAMEORIGIN` 或 `DENY`"),
    ("X-Content-Type-Options", "missing_xcto", "low", "X-Content-Type-Options 缺失",
     "防止 MIME sniff 攻击；设置 `X-Content-Type-Options: nosniff`"),
)


def _scan_headers(headers_text: str) -> list[dict]:
    """从 header_analysis 文本里抽取风险信号。"""
    if not headers_text:
        return []
    out: list[dict] = []
    text = headers_text.lower()

    for header_name, key, severity, risk, suggestion in _SECURITY_HEADERS_INFO:
        # 工具输出形如 "✗ HSTS (Strict-Transport-Security) — 缺失 (...)" 或 "✓ HSTS: max-age=..."
        # 简单判定：包含 header 名 + "缺失"
        marker_lower = header_name.lower()
        if marker_lower in text:
            # 找到该行
            for line in headers_text.splitlines():
                if marker_lower in line.lower():
                    if "缺失" in line or "missing" in line.lower() or "✗" in line:
                        out.append(
                            {
                                "key": key,
                                "severity": severity,
                                "risk": risk,
                                "evidence": f"`{header_name}` 未配置",
                                "suggestion": suggestion,
                            }
                        )
                    break

    # Server / X-Powered-By 头泄露
    server_match = re.search(r"server\s*头泄露[:：]\s*(\S+)", headers_text, re.IGNORECASE)
    if server_match:
        out.append(
            {
                "key": "server_disclosure",
                "severity": "medium",
                "risk": "Server 头泄露中间件信息",
                "evidence": f"`Server: {server_match.group(1)}`",
                "suggestion": "在反代或框架层移除/伪装 Server 头",
            }
        )

    powered_match = re.search(r"x-powered-by\s*头泄露[:：]\s*(\S+)", headers_text, re.IGNORECASE)
    if powered_match:
        out.append(
            {
                "key": "powered_by_disclosure",
                "severity": "low",
                "risk": "X-Powered-By 头泄露框架版本",
                "evidence": f"`X-Powered-By: {powered_match.group(1)}`",
                "suggestion": "在中间件配置里禁用 X-Powered-By 头",
            }
        )

    # 安全评分极低
    score_match = re.search(r"安全(?:头)?评分[:：]\s*(\d+)\s*/\s*(\d+)", headers_text)
    if score_match:
        score, total = int(score_match.group(1)), int(score_match.group(2))
        if total > 0 and score <= total / 3:
            out.append(
                {
                    "key": "low_security_score",
                    "severity": "high",
                    "risk": f"安全头评分极低 ({score}/{total})",
                    "evidence": f"已配置仅 {score} 项 / 共 {total} 项关键安全头",
                    "suggestion": "对照 securityheaders.com 的 A 级要求逐项补齐",
                }
            )

    return out


_DIR_PATTERNS = (
    # (regex, key, severity, risk, suggestion)
    (
        re.compile(r"\[200\][^\n]*/\.git/?"),
        "exposed_git",
        "critical",
        ".git 仓库对外暴露",
        "**立即** 从 web root 移除 .git/，并轮换该仓库泄漏的所有密钥/凭证",
    ),
    (
        re.compile(r"\[200\][^\n]*/\.env\b"),
        "exposed_env",
        "critical",
        ".env 配置对外暴露",
        "**立即** 移除文件，假设其中所有密钥已泄漏并全部轮换",
    ),
    (
        re.compile(r"\[200\][^\n]*/(phpmyadmin|pma)/?"),
        "phpmyadmin_open",
        "high",
        "phpMyAdmin 对外可访问",
        "用 IP 白名单 + 认证保护；考虑迁移到内网管理通道",
    ),
    (
        re.compile(r"\[200\][^\n]*/(?:admin|administrator|wp-admin)/?"),
        "admin_panel_open",
        "high",
        "管理后台对外可访问",
        "限制 IP / VPN，开启 2FA，监控异常登录",
    ),
    (
        re.compile(r"\[200\][^\n]*/images/?\b"),
        "dir_listing",
        "high",
        "目录索引开启 (Apache Indexes)",
        "关闭 Indexes：`Options -Indexes` 或 nginx `autoindex off`",
    ),
    (
        re.compile(r"\[200\][^\n]*/backup", re.IGNORECASE),
        "exposed_backup",
        "critical",
        "备份文件对外暴露",
        "**立即** 移除；扫描历史 commit 是否泄漏敏感信息",
    ),
)


def _scan_directories(dir_text: str) -> list[dict]:
    if not dir_text:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for pattern, key, severity, risk, suggestion in _DIR_PATTERNS:
        match = pattern.search(dir_text)
        if match and key not in seen:
            seen.add(key)
            out.append(
                {
                    "key": key,
                    "severity": severity,
                    "risk": risk,
                    "evidence": f"`{match.group(0).strip()}`",
                    "suggestion": suggestion,
                }
            )
    return out


_PORT_RISK = {
    # port -> (key, severity, risk, suggestion)
    "3306": ("port_db_exposed", "critical", "MySQL 端口对外开放", "防火墙限制访问；强密码 + 启用 TLS"),
    "5432": ("port_db_exposed", "critical", "PostgreSQL 端口对外开放", "防火墙限制访问；强密码 + 启用 TLS"),
    "27017": ("port_db_exposed", "critical", "MongoDB 端口对外开放", "防火墙限制访问；启用认证"),
    "6379": ("port_db_exposed", "critical", "Redis 端口对外开放", "防火墙限制访问；设置 requirepass"),
    "22": ("port_admin_exposed", "high", "SSH 端口对外开放", "禁用密码登录改用 key；限源 IP"),
    "23": ("port_admin_exposed", "critical", "Telnet 端口对外开放（明文）", "立即关闭，改用 SSH"),
    "3389": ("port_admin_exposed", "high", "RDP 端口对外开放", "改用 VPN 接入；启用 NLA + MFA"),
    "21": ("port_admin_exposed", "high", "FTP 端口对外开放（明文）", "改用 SFTP/FTPS"),
}


def _scan_open_ports(port_text: str) -> list[dict]:
    if not port_text:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    # 工具输出形如 "  3306/tcp  open  mysql"
    for match in re.finditer(r"\b(\d+)/(?:tcp|udp)\s+open\b", port_text):
        port = match.group(1)
        if port in _PORT_RISK and port not in seen:
            key, severity, risk, suggestion = _PORT_RISK[port]
            out.append(
                {
                    "key": f"{key}_{port}",
                    "severity": severity,
                    "risk": risk,
                    "evidence": f"端口 {port}/tcp 状态 open",
                    "suggestion": suggestion,
                }
            )
            seen.add(port)
    return out


def _scan_subdomains(sub_text: str) -> list[dict]:
    """暴露的 dev/staging/jenkins 等敏感子域。"""
    if not sub_text:
        return []
    out: list[dict] = []
    sensitive_keywords = (
        "jenkins", "gitlab", "kibana", "grafana", "prometheus",
        "phpmyadmin", "jira", "confluence", "sonar", "rancher",
    )
    found_keywords: list[str] = []
    for kw in sensitive_keywords:
        if re.search(rf"\b{kw}\b", sub_text, re.IGNORECASE):
            found_keywords.append(kw)
    if found_keywords:
        out.append(
            {
                "key": "subdomain_devops",
                "severity": "medium",
                "risk": "DevOps / 内部工具子域暴露",
                "evidence": "出现 " + " / ".join(found_keywords[:3]) + (" 等" if len(found_keywords) > 3 else ""),
                "suggestion": "DevOps 子域加 IP 白名单 + 认证；不暴露给公网",
            }
        )

    # dev / staging / test 暴露
    if re.search(r"\b(dev|staging|test|qa)\b", sub_text, re.IGNORECASE):
        out.append(
            {
                "key": "subdomain_nonprod",
                "severity": "medium",
                "risk": "非生产环境子域 (dev/staging/test) 暴露",
                "evidence": "存在 dev/staging/test 类命名的子域",
                "suggestion": "非生产子域不暴露公网或加 basic auth",
            }
        )
    return out


def _scan_whois(whois_text: str) -> list[dict]:
    """域名即将到期/已到期。"""
    if not whois_text:
        return []
    out: list[dict] = []
    # 匹配 ISO 日期或常见格式
    for match in re.finditer(
        r"(?:expir|到期|过期)[^\n]*?(\d{4})[-/](\d{2})[-/](\d{2})",
        whois_text,
        re.IGNORECASE,
    ):
        try:
            y, m, d = map(int, match.groups())
            expiry = datetime(y, m, d, tzinfo=UTC)
            now = datetime.now(UTC)
            days = (expiry - now).days
        except ValueError:
            continue
        if days < 0:
            out.append(
                {
                    "key": "whois_expired",
                    "severity": "critical",
                    "risk": f"域名已过期 ({-days} 天)",
                    "evidence": f"WHOIS expiration: {expiry.date().isoformat()}",
                    "suggestion": "**立即** 续费，否则随时可能被竞标抢注",
                }
            )
        elif days <= 90:
            out.append(
                {
                    "key": "whois_expiring_soon",
                    "severity": "high",
                    "risk": f"域名 {days} 天内到期",
                    "evidence": f"WHOIS expiration: {expiry.date().isoformat()}",
                    "suggestion": "尽快续费；启用注册商自动续费功能",
                }
            )
        break  # 只取第一个 expiration
    return out


# ──────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────


def collect_signals(
    dns_info: str = "",
    headers: str = "",
    subdomains: str = "",
    open_ports: str = "",
    directories: str = "",
    whois_info: str = "",
) -> list[dict]:
    """扫描各 section 文本，返回所有命中的风险信号。"""
    signals: list[dict] = []
    signals.extend(_scan_headers(headers))
    signals.extend(_scan_directories(directories))
    signals.extend(_scan_open_ports(open_ports))
    signals.extend(_scan_subdomains(subdomains))
    signals.extend(_scan_whois(whois_info))
    # 去重（按 key）
    seen: set[str] = set()
    deduped: list[dict] = []
    for sig in signals:
        if sig["key"] not in seen:
            seen.add(sig["key"])
            deduped.append(sig)
    # 按 severity 排序
    deduped.sort(key=lambda s: _SEVERITY_ORDER.get(s["severity"], 99))
    return deduped


def render_top_n(signals: list[dict], n: int = 3) -> str:
    """渲染 Top-N 风险卡片为 Markdown table；signals 为空时返回空串。"""
    if not signals:
        return ""
    rows = []
    rows.append(f"## 🎯 执行摘要 Top-{min(n, len(signals))}\n")
    rows.append("| 级别 | 风险 | 证据 | 建议 |")
    rows.append("|---|---|---|---|")
    for sig in signals[:n]:
        label = _SEVERITY_LABEL.get(sig["severity"], sig["severity"])
        # 转义 markdown table 里的 |
        evidence = sig["evidence"].replace("|", "\\|")
        suggestion = sig["suggestion"].replace("|", "\\|")
        risk = sig["risk"].replace("|", "\\|")
        rows.append(f"| {label} | {risk} | {evidence} | {suggestion} |")
    return "\n".join(rows) + "\n"


def build_executive_summary(
    dns_info: str = "",
    headers: str = "",
    subdomains: str = "",
    open_ports: str = "",
    directories: str = "",
    whois_info: str = "",
    top_n: int = 3,
) -> str:
    """生成执行摘要的完整 Markdown 块（含标题）。无信号则返空串。"""
    signals = collect_signals(
        dns_info=dns_info,
        headers=headers,
        subdomains=subdomains,
        open_ports=open_ports,
        directories=directories,
        whois_info=whois_info,
    )
    return render_top_n(signals, n=top_n)
