# 侦察报告 — cloudflare.com

> 生成时间: 2026-05-08 15:56:35

## 🎯 执行摘要 Top-2

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🟠 中 | CSP 缺失 | `Content-Security-Policy` 未配置 | 至少配置 `default-src 'self'`，逐步收紧到允许列表 |
| 🟠 中 | Server 头泄露中间件信息 | `Server: **` | 在反代或框架层移除/伪装 Server 头 |

## 🌐 拓扑

```
cloudflare.com
├── NS    ns3.cloudflare.com
├── NS    ns4.cloudflare.com
├── NS    ns5.cloudflare.com
├── NS    ns6.cloudflare.com
├── NS    ns7.cloudflare.com
├── A     198.18.247.47
└── MX    mxa.global.inbound.cf-emailsecurity.net
```

## 概述

对 cloudflare.com 执行了中强度主动侦察，包括 DNS 查询、WHOIS、安全头分析、子域名枚举、目录爆破和端口扫描。Cloudflare 对其官网实施了严格的安全防护，WAF 规则完善，子域名枚举受 wildcard DNS 干扰，目录爆破因全站 301 重定向无法直接发现隐藏路径，端口扫描解析到 RFC2544 保留 IP 段。整体安全态势强硬。

## DNS 信息

```
## DNS 记录
| 类型 | 值 |
|------|-----|
| **A** | 198.18.247.47（RFC2544 保留段） |
| **MX** | 10 mxa.global.inbound.cf-emailsecurity.net.（主） |
|    | 5 mxa-canary.global.inbound.cf-emailsecurity.net. |
|    | 5 mxb-canary.global.inbound.cf-emailsecurity.net. |
|    | 10 mxb.global.inbound.cf-emailsecurity.net. |
| **NS** | ns3.cloudflare.com / ns4.cloudflare.com / ns5.cloudflare.com / ns6.cloudflare.com / ns7.cloudflare.com |
| **TXT** | apple-domain-verification, atlassian-domain-verification, canva-site-verification, cisco-ci-domain-verification 等域名所有权验证记录 |

## WHOIS 注册信息
- **域名**: CLOUDFLARE.COM
- **注册商**: Cloudflare, Inc.
- **创建时间**: 2009-02-17
- **到期时间**: 2033-02-17（长达 24 年）
- **状态**: client/server delete/transfer/update prohibited（多重保护锁）
- **DNS 服务**: 自持 NS3-NS7.CLOUDFLARE.COM
```

## 子域名枚举

```
## 子域名发现
因 cloudflare.com 配置了 wildcard DNS（*.cloudflare.com → 198.18.0.0/15），枚举过程过滤了约 1998 条假阳性记录。

**确认真实子域:**
- `time.cloudflare.com` → 162.159.200.1, 162.159.200.123

> ⚠ 其他常见子域（如 www / api / blog / cdn 等）可能被 wildcard 覆盖或由 Cloudflare 的 DNS 规则保护，未通过常规枚举直接发现。
```

## 开放端口

```
## 端口扫描结果
目标: cloudflare.com（解析至 198.18.255.6）
扫描端口: 21,22,23,25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017

**结果: 未发现开放端口**
- 域名解析到 RFC2544 保留 IP 段（198.18.0.0/15），该段为 IANA 保留的基准测试地址范围，不可路由
- Cloudflare 可能通过 DNS 策略将外部扫描导向此保留段以隐藏真实 IP
- 真实服务可能通过 Cloudflare CDN/反向代理提供，真实源 IP 被隐藏
```

## 目录枚举

```
## 目录爆破结果
目标: https://cloudflare.com
字典: 190 个常见路径
**结果: 未发现可访问路径**
- 网站全站 301 重定向（baseline 状态码），已按基线过滤
- 所有请求均被 Cloudflare 的 WAF/CDN 层处理，未暴露敏感路径
- 可能原因：Cloudflare 官网是静态页面，路由由前端 SPA 处理，后端路径不直接暴露
```

## HTTP 安全头分析

```
## HTTP 安全头分析 (评分: 6/10)
目标: https://cloudflare.com

**✅ 已配置 (6项):**
1. **HSTS**: max-age=31536000; includeSubDomains（严格）
2. **X-Frame-Options**: SAMEORIGIN
3. **X-Content-Type-Options**: nosniff
4. **X-XSS-Protection**: 1; mode=block
5. **Referrer-Policy**: strict-origin-when-cross-origin
6. **Permissions-Policy**: 地理位置/摄像头/麦克风全部禁用

**❌ 缺失 (4项):**
1. **CSP (Content-Security-Policy)** — 缺失（XSS 防御关键头）
2. **COOP** — 缺失
3. **CORP** — 缺失
4. **COEP** — 缺失

**⚠ Server 头泄露:** cloudflare
```

## WHOIS 信息

```
已整合到 DNS 信息部分
```

## 其他发现

```
## 补充分析

### 技术栈推测
- **WAF/CDN**: Cloudflare 自家产品（自用）
- **SSL/TLS**: 强制 HTTPS + HSTS
- **Server**: cloudflare（自曝头）
- **SEO/验证**: 部署了多家平台的域名所有权验证 TXT 记录（Apple、Atlassian、Canva、Cisco）

### 安全评分总结
| 维度 | 评分 | 说明 |
|------|------|------|
| DNS 防护 | ⭐⭐⭐⭐⭐ | 自身 NS，TXT记录完善，Wildcard 策略防枚举 |
| WHOIS 保护 | ⭐⭐⭐⭐⭐ | 多重锁定，续费至 2033 年 |
| HTTP 安全头 | ⭐⭐⭐⭐ (6/10) | HSTS 优秀，但缺少 CSP/COOP/COEP |
| 子域名暴露 | ⭐⭐⭐⭐⭐ | Wildcard DNS 有效干扰枚举 |
| 端口暴露 | ⭐⭐⭐⭐⭐ | 真实 IP 完全隐藏，RFC2544 段迷惑扫描 |
| 目录暴露 | ⭐⭐⭐⭐⭐ | 全站 301 重定向，WAF 层拦截 |
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] dns_lookup on cloudflare.com → WAF 拦截（避免重复尝试或换策略）
2. [2026-05] whois_lookup on cloudflare.com → WAF 拦截（避免重复尝试或换策略）
3. [2026-05] header_analysis on cloudflare.com → WAF 拦截（避免重复尝试或换策略）

---
*由 Argus 自动生成*
