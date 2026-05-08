# L3 · 多模型横向对比（首轮）

2026-05-08 · 目标 `example.com` · 模式 `recon` · Windows 11 · 已修 issue #20 三个 bug

## 结果

| 指标 | DeepSeek V4-Flash | Xiaomi MiMo V2.5-Pro |
|---|---|---|
| 耗时 | 52.6 s | 72.3 s |
| LLM 轮数 | 5 | 6 |
| Tool 调用成功率 | 4/4 | 4/4 |
| token 总量 | ~33.75 K | ~33.96 K |
| prompt cache hit | 0 | **192/256 首轮命中** |
| 报告字数 | 3422 | 3488 |
| 端点 | api.deepseek.com | token-plan-sgp.xiaomimimo.com/v1 |
| 成本 | ~¥0.07 | **¥0（Token Plan 100T 免费）** |
| wildcard DNS 检测 | ✅ 触发 | ✅ 触发（同一 bug 修复） |

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
