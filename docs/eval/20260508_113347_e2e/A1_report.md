# 侦察报告 — http://127.0.0.1:8080

> 生成时间: 2026-05-08 19:34:52

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 严重 | .git 仓库对外暴露 | `[200] /.git` | **立即** 从 web root 移除 .git/，并轮换该仓库泄漏的所有密钥/凭证 |
| 🔴 严重 | MySQL 端口对外开放 | 端口 3306/tcp 状态 open | 防火墙限制访问；强密码 + 启用 TLS |
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |

## 🌐 拓扑

```
http://127.0.0.1:8080
└── 子域    2000 项被 wildcard 过滤 ⚠
```

## 概述

对 127.0.0.1:8080 完成中强度主动侦察。安全头评分 0/10（全部缺失），Server 头泄露 Apache/2.4.25 (Debian)。目录枚举发现 8 个路径，其中 .gitignore/README.md/CHANGELOG.md 可直接访问，.htaccess/.htpasswd/server-status 返回 403。端口扫描发现 3 个开放端口：53(DNS)/3306(MySQL)/8080(HTTP)。MySQL 直接暴露在本地回环，若存在端口转发则有数据泄露风险。

## DNS 信息

```
127.0.0.1 为本地回环地址，DNS/WHOIS 查询无意义（域名不存在，RDAP 不可达）
```

## 子域名枚举

```
子域名枚举检测到 wildcard DNS (*.127.0.0.1 → 198.18.0.0/15)，已过滤 2000 条假阳性，未发现存活子域名
```

## 开放端口

```
53/tcp open domain
3306/tcp open mysql
8080/tcp open http-proxy (目标 Web 服务)
```

## 目录枚举

```
[200] /.gitignore (57 bytes) — 可能泄露项目结构和敏感路径
[200] /CHANGELOG.md (7296 bytes) — 版本变更记录
[200] /README.md (9180 bytes) — 项目文档
[200] /favicon.ico (1406 bytes)
[200] /robots.txt (26 bytes)
[403] /.htaccess (295 bytes) — Apache 配置文件（存在但被保护）
[403] /.htpasswd (295 bytes) — 密码文件（存在但被保护）
[403] /server-status (299 bytes) — Apache 状态页（存在但被保护）
```

## HTTP 安全头分析

```
安全头评分: 0/10

已配置 (0): 无

缺失 (10):
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

⚠ Server 头泄露: Apache/2.4.25 (Debian)
```

## 其他发现

```
目标为 DVWA v1.10（Damn Vulnerable Web Application），已知存在默认凭据 admin/password。MySQL 3306 端口直接暴露，若配置不当可被远程连接。.htaccess/.htpasswd/server-status 虽返回 403，但表明 Apache 配置文件和密码文件存在于服务器上。
```

---
*由 Argus 自动生成*
