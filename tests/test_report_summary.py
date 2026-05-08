"""Day2-1: 报告 Top-3 执行摘要启发式扫描的回归测试。"""

from __future__ import annotations

from tools._report_summary import (
    _SEVERITY_ORDER,
    build_executive_summary,
    collect_signals,
    render_top_n,
)

# ──────────────────────────────────────────────────────────────────────────
# header 信号
# ──────────────────────────────────────────────────────────────────────────


def test_scan_headers_all_missing_yields_high_signals() -> None:
    headers_text = """目标: https://example.com (HTTP 200)

已配置 (0):

缺失 (10):
  ✗ HSTS (Strict-Transport-Security) — 缺失 (强制 HTTPS)
  ✗ CSP (Content-Security-Policy) — 缺失 (限制资源)
  ✗ X-Frame-Options — 缺失 (防点击劫持)
  ✗ X-Content-Type-Options — 缺失 (防 MIME 嗅探)

⚠ Server 头泄露: cloudflare

安全头评分: 0/10
"""
    signals = collect_signals(headers=headers_text)
    keys = {s["key"] for s in signals}
    assert "missing_hsts" in keys
    assert "missing_csp" in keys
    assert "missing_xfo" in keys
    assert "server_disclosure" in keys
    assert "low_security_score" in keys


def test_scan_headers_present_dont_trigger() -> None:
    headers_text = """已配置 (3):
  ✓ HSTS: max-age=31536000
  ✓ CSP: default-src 'self'
  ✓ X-Frame-Options: SAMEORIGIN

缺失 (0):

安全头评分: 3/10
"""
    signals = collect_signals(headers=headers_text)
    keys = {s["key"] for s in signals}
    assert "missing_hsts" not in keys
    assert "missing_csp" not in keys
    assert "missing_xfo" not in keys


# ──────────────────────────────────────────────────────────────────────────
# directory 信号
# ──────────────────────────────────────────────────────────────────────────


def test_scan_directories_critical_exposure_git() -> None:
    dir_text = "目录枚举 — 发现 1/600:\n  [200] /.git/config  (1234 bytes)"
    signals = collect_signals(directories=dir_text)
    keys = {s["key"] for s in signals}
    assert "exposed_git" in keys
    git_sig = next(s for s in signals if s["key"] == "exposed_git")
    assert git_sig["severity"] == "critical"


def test_scan_directories_dotenv_critical() -> None:
    dir_text = "  [200] /.env  (320 bytes)"
    signals = collect_signals(directories=dir_text)
    assert any(s["key"] == "exposed_env" and s["severity"] == "critical" for s in signals)


def test_scan_directories_admin_panel_high() -> None:
    dir_text = "  [200] /admin/  (5500 bytes)"
    signals = collect_signals(directories=dir_text)
    assert any(s["key"] == "admin_panel_open" for s in signals)


def test_scan_directories_clean_no_signals() -> None:
    dir_text = "未发现可访问路径（已检测 600 个）"
    signals = collect_signals(directories=dir_text)
    assert signals == []


# ──────────────────────────────────────────────────────────────────────────
# port 信号
# ──────────────────────────────────────────────────────────────────────────


def test_scan_ports_db_exposed_critical() -> None:
    port_text = """端口扫描结果:
主机: example.com
  3306/tcp  open  mysql
  5432/tcp  open  postgresql
"""
    signals = collect_signals(open_ports=port_text)
    keys = [s["key"] for s in signals]
    assert any("port_db_exposed_3306" in k for k in keys)
    assert any("port_db_exposed_5432" in k for k in keys)
    assert all(s["severity"] == "critical" for s in signals if "port_db" in s["key"])


def test_scan_ports_ssh_high() -> None:
    port_text = "  22/tcp  open  ssh"
    signals = collect_signals(open_ports=port_text)
    assert any(s["key"].startswith("port_admin_exposed_22") for s in signals)


def test_scan_ports_telnet_critical() -> None:
    port_text = "  23/tcp  open  telnet"
    signals = collect_signals(open_ports=port_text)
    telnet = [s for s in signals if "23" in s["key"]]
    assert telnet and telnet[0]["severity"] == "critical"


# ──────────────────────────────────────────────────────────────────────────
# subdomain 信号
# ──────────────────────────────────────────────────────────────────────────


