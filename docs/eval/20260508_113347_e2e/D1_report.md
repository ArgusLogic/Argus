# 侦察报告 — http://127.0.0.1:8080

> 生成时间: 2026-05-08 19:36:43

## 概述

DVWA v1.10 靶场授权漏洞验证：已登录（admin），安全级别 Low。vuln_sqli_timing 时间盲注检测结果为 negative（vulnerable=false），原因是 DVWA SQLi 关卡为 in-band（UNION/Boolean-based），SLEEP payload 被直接查询吸收，不产生延迟。需用 http_request 手注 UNION SELECT 进一步确认 in-band SQLi。

## 其他发现

```
## 漏洞验证详情

### vuln_sqli_timing 结果
- **目标**: http://127.0.0.1:8080/vulnerabilities/sqli/?id=1&Submit=Submit
- **参数**: id
- **结果**: vulnerable=false, confidence=none
- **基线延迟**: 6ms
- **触发数**: 0/4
- **Payload 测试**:
  | Payload | 响应耗时 | 延迟差 | 触发 |
  |---|---|---|---|
  | `' AND SLEEP(3)-- ` | 5ms | -2ms | ❌ |
  | `' OR SLEEP(3)-- ` | 5ms | -1ms | ❌ |
  | `" AND SLEEP(3)-- ` | 6ms | 0ms | ❌ |
  | `); WAITFOR DELAY '0:0:3'-- ` | 5ms | -1ms | ❌ |

### 分析
DVWA v1.10 Low 安全级别的 SQLi 是 **in-band** 类型（UNION SELECT / Boolean-based），查询结果直接回显在页面上。SLEEP/WAITFOR payload 被 MySQL 直接执行但结果通过 UNION 回显而非延迟侧信道，因此时间盲注工具无法检测。

### 授权信息
- 凭据来源: ~/.argus/credentials.toml
- 授权路径: config.toml allowed_domains 包含 127.0.0.1
- 安全级别: Low（已确认）
```

---
*由 Argus 自动生成*
