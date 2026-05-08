# 侦察报告 — http://demo.testfire.net

> 生成时间: 2026-05-08 19:38:01

## 概述

对 demo.testfire.net 靶场执行授权 XSS 探测。登录步骤因网络问题失败（ERR_EMPTY_RESPONSE），但直接访问 login.jsp 返回 200。成功检测到反射型 XSS 漏洞（参数 query，探针未编码反射，上下文为 HTML）。目标已通过 credentials.toml 授权。

## 💡 本次命中的避坑教训

> 基于 `~/.argus/memories/LESSONS.md` 中的历史失败记录。

1. [2026-05] net_info on (unknown) → 限流 429（避免重复尝试或换策略）
2. [2026-05] devtools_network_log on (unknown) → 5xx 服务端错误（避免重复尝试或换策略）

---
*由 Argus 自动生成*
