# 侦察报告 — http://127.0.0.1:8080

> 生成时间: 2026-05-08 18:15:20

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 严重 | .git 仓库对外暴露 | `[200] /.git` | **立即** 从 web root 移除 .git/，并轮换该仓库泄漏的所有密钥/凭证 |
| 🔴 严重 | MySQL 端口对外开放 | 端口 3306/tcp 状态 open | 防火墙限制访问；强密码 + 启用 TLS |
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |

## 🌐 拓扑

```
http://127.0.0.1:8080
```

## 概述

对本地目标 127.0.0.1:8080 进行中强度主动侦察。发现 HTTP 安全头评分极低（0/10），服务器信息泄露，存在敏感文件路径，开放 3 个端口（53, 3306, 8080）。DNS 和 WHOIS 查询因目标为本地 IP 而失败。

## DNS 信息

```
DNS 查询失败：127.0.0.1 是 IP 地址，非域名。
```

## 子域名枚举

```
子域名枚举未发现存活子域名（已检测 2000 个）。
```

## 开放端口

```
端口扫描结果:
主机: 127.0.0.1 (activate.navicat.com)
  状态: up
  53/tcp  open  domain
  3306/tcp  open  mysql
  8080/tcp  open  http-proxy
```

## 目录枚举

```
目录枚举 (http://127.0.0.1:8080) — 发现 8/190:
  [200] /.gitignore  (57 bytes)
  [200] /CHANGELOG.md  (7296 bytes)
  [200] /README.md  (9180 bytes)
  [200] /favicon.ico  (1406 bytes)
  [200] /robots.txt  (26 bytes)
  [403] /.htaccess  (295 bytes)
  [403] /.htpasswd  (295 bytes)
  [403] /server-status  (299 bytes)
```

## HTTP 安全头分析

```
目标: http://127.0.0.1:8080 (HTTP 200)

已配置 (0):

缺失 (10):
  ✗ HSTS (Strict-Transport-Security) — 缺失 (强制 HTTPS，防止降级攻击)
  ✗ CSP (Content-Security-Policy) — 缺失 (限制资源加载来源，防止 XSS)
  ✗ X-Frame-Options — 缺失 (防止点击劫持（Clickjacking）)
  ✗ X-Content-Type-Options — 缺失 (防止 MIME 类型嗅探)
  ✗ X-XSS-Protection — 缺失 (浏览器 XSS 过滤（已过时但仍常见）)
  ✗ Referrer-Policy — 缺失 (控制 Referer 头泄露)
  ✗ Permissions-Policy — 缺失 (控制浏览器特性（摄像头、地理位置等）)
  ✗ COOP (Cross-Origin-Opener-Policy) — 缺失 (跨域窗口隔离)
  ✗ CORP (Cross-Origin-Resource-Policy) — 缺失 (跨域资源加载策略)
  ✗ COEP (Cross-Origin-Embedder-Policy) — 缺失 (跨域嵌入策略)

⚠ Server 头泄露: Apache/2.4.25 (Debian)

安全头评分: 0/10
```

## Cookie 信息

```
未收集 Cookie 信息。
```

## 站点链接

```
未收集页面链接信息。
```

## 表单发现

```
未收集表单信息。
```

## JS 分析

```
未进行 JavaScript 分析。
```

## WHOIS 信息

```
WHOIS 查询失败：RDAP 不可达，旧 API 返回错误（127.0.0.1）。
```

## 其他发现

```
目标为本地 IP 地址，DNS 和 WHOIS 查询不适用。服务器运行 Apache/2.4.25 (Debian)，开放 MySQL 端口 3306，可能存在数据库安全风险。发现 .htaccess 和 .htpasswd 文件，可能包含访问控制配置。
```

---
*由 Argus 自动生成*
