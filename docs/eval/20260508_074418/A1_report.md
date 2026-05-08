# 侦察报告 — http://127.0.0.1:8080 (DVWA - Damn Vulnerable Web Application)

> 生成时间: 2026-05-08 15:45:47

## 🎯 执行摘要 Top-2

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🟠 中 | X-Frame-Options 缺失 | `X-Frame-Options` 未配置 | 防止点击劫持；设置 `X-Frame-Options: SAMEORIGIN` 或 `DENY` |
| 🟡 低 | X-Content-Type-Options 缺失 | `X-Content-Type-Options` 未配置 | 防止 MIME sniff 攻击；设置 `X-Content-Type-Options: nosniff` |

## 概述

对本地回环地址 127.0.0.1:8080 执行了中强度主动侦察。确认目标为 **Damn Vulnerable Web Application (DVWA) v1.10 *Development***，一个故意设计存在漏洞的 PHP/MySQL 安全教学靶机。发现 3 个开放端口（53/DNS、3306/MySQL、8080/HTTP），8 个可访问路径（含敏感文件 .gitignore 暴露配置路径），HTTP 安全头评分 0/10，并获取到默认凭据 admin/password。

## DNS 信息

```
## DNS 查询
- **域名**: 127.0.0.1
- **A 记录**: 198.18.199.142（非标准回环地址解析，可能受网络环境或 DNS 解析器影响）
- **说明**: 127.0.0.1 为本地回环地址，DNS 查询结果不具备实际意义。
```

## 子域名枚举

```
## 子域名枚举
- **目标**: 127.0.0.1
- **结果**: 未发现存活子域名（检测 2000 个候选，受 wildcard DNS 影响已过滤假阳性）
- **说明**: 本地回环地址枚举子域名无实际意义。
```

## 开放端口

```
## 端口扫描结果（127.0.0.1）

| 端口 | 状态 | 服务 | 说明 |
|---|---|---|---|
| **53/tcp** | ✅ OPEN | domain (DNS) | DNS 服务 |
| **3306/tcp** | ✅ OPEN | mysql | MySQL 数据库（DVWA 后端） |
| **8080/tcp** | ✅ OPEN | http-proxy | DVWA Web 服务（Apache/2.4.25 Debian） |

**扫描范围**: 21,22,23,25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017
**存活状态**: up
```

## 目录枚举

```
## 目录爆破（发现 8/190）

| 路径 | 状态 | 大小 | 说明 |
|---|---|---|---|
| `/.gitignore` | ✅ 200 | 57 B | 暴露 `config/config.inc.php` 和 `Dockerfile`！敏感信息泄漏 |
| `/CHANGELOG.md` | ✅ 200 | 7.3 KB | 版本变更日志 |
| `/README.md` | ✅ 200 | 9.2 KB | 项目说明（含默认凭据） |
| `/favicon.ico` | ✅ 200 | 1.4 KB | 网站图标 |
| `/robots.txt` | ✅ 200 | 26 B | `Disallow: /`（屏蔽所有爬虫） |
| `/.htaccess` | 🔒 403 | 295 B | 存在但不可读（Apache 配置） |
| `/.htpasswd` | 🔒 403 | 295 B | 存在但不可读（认证文件） |
| `/server-status` | 🔒 403 | 299 B | 存在但不可读（Apache 状态页） |

### 敏感发现
- `.gitignore` 内容暴露了配置路径：`config/config.inc.php` 和 `Dockerfile`
```

## HTTP 安全头分析

```
## HTTP 安全头分析（评分：0/10 ❌）

### 已配置（0 项）
无任何安全头配置。

### 缺失（10 项）
| 安全头 | 风险说明 |
|---|---|
| ✗ HSTS | 缺少 HTTPS 强制策略，易遭降级攻击 |
| ✗ CSP | 无内容安全策略，易遭 XSS 攻击 |
| ✗ X-Frame-Options | 可被嵌入 iframe，存在点击劫持风险 |
| ✗ X-Content-Type-Options | 可能发生 MIME 类型嗅探 |
| ✗ X-XSS-Protection | 缺少浏览器 XSS 过滤 |
| ✗ Referrer-Policy | 无 Referer 控制策略 |
| ✗ Permissions-Policy | 所有浏览器特性可被滥用 |
| ✗ COOP | 跨域窗口隔离未启用 |
| ✗ CORP | 跨域资源加载无限制 |
| ✗ COEP | 跨域嵌入无策略 |

### Server 信息泄露 ⚠️
- **Server**: Apache/2.4.25 (Debian)
- 版本信息暴露，可能被用于针对性攻击搜索。
```

## Cookie 信息

```
## Cookie 信息

| Cookie名 | 值 | 域 | 路径 | 安全标志 |
|---|---|---|---|---|
| PHPSESSID | 1oj2ja8653eskum00pqvp58ju4 | 127.0.0.1 | / | SameSite=Lax |
| security | low | 127.0.0.1 | / | SameSite=Lax |

- **security=low**: DVWA 安全级别已设为 low（最低级，漏洞可被直接利用）
```

## 站点链接

```
## 页面链接
登录页面未发现同域链接（DVWA 登录前无导航链接）。
```

## 表单发现

```
## 表单分析

### 登录表单（/login.php）
| 字段 | 类型 | 说明 |
|---|---|---|
| username | text | 用户名输入 |
| password | password | 密码输入 |
| user_token | hidden | CSRF 防护 Token |
| Login | submit | 提交按钮 |

**方法**: POST → `http://127.0.0.1:8080/login.php`

### 默认凭据（从 README.md 获取）
| 用户名 | 密码 |
|---|---|
| **admin** | **password** |
```

## JS 分析

```
## JS 分析
登录页面较为简洁，未发现大量 JavaScript 文件加载。后续登录后可进一步分析各漏洞模块的 JS 端点。
```

## WHOIS 信息

```
## WHOIS 查询
- **结果**: 查询失败（RDAP 不可达，旧 API 返回 error）
- **原因**: 127.0.0.1 为本地保留地址，不存在 WHOIS 注册信息。
```

## 其他发现

```
## 补充信息

### 关于 DVWA v1.10 Development
- **类型**: 漏洞教学靶机（PHP/MySQL）
- **后端**: Apache/2.4.25 (Debian)
- **默认凭据**: `admin` / `password`
- **安全级别**: 当前为 `low`
- **已知脆弱性**: SQL 注入、XSS、文件包含、命令注入、CSRF、文件上传等

### 攻击面总结
| 攻击面 | 风险等级 | 说明 |
|---|---|---|
| 📂 信息泄露 | 🔴 高 | .gitignore 暴露配置路径，README 暴露默认凭据 |
| 🔐 弱认证 | 🔴 高 | 默认凭据 admin/password 可被暴力破解 |
| 🛡️ 无安全头 | 🟡 中 | 全部 10 项安全头缺失 |
| 📡 开放数据库 | 🔴 高 | MySQL 3306 端口对外开放 |
| 📄 版本暴露 | 🟡 中 | Apache 版本、PHP 版本等信息可被获取 |

### 建议后续步骤
1. 使用默认凭据 `admin:password` 登录 DVWA
2. 测试各漏洞模块（SQLi、XSS、文件包含等）
3. 尝试提权至更高安全级别后绕过
4. 爆破 config/config.inc.php 获取数据库连接凭据
```

---
*由 Argus 自动生成*
