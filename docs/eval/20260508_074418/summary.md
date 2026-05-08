# Argus Real-World Capability Eval

- 运行时间（UTC）: **2026-05-08 07:58:22 UTC**
- 总 run 数: **8**
- 成功率: **7/8**
- 总耗时: **843.9s**
- 总 token: **57,103**
- 总报告大小: **38,495 B**

## A 段 — 垂直能力（scan 模式）

| ID | 标的 | 耗时 | turns | tools | token | 报告(B) | Top-3 | 章节 | 严重词 | 端口 | 早停 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | DVWA local | 106.2 | 8 | 18 | 8215 | 6088 | 2 | 24 | 4 | 0 | unreachable,wildcard-filter | ok |
| A2 | IBM Altoro | 130.8 | 8 | 23 | 16832 | 9163 | 1 | 25 | 1 | 0 | wildcard-filter | ok |
| A3 | itsecgames | 200.9 | 2 | 7 | 4014 | 0 | 0 | 0 | 0 | 0 | wildcard-filter | timeout |

## B 段 — 多模型同题（recon · demo.testfire.net）

| ID | 模型 | 耗时 | turns | tools | token | 报告(B) | Top-3 | 章节 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| B1 | DeepSeek V4 Flash | 71.8 | 4 | 5 | 5133 | 4417 | 3 | 9 | ok |
| B2 | DeepSeek V4 Pro | 97.5 | 3 | 5 | 5435 | 5505 | 3 | 15 | ok |
| B3 | MiMo V2.5 Pro | 66.4 | 6 | 5 | 4435 | 2677 | 3 | 9 | ok |

## C 段 — 边界鲁棒性

| ID | 场景 | 目标 | 耗时 | turns | tools | token | 早停 | 子域 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| C1 | Cloudflare WAF | https://cloudflare.com | 92.4 | 5 | 8 | 7330 | WAF/rate-limit,wildcard-filter | 0 | ok |
| C2 | Microsoft 大场 | https://microsoft.com | 77.9 | 6 | 13 | 5709 | wildcard-filter | 0 | ok |

## 报告链接

- **A1** DVWA local: [A1_report.md](./A1_report.md)  (6088 B)
- **A2** IBM Altoro: [A2_report.md](./A2_report.md)  (9163 B)
- **A3** itsecgames: _无报告_（timeout）
- **B1** DeepSeek V4 Flash: [B1_report.md](./B1_report.md)  (4417 B)
- **B2** DeepSeek V4 Pro: [B2_report.md](./B2_report.md)  (5505 B)
- **B3** MiMo V2.5 Pro: [B3_report.md](./B3_report.md)  (2677 B)
- **C1** Cloudflare WAF: [C1_report.md](./C1_report.md)  (5526 B)
- **C2** Microsoft 大场: [C2_report.md](./C2_report.md)  (5119 B)

## 客观信号自动抽取

### B 段模型对比要点

- 最快：**MiMo V2.5 Pro** (66.4s)
- 最省 token：**MiMo V2.5 Pro** (4435 tok)
- 报告最丰富：**DeepSeek V4 Pro** (5505 B)
- 工具调用最多：**DeepSeek V4 Flash** (5 次)

### C 段早停触发情况

- **C1** Cloudflare WAF: WAF/rate-limit,wildcard-filter
- **C2** Microsoft 大场: wildcard-filter

## 主观评分（手工填补）

> 此节预留给运行者结合各报告内容评分。

| 维度 | 权重 | A1 | A2 | A3 | B1 | B2 | B3 | C1 | C2 |
|---|---:|---|---|---|---|---|---|---|---|
| 真实性（漏洞实存） | 30% | | | | | | | | |
| 可读性（卡片+建议） | 25% | | | | | | | | |
| 调度（工具切换合理） | 20% | | | | | | | | |
| 鲁棒性（早停/超时） | 15% | | | | | | | | |
| 成本（token/byte） | 10% | | | | | | | | |
| **总分** | 100% | | | | | | | | |

