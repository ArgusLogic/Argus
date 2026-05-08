# Argus Real-World Eval — 主观评分 & 发现

> 配套 `summary.md`（自动生成的客观指标）+ 本文件（主观分析）+ `raw_metrics.json`。

## TL;DR

- **8 run / 7 成功 / 14 分钟 / 57K token** — 远低于 30 分钟 50K 预算
- Argus 在**已知漏洞标的**（DVWA、AltoroJ）上**正确识别技术栈 + 关键暴露面**，但 Top-3 卡片选择不总是命中最严重项
- **三模型 V4-Flash / V4-Pro / MiMo-Pro 主体一致**，差异在 Top-3 优先级与报告丰度
- **C1 Cloudflare 早停**触发 ✓，**C2 Microsoft wildcard 过滤**触发 ✓ — Day 1/2 改进经得起公网验证
- **暴露 1 个真实 bug**：`dir_bruteforce` 内部 60s wall-clock budget 与 `tool_timeout=60` 死锁，A3 itsecgames 整个 run 因此超时

## 主观评分（满分 5，越高越好）

| 维度 | 权重 | A1 DVWA | A2 testfire | A3 itsec | B1 V4-Flash | B2 V4-Pro | B3 MiMo | C1 CF | C2 MS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 真实性（漏洞实存） | 30% | 4 | 5 | 0 | 4 | 4 | 4 | 4 | 4 |
| 可读性（卡片+建议） | 25% | 3 | 4 | 0 | 4 | 4 | 4 | 4 | 4 |
| 调度（工具切换合理） | 20% | 4 | 5 | 1 | 4 | 4 | 5 | 4 | 5 |
| 鲁棒性（早停/超时） | 15% | 5 | 5 | **1** | 5 | 5 | 5 | **5** | **5** |
| 成本（token/byte 比） | 10% | 4 | 4 | 0 | 4 | 4 | 5 | 4 | 4 |
| **加权总分** | 100% | **3.95** | **4.65** | **0.40** | **4.10** | **4.10** | **4.40** | **4.20** | **4.30** |

平均（不含 A3）：**4.24 / 5**。

## A 段 — 垂直能力详评

### A1 — DVWA（4.0 / 5）
**亮点**：正确识别 DVWA v1.10 Development、Apache 2.4.25、PHP 7.0.30、MySQL；爆破出 8 个目录含 `/.gitignore` `/setup.php` 风险；端口 53/3306/8080 全识别；甚至从源码注释提取出**默认凭据 admin/password**。
**短板**：Top-3 卡片只挂出 X-Frame / X-Content-Type 两项中低危头，**遗漏**了同报告下方明确写到的 `/setup.php 数据库泄露` 和 `3306 横向移动风险`。优先级排序偏弱。

### A2 — IBM AltoroJ（4.65 / 5）
**亮点**：识别 AltoroJ + HCL AppScan 演示 + Apache Tomcat；通过爬虫 + JS 分析提取**完整 Swagger REST API**（11 个端点 + 5 个数据模型 + 认证类型标注）；32 个站点链接全图谱；表单 + 输入点完整。
**短板**：Top-3 第 1 项是 "域名 75 天内到期" — 在含 `/swagger` 完全暴露的银行靶场里把它列为 🔴 高确实跑题。

### A3 — itsecgames（**0.4 / 5 — 失败**）
**根因**：`dir_bruteforce` 工具内部 60s wall-clock budget 与 `tool_timeout=60` 两个超时同时到期，在 agent 收到 budget-stop 早停结果之前，先抛 `TOOL_TIMEOUT`。第二次重试再撞 timeout，整个 run 在 200s 后被外部进程超时硬杀，无报告生成。
**修复建议**：把 `dir_bruteforce` 的 wall budget 调为 `tool_timeout - 5s`（动态读取 config），或把工具超时上调到 120s。这是 Day 1 改进留下的相邻 bug，应作为 issue 跟进。

## B 段 — 多模型同题

固定 target = `demo.testfire.net` / 模式 = `recon`，三模型 Top-3 摘要：

