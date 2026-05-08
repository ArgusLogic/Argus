# 侦察报告 — http://127.0.0.1:8080 (DVWA)

> 生成时间: 2026-05-08 15:01:00

## 🎯 执行摘要 Top-3

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | HSTS 缺失 | `Strict-Transport-Security` 未配置 | 强制 HTTPS，防止降级攻击；服务端添加 `Strict-Transport-Security: max-age=31536000` |
| 🟠 中 | CSP 缺失 | `Content-Security-Policy` 未配置 | 至少配置 `default-src 'self'`，逐步收紧到允许列表 |
| 🟠 中 | X-Frame-Options 缺失 | `X-Frame-Options` 未配置 | 防止点击劫持；设置 `X-Frame-Options: SAMEORIGIN` 或 `DENY` |

## 概述

对本地目标 http://127.0.0.1:8080 进行中强度主动侦察。目标运行的是 **Damn Vulnerable Web Application (DVWA) v1.10 *Development*** — 一个故意留有漏洞的 PHP/MySQL 安全训练应用。服务运行在 Apache/2.4.25 (Debian) + PHP 7.0.30 上。发现开放端口 3 个（53/DNS, 3306/MySQL, 8080/HTTP），目录爆破发现 8 个路径，HTTP 安全头评分 0/10。从 setup.php 页面直接获取了完整的数据库配置信息（MySQL 用户: app, 数据库: dvwa），存在严重的信息泄露风险。

## DNS 信息

```
目标为本地回环地址 (127.0.0.1)，DNS 查询无结果。
```

## 子域名枚举

```
本地 IP 地址，子域名枚举无意义（0 个存活子域名）。
```

## 开放端口

```
## 端口扫描结果 (目标: 127.0.0.1)

| 端口 | 服务 | 状态 |
|------|------|------|
| 53/tcp | Domain (DNS) | ✅ 开放 |
| 3306/tcp | MySQL | ✅ 开放 |
| 8080/tcp | HTTP-Proxy (DVWA) | ✅ 开放 |

**说明**: MySQL 3306 端口暴露在本地网络中，结合已知数据库凭据（app/******），存在被本地横向访问的风险。
```

## 目录枚举

```
## 目录爆破结果 (8/190)

| 路径 | 状态码 | 说明 |
|------|--------|------|
| /.gitignore | 200 | 57 bytes — 泄露 config/config.inc.php 路径 |
| /CHANGELOG.md | 200 | 7296 bytes — 版本变更历史 |
| /README.md | 200 | 9180 bytes — 完整文档，含默认凭据 |
| /favicon.ico | 200 | 1406 bytes |
| /robots.txt | 200 | 26 bytes — Disallow: / |
| /.htaccess | 403 | 295 bytes — 存在但禁止访问 |
| /.htpasswd | 403 | 295 bytes — 存在但禁止访问 |
| /server-status | 403 | 299 bytes — Apache 状态页面受限 |

### 额外路径
- /setup.php (200) — **严重信息泄露**：泄露完整数据库配置
- /login.php (200) — 登录入口
- /config/config.inc.php (200) — 空响应，但路径有效
```

## HTTP 安全头分析

```
## HTTP 安全头分析 — 评分: 0/10 ❌

### 已配置 (0):
无任何安全头配置

### 缺失 (10):
- ❌ HSTS (Strict-Transport-Security) — 缺失
- ❌ CSP (Content-Security-Policy) — 缺失
- ❌ X-Frame-Options — 缺失
- ❌ X-Content-Type-Options — 缺失
- ❌ X-XSS-Protection — 缺失
- ❌ Referrer-Policy — 缺失
- ❌ Permissions-Policy — 缺失
- ❌ COOP (Cross-Origin-Opener-Policy) — 缺失
- ❌ CORP (Cross-Origin-Resource-Policy) — 缺失
- ❌ COEP (Cross-Origin-Embedder-Policy) — 缺失

### 信息泄露
- ⚠ Server 头: Apache/2.4.25 (Debian)
```

## Cookie 信息

```
## Cookie 信息

- **PHPSESSID**: 会话标识（HttpOnly 未设置）
- **security**: 默认值 `low` — DVWA 安全级别控制 Cookie，明文传输

Cookie 未设置 HttpOnly 和 Secure 标志，存在会话劫持风险。
```

## 站点链接

```
页面主要链接（同域）:
- /login.php — 登录页
- /setup.php — 数据库设置页（信息泄露严重）
- /instructions.php — 使用说明
- /about.php — 关于页面
- /dvwa/css/login.css — 登录页样式
- /dvwa/css/main.css — 主样式
- /dvwa/js/dvwaPage.js — JS 脚本
- /dvwa/js/add_event_listeners.js — JS 脚本
```

## 表单发现

```
## 表单发现

### 1. login.php (登录表单)
- 方法: POST
- 目标: login.php
- 字段:
  - `username` (text) — 用户名字段
  - `password` (password) — 密码字段
  - `user_token` (hidden) — CSRF 令牌
  - `Login` (submit) — 登录按钮

### 2. setup.php (数据库重置表单)
- 方法: POST
- 字段:
  - `create_db` (submit) — "Create / Reset Database" 按钮
  - `user_token` (hidden) — CSRF 令牌
```

## JS 分析

```
分析了两份 JS 文件：
- `/dvwa/js/dvwaPage.js` — 未发现 API 端点或敏感信息
- `/dvwa/js/add_event_listeners.js` — 未发现 API 端点或敏感信息
```

## WHOIS 信息

```
本地回环地址，WHOIS 查询不适用。
```

## 其他发现

```
## 系统信息泄露 (严重)

从 `/setup.php` 页面直接获取的完整配置信息：

### 服务器环境
| 项目 | 值 |
|------|------|
| 操作系统 | *nix (Linux/Debian) |
| Web 服务器 | Apache/2.4.25 (Debian) |
| PHP 版本 | 7.0.30-0+deb9u1 |
| 后端数据库 | MySQL |
| Web 根目录 | /var/www/html/ |

### 数据库配置 (泄露)
| 项目 | 值 |
|------|------|
| MySQL 用户名 | app |
| MySQL 密码 | (掩码显示, 实际存在) |
| MySQL 数据库名 | dvwa |
| MySQL 主机 | 127.0.0.1 |

### PHP 安全配置
| 配置项 | 状态 |
|--------|------|
| display_errors | Disabled ✅ |
| safe_mode | Disabled ✅ |
| allow_url_fopen | Enabled ⚠ |
| allow_url_include | **Enabled ⚠⚠** |
| magic_quotes_gpc | Disabled ⚠ |
| gd module | Installed ✅ |
| mysql module | Installed ✅ |
| pdo_mysql | Installed ✅ |

### 可写目录（文件上传风险）
- ✅ `/var/www/html/hackable/uploads/` — 可写
- ✅ `/var/www/html/config/` — 可写
- ✅ `/var/www/html/external/phpids/0.6/lib/IDS/tmp/phpids_log.txt` — 可写

### 其他
- reCAPTCHA Key: **Missing**（无验证码保护）
- `.gitignore` 泄露 `config/config.inc.php` 和 Dockerfile 路径

### 默认凭据 (来自 README.md)
- 用户名: **admin**
- 密码: **password**
```

---
*由 Argus 自动生成*
