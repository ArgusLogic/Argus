# 侦察报告 — http://demo.testfire.net

> 生成时间: 2026-05-08 18:21:56

## 概述

对 Altoro Mutual (demo.testfire.net) 靶场执行了授权 XSS 反射探测。使用凭据 jsmith/demo1234 成功登录后，对 search.jsp 的 query 参数进行了 XSS 注入测试。结果确认存在反射型 XSS 漏洞：注入的 &lt;script&gt;alert('xss')&lt;/script&gt; 和 &lt;img src=x onerror=alert(1)&gt; 均被原样回显到页面 HTML 中，未经过任何编码或过滤。

## 其他发现

```
## XSS 反射探测详情

### 测试环境
- **目标**: http://demo.testfire.net (AltoroJ 银行靶场)
- **登录凭据**: jsmith / demo1234 (来自 credentials.toml)
- **登录状态**: ✅ 成功登录，页面显示 "Hello John Smith"

### 测试参数
| 参数 | 位置 | URL |
|------|------|-----|
| query | GET | http://demo.testfire.net/search.jsp?query= |

### Payload #1: Script 标签注入
- **Payload**: `<script>alert('xss')</script>`
- **结果**: ✅ **命中** — 原样回显到页面 HTML 中
- **回显位置**:
```html
<p>No results were found for the query:<br><br>
<script>alert('xss')</script>
</p>
```
- **编码情况**: ❌ 无任何 HTML 编码或过滤

### Payload #2: 事件处理器注入
- **Payload**: `"><img src=x onerror=alert(1)>`
- **结果**: ✅ **命中** — img 标签被注入到 DOM
- **回显位置**:
```html
"&gt;<img src="x" onerror="alert(1)">
```
- **编码情况**: `"` 和 `>` 部分编码，但 `<img>` 标签本身未编码

### 漏洞评估
- **漏洞类型**: Reflected XSS (反射型跨站脚本)
- **严重程度**: 🔴 高危
- **CVSS 评分参考**: 6.1 (Medium-High)
- **攻击向量**: 网络远程，无需认证即可触发（但登录后可利用更多功能）
- **影响**: 攻击者可窃取会话 Cookie、执行任意 JavaScript、钓鱼攻击、页面篡改

### 修复建议
1. 对所有用户输入进行 HTML 实体编码（`&lt;` `&gt;` `&amp;` `&quot;`）
2. 实施 Content-Security-Policy (CSP) 头
3. 使用 HttpOnly 标记敏感 Cookie 防止 JS 读取
4. 对输出上下文采用适当的编码策略
```

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] browser_navigate on demo.testfire.net → 连接错误（避免重复尝试或换策略）
2. [2026-05] http_request on demo.testfire.net → 403 Forbidden（避免重复尝试或换策略）
3. [2026-05] net_info on (unknown) → 限流 429（避免重复尝试或换策略）

---
*由 Argus 自动生成*
