# 侦察报告 — http://demo.testfire.net (AltoroJ - HCL AppScan 漏洞演示)

> 生成时间: 2026-05-08 15:48:03

## 🎯 执行摘要 Top-1

| 级别 | 风险 | 证据 | 建议 |
|---|---|---|---|
| 🔴 高 | 域名 75 天内到期 | WHOIS expiration: 2026-07-23 | 尽快续费；启用注册商自动续费功能 |

## 🌐 拓扑

```
http://demo.testfire.net (AltoroJ - HCL AppScan 漏洞演示)
└── A     198.18.207.115
```

## 概述

对 `demo.testfire.net` 执行了中强度主动侦察。目标为 **AltoroJ** — HCL Technologies (原 IBM) 开发的故意存在漏洞的银行 Web 应用，用于演示 AppScan 安全产品。运行于 Apache Tomcat (Apache-Coyote/1.1)，解析到保留地址段 198.18.0.0/15。安全配置极差（0/10 安全头），暴露了完整 Swagger REST API 文档和多个功能页面。

## DNS 信息

```
## DNS 查询结果
| 记录类型 | 值 |
|---------|---|
| **A 记录** | `198.18.207.115`（RFC2544 基准测试保留段）|
| **通配符** | `*.demo.testfire.net` 指向 `198.18.0.0/15`（已过滤假阳性） |

> ⚠ 该 IP 属于 IANA 保留地址段，仅在测试/实验网络内可路由。
```

## 子域名枚举

```
## 子域名枚举
- **结果**: 未发现存活子域名
- **原因**: 目标配置了通配符 DNS（*.demo.testfire.net → 198.18.0.0/15），已过滤 2000 条疑似假阳性记录
```

## 开放端口

```
## 端口扫描（目标: demo.testfire.net → 198.18.215.81）
| 扫描端口 | 状态 |
|---------|------|
| 21,22,23,25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017 | **均未发现开放端口** |

> ⚠ 目标解析到 198.18.0.0/15（RFC2544 基准测试段），该段仅在扫描实验室内可路由。HTTP 服务（80端口）可通过特定路由方式访问，但 nmap 端口扫描无法直接检测到该段的开放端口。
```

## 目录枚举

```
## 目录枚举（字典 190 条）
| 状态码 | 路径 | 说明 |
|-------|------|------|
| **200** | `/` | 首页（9405 bytes）|

> 内置字典未发现更多隐藏路径。但通过爬虫发现的**已知路径**丰富：

### 通过爬虫发现的 JSP 页面
| 路径 | 说明 |
|------|------|
| `/index.jsp` | 首页（含多种内容参数） |
| `/login.jsp` | 登录页面（含用户名/密码表单，JS 前端校验） |
| `/search.jsp` | 搜索功能（GET 参数: query） |
| `/feedback.jsp` | 反馈提交页面 |
| `/subscribe.jsp` | 订阅页面 |
| `/survey_questions.jsp` | 调查问卷页面 |
| `/status_check.jsp` | 服务器状态检查（含 JSON 提交表单） |
| `/default.jsp` | 默认页面（参数: content=security.htm） |
| `/cgi.exe` | CGI 程序 → **404**（链接存在但页面不存在） |

### 静态资源
| 路径 | 说明 |
|------|------|
| `/style.css` | 样式表 |
| `/images/` | 图片资源目录 |

### Swagger API 文档
| 路径 | 说明 |
|------|------|
| `/swagger/index.html` | Swagger UI 界面 |
| `/swagger/properties.json` | **完整 API 定义（9448 bytes）** |
| `/swagger/swagger-ui.css` | Swagger UI 样式 |
| `/swagger/swagger-ui-bundle.js` | Swagger JS 包 |
| `/swagger/swagger-ui-standalone-preset.js` | Swagger 预设
```

## HTTP 安全头分析

```
## HTTP 安全头分析
**评分: 0/10** ❌

### 已配置（0）
（无任何安全头）

### 缺失（10）
| 安全头 | 作用 |
|-------|------|
| ❌ HSTS | 强制 HTTPS |
| ❌ CSP | 防 XSS |
| ❌ X-Frame-Options | 防点击劫持 |
| ❌ X-Content-Type-Options | 防 MIME 嗅探 |
| ❌ X-XSS-Protection | 浏览器 XSS 过滤 |
| ❌ Referrer-Policy | Referer 控制 |
| ❌ Permissions-Policy | 浏览器特性控制 |
| ❌ COOP | 跨域窗口隔离 |
| ❌ CORP | 跨域资源策略 |
| ❌ COEP | 跨域嵌入策略 |

### 信息泄露
| 风险 | 详情 |
|------|------|
| ⚠ **Server 头泄露** | `Apache-Coyote/1.1`（暴露 Apache Tomcat 版本）|
| ⚠ **JSESSIONID Cookie** | 每次请求生成新 Session ID（无安全标记）|
| ⚠ **无 HTTPS** | 仅 HTTP 明文传输 |
```

## Cookie 信息

```
## Cookie 信息
| Cookie名 | 属性 |
|---------|------|
| **JSESSIONID** | Path=/; HttpOnly（无 Secure 标记，无 SameSite）|

> 每个新请求都会生成不同的 JSESSIONID，说明服务端无粘性会话保持。
```

## 站点链接

