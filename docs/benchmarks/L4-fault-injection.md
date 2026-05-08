# L4 · 故障注入 / 韧性验证

2026-05-08 · Windows 11 · 所有场景脚本化、可在 CI 反复跑

## 覆盖矩阵

| 场景 | 测试文件 | 条数 | 状态 |
|---|---|---|---|
| **L4.a** ESC 中断流式 LLM 响应 | `tests/test_interrupt.py` | 现有 | ✅ 已验证 |
| **L4.b** 浏览器崩溃 → 自恢复 | `tests/test_browser_recovery.py` | 现有 | ✅ 已验证 |
| **L4.c** per-target 限流跨工具 | `tests/test_l4_fault_injection.py` | **新 4 条** | ✅ 绿 |
| **L4.d** 审批拒绝 / skip session | `tests/test_approval_ui.py` + `test_engine_acl.py` | 现有 | ✅ 已验证 |
| **L4.e** wildcard + 限流复合 | `tests/test_l4_fault_injection.py` | 新增 | ✅ 绿 |
| **L4.f** tool 抛异常时 semaphore 泄漏 | `tests/test_l4_fault_injection.py` | 新增 | ✅ 绿 |

## L4.c 关键验证点

**`test_target_slot_shared_across_subdomain_enum_calls`**：
在 2 个并发 `subdomain_enum` 调用同一 target 的场景下，观察 `_resolve_ips` 同一瞬间的在途协程数，断言始终 ≤ `per_target_concurrency`。

**`test_target_slot_independent_per_target`**：
不同 target 用独立 semaphore，互不占用 —— 防止"对 A 做子域枚举把对 B 的扫描也阻塞"。

**`test_target_slot_cleanup_on_exception`**：
工具内部抛 `RuntimeError` 时，槽位必须释放；连续 4 次异常后仍能正常拿槽。

## L4.e wildcard + 限流复合

验证同一次运行里三层机制叠加工作：
  1. wildcard 探测先跑（3 次 probe）
  2. 字典条目解析受 per-target 信号量限制（`_load_limit=3`）
  3. 所有命中 wildcard CIDR 的条目被干净过滤

结果：10 条全过滤，输出 `已过滤 10 条 / 未发现` 无残留。

## 之前 L2 实战已经实际触发过的韧性路径

这些在两次真实跑里被 agent 自主触发，已在 `docs/benchmarks/recon-2026-05-08.md` 记录：

  - `whois_lookup` 两 provider 都失败 → 继续流程
  - `dir_bruteforce` 超时 → 自主换到 `http_request` 探 13 个常见路径
  - `port_scan` 对 198.18.x.x 返空 → LLM 自主推理原因并说明

## 未做 / 需要真实环境手测的

  - **真·ESC 中断**（需交互 TTY，脚本化困难）
  - **浏览器主进程 `taskkill` 中途杀死** → 自恢复重启（需 Playwright 真实进程，CI 代价高）
  - **网络断开中途** → LESSONS 写入（需 firewall 控制）

这些在开发机手测通过，纳入 L5 长期 dogfood 复检。
