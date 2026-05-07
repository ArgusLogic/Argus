# Argus

[![CI](https://github.com/ArgusLogic/Argus/actions/workflows/ci.yml/badge.svg)](https://github.com/ArgusLogic/Argus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-383%20passing-green.svg)](#测试)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 基于 LLM 的 CLI 自主侦察 Agent。一句自然语言任务，**44 个内置工具**全程自动调度——浏览器自动化、DevTools 抓包、JS 端点挖掘、SSE 流式捕获、子域名/目录枚举、端口扫描、请求重放，最终产出结构化 Markdown 报告。

## 亮点

- **真正可用的浏览器** — Playwright 驱动，含 iframe 上下文切换、多 tab 管理、wait_for 智能等待、文件上传/下载、键盘输入、SSE/EventSource 流式捕获
- **HTTP 客户端复用浏览器会话** — Cookie / User-Agent / Referer 一键继承，登录态接口直接调
- **JS 深度分析** — 7 套正则覆盖端点提取，启发式过滤误报，68 KB 大 JS 不再截断
- **请求重放** — 从 DevTools 网络日志取任意请求，改 header/body 后重发
- **项目状态存储** — 结构化 JSON 持久化目标信息，跨会话沿用
- **子代理并行** — `delegate_subagents` 同时打多个目标，主代理只看汇总
- **自演化闭环** — success_count 自动增量、LESSONS 避坑库、自动提炼技能、skill curator、用户画像、跨会话 insights、agentskills.io 互操作
- **Rust 加速骨架** — `argus_native` crate via PyO3，Python fallback 透明
- **完整工程化** — ruff/mypy/pytest 全绿，**383 测试**，GitHub Actions CI（Linux + Windows × Python 3.11/3.12）

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/ArgusLogic/Argus.git
cd Argus

# 2. 安装
pip install -e ".[dev]"
playwright install chromium

# 3. 配置
cp config.example.toml config.toml
# 编辑 config.toml，填入至少一个 LLM API Key

# 4. 启动
python main.py
```

可选依赖（按需）：

```bash
# 端口扫描需 nmap
sudo apt install nmap         # Linux
brew install nmap             # macOS
# Windows: https://nmap.org/download

# Rust 加速器（可选）
cd argus_native
maturin build --release
pip install target/wheels/*.whl
```

## 支持的模型

通过 [LiteLLM](https://docs.litellm.ai/) 统一接入，运行时用 `/model` 切换：

| 提供方 | 推荐模型 | 上下文 | 备注 |
|---|---|---|---|
| **DeepSeek** | `deepseek/deepseek-v4-flash` | 128K | 性价比首选 ¥1/2 per Mtok |
| | `deepseek/deepseek-v4-pro` | 128K | 更强推理，2.5 折时段 ¥3/6 |
| **OpenAI** | `gpt-5.5` | 400K | 最新旗舰 |
| | `gpt-5.4-mini` | 400K | 高性价比 |
| **Anthropic** | `claude-sonnet-4-6` | 200K | 编码/Agent 任务首选 |
| | `claude-opus-4-7` | 200K | 旗舰，复杂推理 |
| **本地** | `ollama/qwen3:32b` 等 | 视模型 | Ollama 接入零成本 |

> **注**：DeepSeek 旧别名 `deepseek-chat` / `deepseek-reasoner` 将于 **2026-07-24 退役**，请尽快迁移到 `v4-flash` / `v4-pro`。

支持 **DeepSeek V4 thinking mode** 与 **OpenAI / Claude reasoning effort**，CLI 中 `/effort high|max|off` 切换深度推理。

## 工具列表（44 个）

<details>
<summary><b>浏览器自动化（13）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `browser_navigate` | 打开 URL，返回标题 + 状态码 | safe |
| `browser_get_html` | 获取页面 / 元素 HTML | safe |
| `browser_get_text` | 获取页面纯文本 | safe |
| `browser_screenshot` | 全页截图 | safe |
| `browser_click` | 点击元素（CSS/XPath） | confirm |
| `browser_fill` | 填表单 | confirm |
| `browser_console_exec` | 浏览器 Console 执行 JS | confirm |
| `browser_wait_for` | CSS / JS 表达式 / 内置预设智能等待 | safe |
| `browser_tabs` | list / switch / close 多 tab | safe |
| `browser_frame` | 切换到 iframe 上下文（top 返回顶层）| safe |
| `browser_upload` | 文件上传 | confirm |
| `browser_keyboard` | 键盘按键 / 组合键 / 输入 | confirm |
| `browser_download` | 触发并保存下载 | confirm |
</details>

<details>
<summary><b>DevTools / 网络（5）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `devtools_start_capture` | 开启网络抓包 + SSE/EventSource 注入（首次启动浏览器自动开启）| safe |
| `devtools_network_log` | 查看已捕获请求（支持过滤）| safe |
| `devtools_sse_log` | 查看 SSE / EventSource / fetch 流式响应内容 | safe |
| `devtools_sse_clear` | 清空 SSE 缓冲区 | safe |
| `devtools_cookies` / `devtools_headers` | Cookie 审计 + 响应头查看 | safe |
</details>

<details>
<summary><b>智能爬虫（5）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `crawl_links` | 提取页面所有链接 | safe |
| `crawl_forms` | 提取表单和输入字段 | safe |
| `crawl_js_sources` | 列出外部 JS 源 | safe |
| `crawl_site_map` | BFS 递归爬取整站 | confirm |
| `crawl_js_endpoints` | 7 套正则 + 启发式提取 API 端点 / 密钥 | safe |
</details>

<details>
<summary><b>侦察（6）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `dns_lookup` | A / AAAA / MX / NS / TXT / CNAME | safe |
| `whois_lookup` | WHOIS 注册信息 | safe |
| `header_analysis` | HTTP 安全头评分（10 项）| safe |
| `subdomain_enum` | 子域枚举（内置 ~200 字典）| block |
| `dir_bruteforce` | 目录枚举（内置 ~130 路径）| block |
| `port_scan` | nmap 端口扫描 | block |
</details>

<details>
<summary><b>HTTP / 重放（3）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `http_request` | 自定义 HTTP 请求，可复用浏览器会话 + `save_to` 保存大文件 | confirm |
| `request_replay_list` | 列出 DevTools 已捕获请求 | safe |
| `request_replay` | 选取某请求，覆盖 header / body 后重发 | confirm |
</details>

<details>
<summary><b>记忆 / 项目 / 技能 / 子代理 / 文件 / 报告（12）</b></summary>

| 工具 | 说明 | 风险 |
|---|---|:-:|
| `memory_manage` | MEMORY.md 增删改查（结构化笔记）| safe |
| `session_search` | 历史会话全文检索 | safe |
| `project_save` / `project_load` / `project_list` / `project_delete` | 结构化项目状态持久化（`~/.argus/projects/`）| safe |
| `skill_manage` | 创建 / 修改 / 删除可复用技能（Hermes 风格）| safe |
| `delegate_subagents` | 派发子任务并行执行 | confirm |
| `save_file` / `read_file` | output/ 目录文件 IO | safe |
| `generate_report` | 汇总生成结构化 Markdown 报告 | safe |
</details>

## CLI 命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示帮助 |
| `/tools` | 列出所有已注册工具 + 风险等级 |
| `/model` | 交互式选择模型 + reasoning effort |
| `/effort off\|high\|max` | 切换推理深度 |
| `/yolo` ⇄ `/agent` | YOLO（无审批）⇄ Agent（高风险审批） |
| `/session save \| load \| list \| delete` | 会话持久化 |
| `/skills list \| show \| delete \| pin \| unpin \| export \| import` | 技能管理 + agentskills.io 互操作 |
| `/curator [--dry-run]` | 立即跑一次 skill curator（合并/归档） |
| `/insights [--days N]` | 跨会话趋势报表 |
| `/clear` | 清空上下文 |
| `/exit` | 退出 |

## 自演化（Self-Evolution）

Argus 在每轮任务结束时**自动**沉淀经验，不需要主 LLM 主动管。所有特性都可独立开关：

| 项 | 模块 | LLM 成本 | 默认 | 配置项 |
|---|---|:-:|:-:|---|
| **A1**: success_count 自动增量 | `agent/skills.py` | 零 | ✅ | `[skills] track_usage` |
| **A2**: 自动提炼新技能（LLM judge） | `agent/skill_extractor.py` | 每轮 1 次轻量 prompt | ❌ | `[skills] auto_extract` |
| **A3**: LESSONS 失败避坑库 | `agent/lessons.py` | 零（启发式正则） | ✅ | `[memory] track_lessons` |
| **B1**: skill curator（合并/归档） | `agent/curator.py` | 零（SequenceMatcher） | ❌（独立 daemon） | `[skills.curator] enabled` |
| **B2**: 用户画像归纳 | `agent/user_profile.py` | curator 周期 1 次 | ❌ | `[skills.curator] update_user_profile` |
| **C1**: `/insights` 跨会话报表 | `agent/insights.py` | 零（SQLite 聚合） | ✅（按需调用） | — |
| **C2**: 失败请求结构化日志 | `agent/failure_log.py` | 零 | ❌ | `[memory] track_failure_replays` |
| **C3**: agentskills.io 互操作 | `agent/skill_interop.py` | 零 | ✅ | — |

### 启用 curator 后台进程

```bash
# 单次跑一遍（建议先用 --dry-run 看报告）
python -m agent.curator run --dry-run

# 后台常驻定时跑（cron 风格）
python -m agent.curator daemon --interval 24h
```

报告写入 `~/.argus/curator_reports/YYYYMMDD_HHMMSS.md`。

### 与 agentskills.io 互操作

```bash
# 在 CLI 里：
/skills export recon_pipeline           # 导出到 ~/.argus/skills_export/
/skills import path/to/SKILL.md         # 或导入一个外部技能包
```

兼容 [agentskills.io 规范](https://agentskills.io/specification)：YAML frontmatter + Markdown body，可与 Hermes/Claude Code/Cursor 共享技能。

## 安全机制

### 工具风险三级

| 级别 | 行为 | 工具示例 |
|---|---|---|
| **safe** | 自动执行 | `dns_lookup`, `browser_get_text`, `crawl_links` |
| **confirm** | Agent 模式下需用户审批 | `browser_console_exec`, `http_request`, `crawl_site_map` |
| **block** | 必须审批 + 风险提示 | `subdomain_enum`, `dir_bruteforce`, `port_scan` |

### 工具 ACL（白/黑名单 + 强制审批）

```toml
[security]
# 仅允许这些工具（白名单优先）
tool_allowlist = ["dns_lookup", "whois_lookup", "browser_navigate", "browser_get_text"]
# 显式禁用（最高优先级）
tool_blocklist = ["browser_console_exec", "port_scan"]
# 即使 YOLO 模式也强制审批
require_approval_for = ["delegate_subagents", "subdomain_enum"]
# 优先级：blocklist > allowlist > require_approval > approval_mode
```

### 域名白名单

```toml
[security]
allowed_domains = ["example.com", "*.testsite.local"]
```

为空则不限制。

### 工具超时

```toml
[general]
tool_timeout = 60   # 秒
max_retries = 2
```

## 项目结构

```
Argus/
├── main.py                    # CLI 入口
├── pyproject.toml             # 依赖 + ruff/mypy/pytest 配置
├── config.example.toml        # 配置模板
├── agent/
│   ├── engine.py              # 核心循环 + 审批 + ACL + 子代理调度
│   ├── llm_client.py          # LiteLLM 统一封装
│   ├── tool_registry.py       # 工具注册 + 超时保护
│   ├── memory.py              # SQLite + FTS5 长期记忆
│   ├── memory_md.py           # MEMORY.md 结构化笔记
│   ├── skills.py              # 技能管理
│   ├── subagent.py            # 子代理并行编排
│   ├── session.py             # 会话持久化
│   ├── errors.py              # 12 个结构化异常
│   └── prompts.py             # 系统提示词
├── tools/                     # 44 个工具实现
├── utils/
│   ├── sanitizer.py           # URL / 文件名 / ANSI / 密钥脱敏（Rust 加速）
│   ├── _native.py             # Rust shim（自动 fallback）
│   ├── logger.py
│   └── ui.py                  # Rich Live UI
├── argus_native/              # Rust crate（可选）
│   ├── Cargo.toml
│   └── src/{lib,sanitizer,memory}.rs
├── tests/                     # 267 测试
└── .github/workflows/ci.yml   # lint + mypy + pytest matrix + Rust build
```

## 开发

### 测试

```bash
pytest                                    # 全部 267 测试
pytest tests/test_browser_extras.py -v    # 单文件
pytest --cov --cov-report=term            # 覆盖率
```

### Lint / Format / Type

```bash
ruff check .
ruff format .
mypy agent tools utils main.py
pre-commit run --all-files                # 全套（已配 pre-commit）
```

### 关键模块覆盖率

| 模块 | 覆盖率 |
|---|:-:|
| `agent/errors.py` | 100% |
| `agent/session.py` | 100% |
| `utils/sanitizer.py` | 94% |
| `tools/request_replay.py` | 93% |
| `agent/skills.py` | 92% |
| `agent/subagent.py` | 91% |
| `tools/project_store.py` | 90% |
| `tools/http_client.py` | 87% |

### Rust 加速（可选）

`utils/sanitizer.py` 与 `agent/memory_md.py` 的热路径函数会自动委托给 `argus_native` Rust 实现（如果 wheel 已安装），失败透明回退 Python。环境变量 `ARGUS_NO_NATIVE=1` 可强制禁用。

## 靶场

```bash
# DVWA
docker run -d -p 80:80 vulnerables/web-dvwa
# OWASP Juice Shop
docker run -d -p 3000:3000 bkimminich/juice-shop
```

```
> 对 http://localhost 做完整侦察：抓包、表单、JS 端点、安全头评分，最后生成报告
```

## 路线图

- [x] v9：浏览器原语 + SSE 捕获 + 请求重放 + 项目存储 + 子代理 + Rust 加速骨架
- [x] v10：自演化闭环（A1+A2+A3+B1+B2+C1+C2+C3，对齐 Hermes 自演化基线 + agentskills.io 互操作）
- [ ] v11：MCP 协议接入（让 Argus 既能消费也能暴露工具）
- [ ] v12：分布式扫描后端（多浏览器 worker + 任务队列）
- [ ] v13：插件市场（社区贡献工具）

## 安全声明

**本工具仅用于授权目标的安全测试。** 未经授权对他人系统进行扫描、探测属违法行为，使用者需自行承担法律责任。

## License

MIT