```
## 站点链接（已发现 32 个同域链接）
### 主要页面入口
- `/index.jsp` — 首页
- `/login.jsp` — 登录
- `/feedback.jsp` — 反馈
- `/search.jsp` — 搜索
- `/subscribe.jsp` — 订阅
- `/survey_questions.jsp` — 调查问卷
- `/status_check.jsp` — 服务器状态检查
- `/default.jsp?content=security.htm` — 安全声明
- `/cgi.exe` — 位置查询（404）

### 内容页面（通过 index.jsp?content= 参数加载）
- `personal.htm` / `business.htm` / `inside.htm` — 主要板块
- `personal_deposit.htm`, `personal_checking.htm`, `personal_loans.htm`, `personal_cards.htm`, `personal_investments.htm`, `personal_other.htm`
- `business_deposit.htm`, `business_lending.htm`, `business_cards.htm`, `business_insurance.htm`, `business_retirement.htm`, `business_other.htm`
- `inside_about.htm`, `inside_contact.htm`, `inside_investor.htm`, `inside_press.htm`, `inside_careers.htm`
- `privacy.htm`, `security.htm`, `personal_savings.htm`

### API 文档
- `/swagger/index.html` — Swagger REST API 文档
```

## 表单发现

```
## 表单发现
| 表单 | 方法 | 动作地址 | 字段 |
|------|------|---------|------|
| **搜索** | GET | `/search.jsp` | `query` (text), 提交按钮 |

### 通过分析页面发现的更多输入点（非标准表单）:
- **登录 (login.jsp)**: `uid` (text), `passw` (password) — JS 前端校验
- **状态检查 (status_check.jsp)**: JSON 提交按钮（表单 ID: `frmJsonSubmit`）
- **反馈 (feedback.jsp)**: name, email, subject, message 等字段
```

## JS 分析

```
## JS 分析 & API 端点

### Swagger REST API（完整暴露）
**Base Path**: `/api`

| 端点 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/login` | GET | 检查登录状态 | Bearer Token |
| `/api/login` | POST | 用户登录（返回 Token） | 无 |
| `/api/account` | GET | 获取所有账户列表 | Bearer Token |
| `/api/account/{accountNo}` | GET | 获取指定账户详情 | Bearer Token |
| `/api/transfer` | POST | 转账 | Bearer Token |
| `/api/feedback` | POST | 提交反馈 | 无 |
| `/api/feedback/all` | GET | 查看所有反馈 | Bearer Token |
| `/api/admin` | POST | 添加新用户 | Bearer Token |
| `/api/admin/{username}` | GET | 获取用户信息 | Bearer Token |
| `/api/admin/{username}` | PUT | 修改密码 | Bearer Token |
| `/api/logout` | POST | 注销 | Bearer Token |

### API 数据模型
| 模型 | 字段 |
|------|------|
| **login** | username, password |
| **transaction** | startDate, endDate |
| **transfer** | toAccount, fromAccount, transferAmount |
| **feedback** | name, email, subject, message |
| **newUser** | firstname, lastname, username, password1, password2 |
| **changePassword** | username, password1, password2 |
```

## WHOIS 信息

```
## WHOIS 注册信息
| 字段 | 值 |
|------|-----|
| **域名** | TESTFIRE.NET |
| **注册商** | Amazon Registrar, Inc. |
| **创建时间** | 1999-07-23 |
| **到期时间** | 2026-07-23 |
| **状态** | clientDelete/Transfer/Update Prohibited |
| **DNS** | Akamai 基础设施（asia3/eur2/eur5/usc2/usc3/usw2.akam.net + ns1-206/ns1-99.akam.net）|

> 注：子域 demo.testfire.net 的 WHOIS 已回退到注册域 testfire.net。
```

## 其他发现

```
## 补充信息

### 🔓 已知漏洞背景
- **项目**: AltoroJ（开源 Java 漏洞演示应用）
- **源码**: https://github.com/AppSecDev/AltoroJ/
- **技术栈**: **Apache Tomcat** (Apache-Coyote/1.1) + **Java JSP**
- **目的**: 演示 Web 漏洞检测（HCL AppScan 产品演示）
- **版本**: API v1.0.2
- **特性**: 该应用刻意包含多种安全漏洞（SQL 注入、XSS、认证缺陷等）

### 登录页面特征
- 用户名输入框 ID: `uid`
- 密码输入框 ID: `passw`
- 含 JS 前端校验（验证非空，弹出 alert）
- 无验证码保护
- 无登录失败次数限制提示

### 信息暴露风险
1. ⚠ **Swagger API 文档完全暴露** — 无需认证即可查看全部 API 定义
2. ⚠ **Apache-Coyote/1.1 版本泄露** — 有助于针对性攻击
3. ⚠ **JSESSIONID 无 Secure/SameSite 属性** — 存在会话劫持风险
4. ⚠ **全站 HTTP 明文传输** — 凭据和会话均可被嗅探
5. ⚠ **`/api/feedback/all` 无需认证即可获取所有用户反馈**（根据 Swagger 定义，但实际需验证）

### 安全建议
1. 🔧 启用 HTTPS 并配置 HSTS
2. 🔧 添加 CSP、X-Frame-Options 等安全头
3. 🔧 隐藏 Server 版本头
4. 🔧 对 Swagger 文档添加访问控制
5. 🔧 为 JSESSIONID 添加 Secure、SameSite=Strict 标记
```

---
*由 Argus 自动生成*
