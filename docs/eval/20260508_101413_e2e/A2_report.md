# 侦察报告 — http://demo.testfire.net

> 生成时间: 2026-05-08 18:16:42

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |
| 🔴 高 | 安全头评分极低 (0/10) | 已配置仅 0 项 / 共 10 项关键安全头 | 对照 securityheaders.com 的 A 级要求逐项补齐 |
| 🟠 中 | CSP 缺失 | `Content-Security-Policy` 未配置 | 至少配置 `default-src 'self'`，逐步收紧到允许列表 |

## 🌐 拓扑

```
http://demo.testfire.net
└── A     198.18.15.169
```

## 概述

对 demo.testfire.net 执行中强度主动侦察。DNS 解析到 198.18.15.169（RFC2544 保留段），HTTP 可访问但端口扫描因 IP 不可达而无结果。安全头评分 0/10，服务器泄露 Apache-Coyote/1.1。通配符 DNS 导致子域名枚举全部过滤。目录爆破仅发现根路径。WHOIS 查询失败。

## DNS 信息

```
A 记录: demo.testfire.net → 198.18.15.169
注意: 该 IP 属于 RFC2544 基准测试保留段 (198.18.0.0/15)，仅在特定网络环境中可路由。
```

## 子域名枚举

```
⚠️ 检测到通配符 DNS (*.testfire.net → 198.18.0.0/15)，已过滤 2000 条疑似假阳性。
未发现真实存活子域名。
```

## 开放端口

```
❌ 未发现开放端口。
目标 IP 198.18.15.169 属于 RFC2544 保留段，从当前侦察网络不可路由，nmap 无法到达。
已扫描端口: 21-25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017
```

## 目录枚举

```
目录枚举结果 (190 条路径测试):
  [200] / (9405 bytes)
其余 189 条路径未返回有效响应（可能因 IP 不可达或路径不存在）。
```

## HTTP 安全头分析

```
安全头评分: 0/10 ❌

已配置: 无

缺失 (全部 10 项):
  ✗ HSTS (Strict-Transport-Security)
  ✗ CSP (Content-Security-Policy)
  ✗ X-Frame-Options
  ✗ X-Content-Type-Options
  ✗ X-XSS-Protection
  ✗ Referrer-Policy
  ✗ Permissions-Policy
  ✗ COOP (Cross-Origin-Opener-Policy)
  ✗ CORP (Cross-Origin-Resource-Policy)
  ✗ COEP (Cross-Origin-Embedder-Policy)

⚠ 服务器信息泄露: Apache-Coyote/1.1
```

## WHOIS 信息

```
❌ 查询失败 — RDAP 不可达，旧 WHOIS API 也返回错误。testfire.net 的注册信息未能获取。
```

## 其他发现

```
## 侦察环境说明
- 目标 demo.testfire.net 解析到 198.18.15.169（RFC2544 保留段），HTTP 请求可通过浏览器代理访问，但 TCP 端口扫描和目录爆破受限于网络不可达。
- 建议: 若需完整端口扫描和目录枚举，需在可路由到目标的网络环境中执行（如 VPN 或本地网络）。
- demo.testfire.net 是 IBM 的 AltoroJ 演示银行应用，用于安全测试教学。

## 风险摘要
| 风险项 | 严重程度 | 说明 |
|--------|----------|------|
| 安全头全部缺失 | 高 | 0/10，无任何安全头保护 |
| 服务器版本泄露 | 中 | Apache-Coyote/1.1 暴露中间件信息 |
| 通配符 DNS | 信息 | 任何 *.testfire.net 均解析，可能被利用 |
| WHOIS 不可达 | 信息 | 无法验证域名注册信息 |
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] browser_navigate on demo.testfire.net → 连接错误（避免重复尝试或换策略）
2. [2026-05] http_request on demo.testfire.net → 403 Forbidden（避免重复尝试或换策略）
3. [2026-05] net_info on (unknown) → 限流 429（避免重复尝试或换策略）

---
*由 Argus 自动生成*