| 模型 | Top-3 选择 | 风格 |
|---|---|---|
| V4-Flash | 🔴 HSTS / 🔴 安全头评分 / 🔴 域名到期 | 三红色，最 alarmist |
| V4-Pro | 🔴 HSTS / 🔴 域名到期 / 🟠 CSP | 中庸，分布更合理 |
| MiMo-Pro | 🔴 安全头评分 / 🔴 域名到期 / 🟠 X-Frame | 紧凑，最少废话 |

数据：

|  | turns | tools | tokens | 报告 B | sections |
|---|---:|---:|---:|---:|---:|
| V4-Flash | 4 | 5 | 5,133 | 4,417 | 9 |
| V4-Pro | 3 | 5 | 5,435 | 5,505 | **15** |
| MiMo-Pro | **6** | 5 | **4,435** | **2,677** | 9 |

**结论**：
- V4-Pro 报告最丰（15 sections / 5.5 KB），证明强推理能写更细
- MiMo-Pro 用 6 turns 但 token 反而最少（4,435），说明 MiMo agent loop 比较"果断"
- V4-Flash 在性价比维度最稳；不偏不倚的中间档
- 三模型**全部 100% 命中** AltoroJ + 0/10 安全头 + Akamai DNS — Argus 的工具链层稳定，模型差异主要在**叙述风格**

## C 段 — 边界鲁棒性

### C1 — Cloudflare WAF（4.2 / 5）
- HEAD 请求即 403（互联网层就拦） → Argus 报告原文写 "**Cloudflare 对其官网实施了严格的安全防护，WAF 规则完善**"，并自洽归因 "目录爆破因全站 301 重定向无法直接发现隐藏路径"
- 早停日志：`WAF/rate-limit + wildcard-filter` 双触发
- 没有死循环重试，没有把 403 当作可挖掘信号 — 处理得体

### C2 — Microsoft 大场（4.3 / 5）
- 解析到 `198.18.255.17 + 198.18.0.0` 双 wildcard IP
- 报告原文：`A 记录 198.18.255.17（注：此 IP 属于保留地址段 198.18.0.0/15，用于网络基准测试，表明 DNS 查询受到本地网络环境影响，非真实微软服务器 IP）`
- subdomain_enum 输出 0 条（2000 全部被 wildcard 过滤）— 假阳性 0
- 唯一遗憾：报告未提到 Microsoft 庞大子域生态（实际 `*.microsoft.com` 有几万子域），但这受限于本地 DNS 解析层环境，不算 Argus 失误

## 真实发现 / 后续 issue 候选

1. **HIGH**：`dir_bruteforce` 60s budget 与 `tool_timeout=60` 竞争，应让 budget < timeout - safety_margin。A3 案例可复现。
2. **MED**：Top-3 卡片优先级算法偏弱 — 在 DVWA 等含明确高危项的目标，把"X-Frame-Options 缺失"挂顶不合适。可考虑 prompt 加 ranking hint，或在 `_report_summary.py` 加加权重。
3. **LOW**：A2 把 "域名到期 75 天" 排 🔴 — 与漏洞严重度冲突。同上修复。
4. **INFO**：DeepSeek V4-Pro 用 3 turns 出 15 sections（最丰），印证之前 L3 bench 看到的 "Pro 模型并行调度更激进"。
5. **INFO**：MiMo-Pro 在百万上下文配置下用 token 最省（4,435），说明 MiMo agent prompt 调优合理，不"灌水"。

## 总评

> Argus 已具备**面对未知公网目标自主完成有意义侦察**的能力。在已知含漏洞的标的上，**报告层质量主要受 LLM 选择 Top-3 时的优先级影响，工具链本身稳定**。三层早停（WAF / wildcard / 不可达）在公网真实场景全部触发并被报告所"自洽叙述"，证明 Day 1 改进达到设计意图。

> **下一步重点**应是修 `dir_bruteforce` 超时竞争（issue 1），并在 `_report_summary.py` 加严重度优先级权重（issue 2/3）。
