# 侦察报告 — demo.testfire.net

> 生成时间: 2026-05-08 15:54:12

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |
| 🔴 高 | 域名 75 天内到期 | WHOIS expiration: 2026-07-23 | 尽快续费；启用注册商自动续费功能 |
| 🟠 中 | CSP 缺失 | `Content-Security-Policy` 未配置 | 至少配置 `default-src 'self'`，逐步收紧到允许列表 |

## 🌐 拓扑

```
demo.testfire.net
├── NS    testfire.net
├── NS    akam.net
└── A     198.18.231.69
```

## 概述

对 demo.testfire.net 完成被动（只读）侦察。目标解析到单一 IPv4 地址 198.18.231.69，托管在 Akamai 的 Wildcard DNS 基础设施上。WHOIS 显示根域 testfire.net 注册于 1999 年（Amazon Registrar），使用了 8 台 Akamai 权威 NS 且锁定 Transfer/Delete/Update。安全头评分 0/10，服务端为 Apache-Coyote/1.1（Tomcat），未配置任何现代安全头部。子域名枚举因 Wildcard DNS 干扰未发现存活子域。

## DNS 信息

```
| 记录类型 | 结果 |
|----------|------|
| A | 198.18.231.69 |
| AAAA | 无 |
| MX | 无 |
| NS | 无（根域 testfire.net 使用 8 台 akam.net NS） |
| TXT | 无 |
| CNAME | 无 |

备注：demo.testfire.net 直接解析到 A 记录，无 CNAME 别名。根域 testfire.net 的 8 台权威 NS 均为 Akamai（ASIA3/EUR2/EUR5/NS1-206/NS1-99/USC2/USC3/USW2），典型的企业 CDN/WAF 架构。
```

## 子域名枚举

```
**Wildcard DNS 已确认：`*.demo.testfire.net → 198.18.0.0/15`**

枚举 2000 条内置字典后，所有查询均被 Wildcard 匹配，无法区分真实子域与假阳性。通过 IP 范围过滤已排除全部疑似假阳结果。**未发现存活子域名。**

> 这意味着 demo.testfire.net 下的任意随机子域（如 `random123.demo.testfire.net`）都会解析到 Akamai 的 IP 段，这是典型的企业 WAF/边缘网络配置。
```

## 开放端口

```
被动侦察 — 未执行端口扫描（按用户要求只读模式）
```

## 目录枚举

```
被动侦察 — 未执行目录爆破（按用户要求只读模式）
```

## HTTP 安全头分析

```
| 安全头 | 状态 | 说明 |
|--------|------|------|
| HSTS (Strict-Transport-Security) | ✗ 缺失 | 无强制 HTTPS，存在降级攻击风险 |
| CSP (Content-Security-Policy) | ✗ 缺失 | 无资源来源限制，XSS 风险敞口 |
| X-Frame-Options | ✗ 缺失 | 无点击劫持防护 |
| X-Content-Type-Options | ✗ 缺失 | 无 MIME 嗅探防护 |
| X-XSS-Protection | ✗ 缺失 | 浏览器 XSS 过滤未启用（已过时） |
| Referrer-Policy | ✗ 缺失 | Referer 头泄露未控制 |
| Permissions-Policy | ✗ 缺失 | 浏览器特性权限未限制 |
| COOP (Cross-Origin-Opener-Policy) | ✗ 缺失 | 跨域窗口隔离未配置 |
| CORP (Cross-Origin-Resource-Policy) | ✗ 缺失 | 跨域资源策略未配置 |
| COEP (Cross-Origin-Embedder-Policy) | ✗ 缺失 | 跨域嵌入策略未配置 |

**评分: 0/10** — 10 项关键安全头全部缺失。

⚠️ **信息泄露**: `Server: Apache-Coyote/1.1` — 暴露了后端为 Apache Tomcat。
```

## Cookie 信息

```
被动侦察 — 未打开页面，无 Cookie 数据
```

## 站点链接

```
被动侦察 — 未爬取页面链接
```

## 表单发现

```
被动侦察 — 未提取表单
```

## JS 分析

```
被动侦察 — 未分析 JS 文件
```

## WHOIS 信息

```
| 字段 | 值 |
|------|-----|
| 域名 | TESTFIRE.NET |
| 注册商 | Amazon Registrar, Inc. |
| 创建时间 | 1999-07-23T13:52:32Z |
| 到期时间 | 2026-07-23T13:52:32Z |
| 最后修改 | 2025-02-27T17:53:33Z |
| 状态 | clientDeleteProhibited, clientTransferProhibited, clientUpdateProhibited |
| 权威 NS (8台) | ASIA3.AKAM.NET, EUR2.AKAM.NET, EUR5.AKAM.NET, NS1-206.AKAM.NET, NS1-99.AKAM.NET, USC2.AKAM.NET, USC3.AKAM.NET, USW2.AKAM.NET |

分析：域名年龄近 27 年（1999 注册），锁定防止未授权转移。全部 8 台 NS 归属 Akamai，这是 IBM/Altoro Mutual 的安全演练靶场，托管在 Akamai 边缘网络上。
```

## 其他发现

```
### 关键发现
1. **目标身份确认**：`demo.testfire.net` 是 IBM/Altoro Mutual 的公开 Web 安全演练靶场，后端为 Java（Tomcat）。
2. **基础设施**：完全托管于 Akamai 全球边缘网络，Wildcard DNS 覆盖整个 `*.demo.testfire.net` 子域空间。
3. **安全态势**：安全头 0/10，靶场设计有意暴露漏洞以用于教育/演练目的。
4. **历史教训**：该目标对外部请求有严格限制（此前遇到过连接错误、403 Forbidden），被动侦察未触发封禁。

### 风险评价
- 🔴 **高危**：所有 10 项安全头缺失，无 HSTS/CSP/X-Frame-Options
- 🟡 **中危**：服务端版本泄露 (Apache-Coyote/1.1)
- 🟢 **低危**：Wildcard DNS 对于边缘网络属于正常配置
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] browser_navigate on demo.testfire.net → 连接错误（避免重复尝试或换策略）
2. [2026-05] http_request on demo.testfire.net → 403 Forbidden（避免重复尝试或换策略）

---
*由 Argus 自动生成*
