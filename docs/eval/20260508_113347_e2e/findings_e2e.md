# Argus 端到端 Eval — Stage 1+2+3 验收

- 时间（UTC）: **2026-05-08 11:38:08 UTC**
- 运行: A1+A2+D1+D2 = 4 run
- 总耗时: **246.7s**

## A 段 — Stage 1（Top-3 信号库扩充）验收

| ID | 标的 | 状态 | 耗时 | turns | tools | Top-3 计数 | 报告 B |
|---|---|---|---|---|---|---|---|
| A1 | DVWA local | ok | 75.6s | 4 | 7 | 3 | 2880 |
| A2 | IBM AltoroJ | ok | 42.3s | 3 | 1 | 0 | 2593 |

### Stage 1 Top-1 验收

| ID | severity | 风险 |
|---|---|---|
| A1 | critical | .git 仓库对外暴露 |
| A2 | ? | (no Top-1) |

**Stage 1 结论**: ✅ PASS — A1 或 A2 至少一个 Top-1 升级到 critical/high

## D 段 — Stage 2 (auth_login) + Stage 3 (vuln_scan) 验收

| ID | 标的 | 状态 | 耗时 | turns | tools | auth_login | 登录✓ | vuln_called | vuln✓ | 报告 |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | DVWA login + sqli | ok | 60.3s | 7 | 6 | ✓ | ✓ | ✓ | ✗ | 1491 |
| D2 | AltoroJ login + xss | ok | 68.5s | 8 | 7 | ✓ | ✗ | ✓ | ✓ | 736 |

**Stage 2 结论**: ✅ PASS — D 段 至少一次 auth_login 登录成功
**Stage 3 结论**: ✅ PASS — D 段 至少一个 vuln_* 报 vulnerable=true

## D 段工具调用链

### D1 — DVWA login + sqli
- 工具调用顺序: `credentials_lookup → auth_login → browser_navigate → browser_get_html → vuln_sqli_timing → generate_report`
- vuln_summary: `vuln_sqli_timing: vulnerable=False`
- final_text 摘录: ---

**一句话总结**：`vuln_sqli_timing` 对 DVWA Low 级别的 SQLi 参数 `id` 检测结果为 **未检测到漏洞**（`vulnerable=false`，0/4 payload 触发），原因是 DVWA 的 SQLi 是 **in-band**（UNION/Boolean 回显型），SLEEP payload 被直接查询吸收不产生延迟侧信道——需要用 `h

### D2 — AltoroJ login + xss
- 工具调用顺序: `credentials_lookup → auth_login → dns_lookup → http_request → http_request → vuln_xss_reflection → generate_report`
- vuln_summary: `vuln_xss_reflection: vulnerable=True`
- final_text 摘录: 已完成对 demo.testfire.net 的授权 XSS 探测。

**执行结果：**
1. ✅ `credentials_lookup` 成功获取凭据占位符
2. ❌ `auth_login` 失败（`net::ERR_EMPTY_RESPONSE`），但直接访问 `login.jsp` 返回 200
3. ✅ `vuln_xss_reflection` **命中** — 发现反射型 XSS

## 总评

- **三阶段全部 PASS**: ✅ 是
- Stage 1: PASS · Stage 2: PASS · Stage 3: PASS

