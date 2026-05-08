# 侦察报告 — demo.testfire.net

> 生成时间: 2026-05-08 15:52:39

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |
| 🔴 高 | 安全头评分极低 (0/10) | 已配置仅 0 项 / 共 10 项关键安全头 | 对照 securityheaders.com 的 A 级要求逐项补齐 |
| 🔴 高 | 域名 75 天内到期 | WHOIS expiration: 2026-07-23 | 尽快续费；启用注册商自动续费功能 |

## 🌐 拓扑

```
demo.testfire.net
├── A     198.18.223.82
└── 子域    2000 项被 wildcard 过滤 ⚠
```

## 概述

对 demo.testfire.net 完成了完整被动侦察（read-only）。DNS 解析指向 RFC 2544 保留地址 198.18.223.82；WHOIS 显示注册在 Amazon Registrar，使用 Akamai 托管 DNS；安全头评分极低（0/10），无任何安全配置；子域名枚举发现泛解析（wildcard DNS），未过滤出存活子域名。该域名似乎被某中间设备（防火墙/CDN/本地配置）拦截，实际应用服务无法直接触达。

## DNS 信息

```
=== demo.testfire.net DNS 查询 ===

记录类型 | 值
A | 198.18.223.82

备注：198.18.0.0/15 为 RFC 2544 网络基准测试保留地址。该解析结果通常意味着流量被中间设备（如本地 hosts 配置、防火墙、VPN 或代理）拦截/重定向，而非真实服务器 IP。

子域名枚举发现 *.demo.testfire.net 存在泛解析（wildcard DNS），均指向 198.18.0.0/15 子网。
```

## 子域名枚举

```
=== 子域名枚举结果 ===

检测到 wildcard DNS 泛解析（*.demo.testfire.net → 198.18.0.0/15）
已过滤 2000 条疑似假阳性记录
未发现 demo.testfire.net 的存活子域名

说明：泛解析意味着任何不存在的子域名都会返回一个 IP，无法通过 DNS 方式有效枚举子域名。建议通过其他渠道（JS 分析、证书透明度日志等）发现子域名。
```

## HTTP 安全头分析

```
=== HTTP 安全头分析 ===

目标: http://demo.testfire.net (HTTP 200)

已配置安全头: 0 项
缺失安全头: 10 项
安全头评分: 0/10

详细状态:
✗ HSTS (Strict-Transport-Security) — 缺失
✗ CSP (Content-Security-Policy) — 缺失
✗ X-Frame-Options — 缺失
✗ X-Content-Type-Options — 缺失
✗ X-XSS-Protection — 缺失
✗ Referrer-Policy — 缺失
✗ Permissions-Policy — 缺失
✗ COOP (Cross-Origin-Opener-Policy) — 缺失
✗ CORP (Cross-Origin-Resource-Policy) — 缺失
✗ COEP (Cross-Origin-Embedder-Policy) — 缺失

⚠ Server 头泄露: Apache-Coyote/1.1

安全风险提示: 全部安全头缺失，且 Server 头泄露了 Apache-Coyote/1.1（Apache Tomcat 标志），为攻击者提供了技术栈信息。
```

## WHOIS 信息

```
=== WHOIS 注册信息 ===

域名: testfire.net (子域查询回退到注册域)
注册商: Amazon Registrar, Inc.
创建时间: 1999-07-23T13:52:32Z
到期时间: 2026-07-23T13:52:32Z
最后修改: 2025-02-27T17:53:33Z
状态: clientDeleteProhibited, clientTransferProhibited, clientUpdateProhibited

名称服务器 (Akamai):
- ASIA3.AKAM.NET
- EUR2.AKAM.NET
- EUR5.AKAM.NET
- NS1-206.AKAM.NET
- NS1-99.AKAM.NET
- USC2.AKAM.NET
- USC3.AKAM.NET
- USW2.AKAM.NET
```

## 其他发现

```
=== 补充发现 ===

1. IP 地址 198.18.223.82 属于 RFC 2544 保留地址段（198.18.0.0/15），该地址段被 IANA 保留用于网络基准测试。该域名被解析到此地址，说明：
   - 可能在本地 hosts 文件中被配置为测试地址
   - 或流量被 VPN/代理/firewall 拦截
   - 或该域名在 DNS 层面被重定向

2. Server 头泄露 Apache-Coyote/1.1 表明后端运行 Apache Tomcat（Java Servlet 容器）。

3. 直接 HTTP 请求返回 403 Forbidden（历史记录），浏览器访问连接错误，进一步证实该域名不可直接访问。
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] browser_navigate on demo.testfire.net → 连接错误（避免重复尝试或换策略）
2. [2026-05] http_request on demo.testfire.net → 403 Forbidden（避免重复尝试或换策略）

---
*由 Argus 自动生成*
