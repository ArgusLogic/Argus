# L3 · 多模型横向对比（首轮）

2026-05-08 · 目标 `example.com` · 模式 `recon` · Windows 11 · 已修 issue #20 三个 bug

## 结果

| 指标 | V4-Flash | **V4-Pro** | MiMo V2.5-Pro | **MiMo V2.5** | V2.5-Flash |
|---|---|---|---|---|---|
| 耗时 | 52.6 s | 81.4 s | 72.3 s | **39.3 s** ⚡ | — |
| LLM 轮数 | 5 | **3** ⭐ | 6 | 6 | — |
| Tool 调用成功率 | 4/4 | 4/4 | 4/4 | 4/4 | — |
| token 总量 | ~33.75 K | **~4.61 K** 🏆 | ~33.96 K | ~32.97 K | — |
| prompt cache hit | 0 | 0 | 192/256 | — | — |
| 报告字数 | 3422 | 3806 | 3488 | — | — |
| 端点 | api.deepseek.com | 同左 | token-plan-sgp.xiaomimimo.com/v1 | 同左 | 同左 |
| 成本 (单次) | ~¥0.07 | **~¥0.03** | **¥0（Token Plan）** | **¥0** | — |
| wildcard 过滤触发 | ✅ | ✅ | ✅ | ✅ | — |
| Token Plan 可用 | N/A | N/A | ✅ | ✅ | ❌ |

### 关键观察

1. **V4-Pro 的 token 效率最强**（4.61K vs 33K+）：能**并行调用**多个工具 (dns+whois+headers+subdomain) 一轮拿到所有数据，而其他模型串行调；这是 tool-calling scheduler 差异，不是模型能力差距。
2. **MiMo V2.5 速度最快**（39.3s），因为非推理模型、流式响应短。
3. **V4-Pro 报告最长**（3806 字），但因 wildcard 过滤干净，只陈述"wildcard 导致无有效枚举"一句话，而非 Flash 那种 3000 字的子域列表灌水。
4. **V4-Pro 成本反而最低**：虽单价贵 3x，但 tokens 少 7x，单次任务成本 ¥0.03 < V4-Flash ¥0.07。**tool-parallel 是降本的关键**。

## 观察

1. **MiMo V2.5-Pro 能跑通完整侦察链**，第一次实战即稳定完成 recon。
2. **Prompt cache 首轮就命中 75%**（192/256 tokens）—— 官方 prompt cache 基础设施在线。
3. **轮数比 DeepSeek 多 1 轮**：MiMo 更保守，先确认 DNS 再判断是否继续；DeepSeek 一轮打包请求。
4. **tool calling 兼容性**：litellm 内置 `xiaomi_mimo` provider 当前路由不带 tools/tool_choice 支持，Argus 侧透明改走 `openai/`-compat 路由后一切正常（Token Plan 端点本就是 OpenAI 协议）。

## 做了什么

- 新增 `[api_bases]` config 段，支持 per-provider 自定义 base URL
- `LLMClient._resolve_litellm_args` 对 `xiaomi_mimo` + 自定义 base 自动转写为 `openai/<model>` + explicit api_key，绕过 litellm 内置 provider 的 tool 参数限制
- 新增 CLI `--model` flag 覆盖 config 的 `default_model`，方便脚本化跑 bench

## 还没做的

- L3 矩阵其余 4 行（Flash/Pro 对比 V2.5-Pro/Flash）—— 需先验证 v2.5-flash / v2.5 在 Token Plan 端点是否已上线
- Claude / GPT 纳入 —— 需要另外的 key
- 推理链可视化 —— 当前只看耗时和轮数，没抓 reasoning_tokens 对比
