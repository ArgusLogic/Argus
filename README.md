# Argus

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/ArgusLogic/Argus/ci.yml?label=CI&logo=github" alt="CI">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/ruff-%E2%9C%93-success" alt="Ruff">
  <img src="https://img.shields.io/badge/tests-267%20passing-success" alt="267 tests">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
</p>

<p align="center">
  <b>基于 LLM 的自主侦察 Agent</b><br>
  说一句自然语言，44 个工具全程自动调度<br>
  浏览器自动化 · DevTools 抓包 · JS 端点挖掘 · 子域名枚举 · 端口扫描 · 请求重放<br>
  最终产出结构化 Markdown 报告
</p>

---

## 目录

- [✨ 快速体验](#-快速体验)
- [🎯 它能做什么](#-它能做什么)
- [⚡ 快速开始](#-快速开始)
- [🛠️ 工具全览](#️-工具全览)
- [🧠 支持的模型](#-支持的模型)
- [⌨️ CLI 命令](#️-cli-命令)
- [🔒 安全机制](#-安全机制)
- [📁 项目结构](#-项目结构)
- [🛡️ 安全声明](#️-安全声明)

---

## ✨ 快速体验

```bash
# 启动后输入：
> 对 example.com 做信息收集
```

Argus 会自动：
1. 打开浏览器访问目标页面
2. 提取链接、表单、JS 资源
3. 分析 HTTP 安全头（10 项评分）
4. 查询 WHOIS 和 DNS 记录
5. 枚举子域名和开放端口
6. 生成结构化 Markdown 报告

**全程无需人工干预。** 一个命令，报告到手。

---

## 🎯 它能做什么

| 场景 | 一句话指令 | Argus 会做什么 |
|------|-----------|---------------|
| 🕵️ 信息收集 | `对 example.com 做信息收集` | 浏览器打开 → 爬链接/表单/JS → WHOIS → DNS → 安全头分析 → 报告 |
| 🔍 子域名扫描 | `扫描 example.com 的子域名和开放端口` | 子域枚举 → DNS 解析 → 端口扫描 → 结果汇总 |
| 📡 API 接口发现 | `分析这个登录页的 API 接口` | 浏览器打开登录页 → 开启 DevTools 抓包 → 提取 XHR/fetch 请求 → 输出接口列表 |
| 🔐 安全审计 | `审计 example.com 的安全配置` | 分析 10 项安全头 → Cookie 安全属性 → Server 头泄露 → 生成安全建议 |
| 📄 深度分析 JS | `提取这个页面的 JS API 端点` | 下载 JS 文件 → 7 套正则提取端点 → 启发式过滤 → 输出发现的 API 路径 |
| 🔄 请求重放 | `重放登录接口，改一下参数` | 从网络日志选请求 → 修改 header/body → 重发 → 显示响应 |
| ⚡ 并行侦察 | `同时扫描 targets.txt 里的所有目标` | 派发子代理并行执行 → 主代理收汇总报告 |

### 实测效果

在一个真实 DigitalOcean 节点上的侦察结果：

```
目标: 165.22.240.99
→ 发现: nginx 1.24.0 · Cloudflare CDN · DigitalOcean 纽约节点
→ 发现: /api/ (403 但暴露路径) · /app/ (APK 分发目录)
→ 发现: 站长李明景 · 西亚斯课表助手 v1.0.21
→ 截图已保存 · 完整报告已生成 (4932 字符)
→ 全程: 34 个工具调用 · 23 万 tokens · ¥0.25
```

---

## ⚡ 快速开始

### 安装

```bash
# 1. 克隆
git clone https://github.com/ArgusLogic/Argus.git
cd Argus

# 2. 创建虚拟环境并安装
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. 安装浏览器
playwright install chromium

# 4. 配置
cp config.example.toml config.toml
# 编辑 config.toml，填入至少一个 LLM API Key

# 5. 启动
python main.py
```

### 可选依赖

```bash
# 端口扫描（推荐）
sudo apt install nmap         # Linux
brew install nmap             # macOS

# Rust 加速器（可选，提升脱敏/记忆处理性能）
cd argus_native
maturin build --release
pip install target/wheels/*.whl
```

### 启动后

```
> 对 example.com 做完整侦察，然后生成报告
```

Argus 会一路执行下去，完成后报告自动保存到 `output/reports/`，截图保存到 `output/screenshots/`。

---

## 🛠️ 工具全览

### 浏览器自动化（13）

| 工具 | 说明 | 风险 |
|---|---|---|
| `browser_navigate` | 打开 URL，返回标题 + 状态码 | safe |
| `browser_get_html` | 获取页面 / 元素 HTML | safe |
| `browser_get_text` | 获取页面纯文本 | safe |
| `browser_screenshot` | 全页截图 | safe |
| `browser_click` | 点击元素（CSS/XPath） | confirm |
| `browser_fill` | 填表单 | confirm |
| `browser_console_exec` | 浏览器 Console 执行 JS | confirm |
| `browser_wait_for` | CSS / JS 表达式 / 内置预设智能等待 | safe |
| `browser_tabs` | 管理多标签页 | safe |
| `browser_frame` | iframe 上下文切换 | safe |
| `browser_upload` | 文件上传 | confirm |
| `browser_keyboard` | 键盘输入 / 组合键 | confirm |
| `browser_download` | 触发并保存下载 | confirm |

### DevTools / 网络（5）

| 工具 | 说明 | 风险 |
|---|---|---|
| `devtools_start_capture` | 开启网络抓包 + SSE/EventSource 注入 | safe |
| `devtools_network_log` | 查看已捕获请求（支持过滤） | safe |
| `devtools_sse_log` | 查看 SSE / EventSource 响应内容 | safe |
| `devtools_sse_clear` | 清空 SSE 缓冲区 | safe |
| `devtools_cookies` / `devtools_headers` | Cookie 审计 + 响应头查看 | safe |

### 智能爬虫（5）

| 工具 | 说明 | 风险 |
|---|---|---|
| `crawl_links` | 提取页面所有链接 | safe |
| `crawl_forms` | 提取表单和输入字段 | safe |
| `crawl_js_sources` | 列出外部 JS 源 | safe |
| `crawl_site_map` | BFS 递归爬取整站 | confirm |
| `crawl_js_endpoints` | 提取 API 端点 / 密钥（7 套正则 + 启发式过滤） | safe |

### 侦察（6）

| 工具 | 说明 | 风险 |
|---|---|---|
| `dns_lookup` | A / AAAA / MX / NS / TXT / CNAME | safe |
| `whois_lookup` | WHOIS 注册信息 | safe |
| `header_analysis` | HTTP 安全头评分（10 项） | safe |
| `subdomain_enum` | 子域枚举 | block |
| `dir_bruteforce` | 目录枚举 | block |
| `port_scan` | 端口扫描（需 nmap） | block |

### HTTP / 请求重放（3）

| 工具 | 说明 | 风险 |
|---|---|---|
| `http_request` | 自定义 HTTP 请求，可复用浏览器会话 | confirm |
| `request_replay_list` | 列出 DevTools 已捕获请求 | safe |
| `request_replay` | 选取请求，覆盖 header/body 后重发 | confirm |

### 记忆 / 项目 / 技能 / 子代理 / 文件 / 报告（12）

| 工具 | 说明 | 风险 |
|---|---|---|
| `memory_manage` | MEMORY.md 增删改查 | safe |
| `session_search` | 历史会话全文检索 | safe |
| `project_save/load/list/delete` | 项目状态持久化 | safe |
| `skill_manage` | 创建/修改/删除可复用技能 | safe |
| `delegate_subagents` | 派发子任务并行执行 | confirm |
| `save_file` / `read_file` | output/ 目录文件 IO | safe |
| `generate_report` | 生成 Markdown 报告 | safe |

---

## 🧠 支持的模型

通过 [LiteLLM](https://docs.litellm.ai/) 统一接入，运行时用 `/model` 切换。

| 提供方 | 推荐模型 | 上下文 | 备注 |
|---|---|---|---|
| **DeepSeek** | `deepseek/deepseek-v4-flash` | 128K | 🏆 性价比首选，¥1/2 per Mtok |
| | `deepseek/deepseek-v4-pro` | 128K | 更强推理，¥3/6 |
| **OpenAI** | `gpt-5.5` | 400K | 最新旗舰 |
| | `gpt-5.4-mini` | 400K | 高性价比 |
| **Anthropic** | `claude-sonnet-4-6` | 200K | 编码/Agent 任务首选 |
| | `claude-opus-4-7` | 200K | 旗舰推理 |
| **本地** | `ollama/qwen3:32b` 等 | 视模型 | Ollama 接入，零成本 |

> ⚠️ DeepSeek 旧别名 `deepseek-chat` / `deepseek-reasoner` 将于 **2026-07-24 退役**，请尽快迁移到 `v4-flash` / `v4-pro`。

支持 DeepSeek V4 thinking mode 与 OpenAI/Claude reasoning effort，CLI 中用 `/effort high|max|off` 切换推理深度。

---

## ⌨️ CLI 命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示帮助 |
| `/tools` | 列出所有已注册工具 + 风险等级 |
| `/model` | 交互式选择模型 |
| `/effort off\|high\|max` | 切换推理深度 |
| `/yolo` | **开启 YOLO 模式** — 跳过所有工具审批，全自动执行 |
| `/agent` | 恢复审批模式 — 高风险工具需人工确认 |
| `/session save\|load\|list\|delete` | 会话持久化 |
| `/clear` | 清空上下文 |
| `/exit` | 退出 |

> 💡 启动后先敲 `/yolo` 进入全自动模式，然后输入侦察指令，体验最流畅。

---

## 🔒 安全机制

### 三级风险控制

| 级别 | 行为 | 示例工具 |
|---|---|---|
| **safe** | 自动执行 | `dns_lookup`, `crawl_links`, `header_analysis` |
| **confirm** | 需用户审批 | `browser_console_exec`, `http_request`, `delegate_subagents` |
| **block** | 审批 + 风险提示 | `subdomain_enum`, `port_scan`, `dir_bruteforce` |

### 工具 ACL

```toml
[security]
tool_allowlist = ["dns_lookup", "whois_lookup", "browser_navigate"]
tool_blocklist = ["browser_console_exec", "port_scan"]
require_approval_for = ["delegate_subagents"]

# 优先级：blocklist > allowlist > require_approval > approval_mode
```

### 域名白名单

```toml
[security]
allowed_domains = ["example.com", "*.testsite.local"]
# 为空则不限制
```

### 超时控制

```toml
[general]
tool_timeout = 60    # 单次工具执行超时（秒）
max_retries = 2      # 失败重试次数
```

---

## 📁 项目结构

```
Argus/
├── main.py                    # CLI 入口
├── config.example.toml        # 配置模板
├── pyproject.toml             # 依赖 + ruff/mypy/pytest 配置
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
│   ├── browser.py             # Playwright 浏览器控制
│   ├── crawler.py             # 爬虫 / JS 端点提取
│   ├── devtools.py            # CDP 网络抓包
│   ├── recon.py               # DNS / WHOIS / 安全头
│   ├── recon_wordlists.py     # 子域/目录字典
│   └── ...                    # 更多工具
├── utils/
│   ├── sanitizer.py           # 脱敏（可选 Rust 加速）
│   ├── _native.py             # Rust shim（自动 fallback）
│   ├── logger.py              # 日志
│   ├── ui.py                  # Rich Live UI
│   └── paths.py               # 路径常量
├── argus_native/              # Rust crate（可选加速）
│   ├── Cargo.toml
│   └── src/{lib,sanitizer,memory}.rs
├── tests/                     # 267 个测试
│   ├── test_browser_extras.py
│   ├── test_crawl_js.py
│   ├── test_subagent.py
│   └── ...
└── .github/workflows/ci.yml   # CI（lint + mypy + pytest × 2 OS × 2 Python）
```

### 开发

```bash
# 全部测试
pytest

# 单文件测试
pytest tests/test_browser_extras.py -v

# 代码质量
ruff check .
ruff format .
mypy agent tools utils main.py
pre-commit run --all-files
```

| 模块 | 覆盖率 |
|---|---|
| `agent/errors.py` | 100% |
| `agent/session.py` | 100% |
| `utils/sanitizer.py` | 94% |
| `tools/request_replay.py` | 93% |

### Rust 加速（可选）

热路径函数（sanitizer、memory_md）自动委托给 `argus_native` crate（PyO3）。如果 wheel 未安装，透明回退 Python 实现。环境变量 `ARGUS_NO_NATIVE=1` 可强制禁用。

### 靶场

```bash
# DVWA
docker run -d -p 80:80 vulnerables/web-dvwa
# OWASP Juice Shop
docker run -d -p 3000:3000 bkimminich/juice-shop
```

进入 Argus 后：
```
> 对 http://localhost 做完整侦察：抓包、表单、JS 端点、安全头评分，生成报告
```

---

## 🛡️ 安全声明

**本工具仅用于授权目标的安全测试。** 未经授权对他人系统进行扫描、探测属违法行为，使用者需自行承担法律责任。

---

## License

MIT © ArgusLogic
