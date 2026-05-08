# 侦察报告 — microsoft.com

> 生成时间: 2026-05-08 15:58:10

## 🌐 拓扑

```
microsoft.com
├── NS    ns1-39.azure-dns.com
├── NS    ns2-39.azure-dns.net
├── NS    ns3-39.azure-dns.org
├── NS    ns4-39.azure-dns.info
├── A     198.18.255.17
├── A     198.18.0.0
└── MX    microsoft-com.mail.protection.outlook.com
```

## 概述

对 microsoft.com 执行了被动侦察（read-only），涵盖 DNS 全记录查询、WHOIS 注册信息、HTTP 安全头评估和子域名枚举。目标为 Microsoft 核心域名，托管于 Azure DNS 基础设施，邮件由 Exchange Online Protection 保障。DNS 层面因网络环境收到 wildcard DNS 干扰（*.microsoft.com → 198.18.0.0/15），但核心记录正常。安全头评分 1/10，仅配置了 HSTS，存在较大安全头配置缺口。

## DNS 信息

```
## DNS 记录

| 记录类型 | 值 |
|---------|---|
| **A** | 198.18.255.17（注：此 IP 属于保留地址段 198.18.0.0/15，用于网络基准测试，表明 DNS 查询受到本地网络环境影响，非真实微软服务器 IP） |
| **AAAA** | ⚠ 未查询到 IPv6 记录 |
| **MX** | `10 microsoft-com.mail.protection.outlook.com.`（Exchange Online Protection） |
| **NS** | `ns1-39.azure-dns.com.`、`ns2-39.azure-dns.net.`、`ns3-39.azure-dns.org.`、`ns4-39.azure-dns.info.` |
| **TXT** | ⚠ 未查询到记录 |
| **CNAME** | ⚠ 未查询到记录 |

**说明**：A 记录返回 198.18.x.x 是本地网络/中间设备的基准测试地址，非微软真实 IP。权威 DNS 服务器指向 Azure DNS，MX 指向 Microsoft 365 邮件防护。
```

## 子域名枚举

```
## 子域名枚举

### 状态
- **结果**: ⚠ 未发现存活子域名（受 wildcard DNS 干扰）
- **检测量**: 2000 个常用子域
- **过滤数**: 1998 条疑似假阳性（`*.microsoft.com → 198.18.0.0/15`）
- **说明**: 网络环境存在 wildcard DNS 解析（任意子域名均返回 198.18.x.x），导致无法通过 DNS 验证方式发现真实存活子域名。建议在无 wildcard 干扰的网络环境下重新枚举。
```

## HTTP 安全头分析

```
## HTTP 安全头分析

**目标**: https://microsoft.com → 200 OK（自动跳转 zh-hk 区域版）

### 已配置 (1/10)
| 安全头 | 值 |
|--------|-----|
| ✅ **HSTS** | `max-age=31536000; includeSubDomains` |

### 缺失 (9/10)
| 安全头 | 风险说明 |
|--------|----------|
| ❌ CSP (Content-Security-Policy) | 无限制 → 可能被 XSS 利用 |
| ❌ X-Frame-Options | 无保护 → 可被嵌入 iframe 点击劫持 |
| ❌ X-Content-Type-Options | 无保护 → 允许 MIME 嗅探 |
| ❌ X-XSS-Protection | 缺失（已过时但仍常见） |
| ❌ Referrer-Policy | 无控制 → 可能泄露 URL |
| ❌ Permissions-Policy | 无限制 → 浏览器 API 均可调用 |
| ❌ COOP | 无跨域隔离 |
| ❌ CORP | 无跨域资源限制 |
| ❌ COEP | 无跨域嵌入策略 |

**安全头评分**: ⭐ **1/10**
```

## WHOIS 信息

```
## WHOIS 注册信息

| 字段 | 值 |
|------|-----|
| **域名** | MICROSOFT.COM |
| **注册商** | MarkMonitor Inc. |
| **创建时间** | 1991-05-02T04:00:00Z（已注册 35 年） |
| **到期时间** | 2027-05-03T04:00:00Z |
| **最后修改** | 2026-01-29T18:46:57Z |
| **状态** | `clientDeleteProhibited`, `clientTransferProhibited`, `clientUpdateProhibited`, `serverDeleteProhibited`, `serverTransferProhibited`, `serverUpdateProhibited`（全面保护锁定） |
| **名称服务器** | NS1-39.AZURE-DNS.COM, NS2-39.AZURE-DNS.NET, NS3-39.AZURE-DNS.ORG, NS4-39.AZURE-DNS.INFO |
```

## 其他发现

```
## 页面信息

| 项目 | 内容 |
|------|------|
| **首页标题** | Microsoft – AI、雲端、生產力、運算、遊戲及應用程式 |
| **最终 URL** | https://www.microsoft.com/zh-hk/ |
| **状态码** | 200 OK |
| **截图** | ✅ 已保存 (microsoft-homepage.png) |

## 总结与建议

1. **基础设施**：微软使用 Azure DNS 作为权威 DNS 服务，邮件系统基于 Exchange Online Protection（Microsoft 365），域名注册由 MarkMonitor 保护并锁定。
2. **安全头短板**：虽然首页只配了 HSTS（评分 1/10），但像微软这样的大型站点通常在子域名（如 login.live.com、portal.azure.com）上配置了完整安全头。主站首页的轻量配置是常见设计，并非安全缺陷。
3. **子域名发现受限**：因 wildcard DNS 环境干扰，DNS 枚举无法可靠检测存活子域名。在未授权的情况下也不应尝试主动爆破。
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] header_analysis on testphp.vulnweb.com → 5xx 服务端错误（避免重复尝试或换策略）
2. [2026-05] browser_navigate on testphp.vulnweb.com → 连接错误（避免重复尝试或换策略）
3. [2026-05] http_request on testphp.vulnweb.com → 5xx 服务端错误（避免重复尝试或换策略）

---
*由 Argus 自动生成*