def test_scan_subdomains_devops_exposure() -> None:
    sub_text = """  jenkins.example.com → 1.2.3.4
  gitlab.example.com → 1.2.3.5
  kibana.example.com → 1.2.3.6
"""
    signals = collect_signals(subdomains=sub_text)
    devops = [s for s in signals if s["key"] == "subdomain_devops"]
    assert devops
    assert "jenkins" in devops[0]["evidence"] or "gitlab" in devops[0]["evidence"]


def test_scan_subdomains_dev_staging() -> None:
    sub_text = "  dev.example.com → 1.2.3.4\n  staging.example.com → 1.2.3.5\n"
    signals = collect_signals(subdomains=sub_text)
    assert any(s["key"] == "subdomain_nonprod" for s in signals)


# ──────────────────────────────────────────────────────────────────────────
# whois 信号
# ──────────────────────────────────────────────────────────────────────────


def test_scan_whois_expired() -> None:
    whois_text = "expiration: 2020-01-15"
    signals = collect_signals(whois_info=whois_text)
    expired = [s for s in signals if s["key"] == "whois_expired"]
    assert expired and expired[0]["severity"] == "critical"


def test_scan_whois_no_date_no_signal() -> None:
    whois_text = "registrar: GoDaddy\n"
    signals = collect_signals(whois_info=whois_text)
    assert all(not s["key"].startswith("whois_") for s in signals)


# ──────────────────────────────────────────────────────────────────────────
# 渲染 + 排序
# ──────────────────────────────────────────────────────────────────────────


def test_signals_sorted_by_severity() -> None:
    """critical 必须排在 high 之前；high 在 medium 之前。"""
    signals = collect_signals(
        headers="✗ HSTS — 缺失\n安全头评分: 0/10",
        directories="  [200] /.git/config  (123 bytes)",
        open_ports="  22/tcp  open  ssh",
    )
    # 第一个应该是 critical
    assert signals[0]["severity"] == "critical"
    # 顺序非递减
    severities = [_SEVERITY_ORDER[s["severity"]] for s in signals]
    assert severities == sorted(severities)


def test_render_top_n_returns_markdown_table() -> None:
    signals = [
        {"key": "k1", "severity": "high", "risk": "R1", "evidence": "E1", "suggestion": "S1"},
        {"key": "k2", "severity": "medium", "risk": "R2", "evidence": "E2", "suggestion": "S2"},
    ]
    out = render_top_n(signals, n=3)
    assert "## 🎯 执行摘要 Top-2" in out
    assert "| 级别 |" in out
    assert "🔴 高" in out
    assert "🟠 中" in out
    assert "R1" in out


def test_render_empty_returns_empty_string() -> None:
    assert render_top_n([], n=3) == ""
    assert build_executive_summary() == ""


def test_top_n_truncates() -> None:
    signals = [
        {"key": f"k{i}", "severity": "high", "risk": f"R{i}", "evidence": "E", "suggestion": "S"}
        for i in range(5)
    ]
    out = render_top_n(signals, n=3)
    # 标题里写的是 Top-3
    assert "Top-3" in out
    # 表里只有 3 行数据（除头部 2 行）
    body_lines = [line for line in out.splitlines() if line.startswith("|") and "---" not in line]
    assert len(body_lines) == 4  # 1 表头 + 3 数据行


def test_build_executive_summary_end_to_end() -> None:
    out = build_executive_summary(
        headers="✗ HSTS — 缺失\n安全头评分: 0/10",
        directories="  [200] /.git/config",
    )
    assert "🎯 执行摘要" in out
    assert "exposed_git" not in out  # key 不应渲染
    assert ".git" in out  # 证据里应含 .git
    assert "立即" in out  # critical 建议里有"立即"


def test_dedup_same_key_only_once() -> None:
    """两个 dir 命中同一种风险（多个 .git 路径）→ 仅出现一次。"""
    dir_text = "  [200] /.git/config\n  [200] /.git/HEAD\n  [200] /.git/refs/heads/main\n"
    signals = collect_signals(directories=dir_text)
    git_sigs = [s for s in signals if s["key"] == "exposed_git"]
    assert len(git_sigs) == 1
