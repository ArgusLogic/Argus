# 侦察报告 — http://demo.testfire.net

> 生成时间: 2026-05-08 15:55:21

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | 安全头评分极低 (0/10) | 已配置仅 0 项 / 共 10 项关键安全头 | 对照 securityheaders.com 的 A 级要求逐项补齐 |
| 🔴 高 | 域名 75 天内到期 | WHOIS expiration: 2026-07-23 | 尽快续费；启用注册商自动续费功能 |
| 🟠 中 | X-Frame-Options 缺失 | `X-Frame-Options` 未配置 | 防止点击劫持；设置 `X-Frame-Options: SAMEORIGIN` 或 `DENY` |

## 🌐 拓扑

```
http://demo.testfire.net
└── A     198.18.239.76
```

## 概述

对 demo.testfire.net 进行被动侦察，发现该网站是 IBM 的演示应用（AltoroJ），使用 Apache Tomcat 服务器，IP 地址为 198.18.239.76。安全配置极差，完全没有配置任何 HTTP 安全头，存在多个安全风险。域名注册于 1999 年，使用 Akamai 的 DNS 服务。

## DNS 信息

```
A 记录: 198.18.239.76
AAAA 记录: 无
MX 记录: 无
NS 记录: 无
TXT 记录: 无
CNAME 记录: 无
```

## 子域名枚举

```
检测到通配符 DNS (*.demo.testfire.net → 198.18.0.0/15)，已过滤 2000 条假阳性，未发现真实存活子域名。
```

## HTTP 安全头分析

```
安全头评分: 0/10
已配置: 无
缺失: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy, COOP, CORP, COEP
服务器信息泄露: Apache-Coyote/1.1
```

## WHOIS 信息

```
域名: TESTFIRE.NET
注册商: Amazon Registrar, Inc.
创建时间: 1999-07-23T13:52:32Z
到期时间: 2026-07-23T13:52:32Z
最后修改: 2025-02-27T17:53:33Z
状态: client delete prohibited, client transfer prohibited, client update prohibited
名称服务器: ASIA3.AKAM.NET, EUR2.AKAM.NET, EUR5.AKAM.NET, NS1-206.AKAM.NET, NS1-99.AKAM.NET, USC2.AKAM.NET, USC3.AKAM.NET, USW2.AKAM.NET
```

## 其他发现

```
目标网站是 IBM 的 AltoroJ 演示应用，用于安全测试和教学目的。使用 Apache Tomcat 服务器（通过 Server 头 Apache-Coyote/1.1 可知）。域名历史较长（1999年注册），使用 Akamai CDN 的 DNS 服务。安全配置存在严重缺陷，建议在安全测试环境中使用。
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] browser_navigate on demo.testfire.net → 连接错误（避免重复尝试或换策略）
2. [2026-05] http_request on demo.testfire.net → 403 Forbidden（避免重复尝试或换策略）

---
*由 Argus 自动生成*
