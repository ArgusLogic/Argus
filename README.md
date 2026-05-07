# Argus - 网络安全信息收集 Agent

[![CI](https://github.com/ArgusLogic/Argus/actions/workflows/ci.yml/badge.svg)](https://github.com/ArgusLogic/Argus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

基于 LLM + Playwright 浏览器自动化的 CLI 安全侦察 Agent。输入自然语言任务，Agent 自动调用 44 个内置工具完成信息收集并生成报告。

## 功能概览

- **浏览器自动化** — 页面导航、内容获取、截图、点击、表单填写、JS 执行
- **DevTools 深度交互** — 网络抓包、请求拦截、Cookie 审计、响应头分析
- **智能爬虫** — 链接发现、递归站点地图、表单提取、JS 端点/密钥提取
- **侦察工具** — DNS 查询、子域名枚举、目录爆破、端口扫描、WHOIS、安全头评分
- **HTTP 客户端** — 自定义方法/头部/Body
- **报告生成** — 自动汇总为结构化 Markdown 报告
- **多模型支持** — DeepSeek / OpenAI / Claude / Ollama 一键切换
- **安全机制** — 三级审批（safe/confirm/block）、域名白名单、工具超时保护

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 Playwright 浏览器
playwright install chromium

# 3. 配置 API Key
cp config.example.toml config.toml
# 编辑 config.toml，至少填入一个 API Key

# 4. 启动
python main.py
```

### 可选：安装 nmap（端口扫描需要）

```bash
# Windows: https://nmap.org/download 下载安装
# macOS:   brew install nmap
# Linux:   sudo apt install nmap
```

## 使用示例

```
> 收集 example.com 的基本信息

[*] Turn 1/20 | Tokens: ~580
[Tool] dns_lookup → DNS 查询结果 (example.com): A: 93.184.216.34 ...
[Tool] browser_navigate → 状态码: 200 | 标题: Example Domain
[Tool] header_analysis → 安全头评分: 3/10
[Tool] crawl_links → 共发现 1 个链接
[Agent] ## 侦察报告 — example.com ...
```

## 工具列表（26 个）

| 分类 | 工具 | 说明 |
|------|------|------|
| 浏览器 | `browser_navigate` | 打开 URL，返回标题和状态码 |
| | `browser_get_html` | 获取页面/元素 HTML |
| | `browser_get_text` | 获取页面纯文本 |
| | `browser_screenshot` | 全页截图保存到本地 |
| | `browser_console_exec` | 在浏览器 Console 执行 JS |
| | `browser_click` | 点击页面元素 |
| | `browser_fill` | 在输入框填入文本 |
| DevTools | `devtools_start_capture` | 开启网络请求抓包 |
| | `devtools_network_log` | 查看已捕获的网络请求 |
| | `devtools_cookies` | 获取当前域的 Cookie |
| | `devtools_headers` | 获取页面 HTTP 响应头 |
| 爬虫 | `crawl_links` | 爬取页面所有链接 |
| | `crawl_forms` | 提取页面表单和输入字段 |
| | `crawl_js_sources` | 提取外部 JS 文件 URL |
| | `crawl_site_map` | BFS 递归爬取整站链接 |
| | `crawl_js_endpoints` | 从 JS 中提取 API 端点和密钥 |
| 侦察 | `dns_lookup` | DNS 查询（A/MX/NS/TXT/CNAME） |
| | `subdomain_enum` | 子域名枚举（内置 ~200 字典） |
| | `dir_bruteforce` | 目录/路径枚举（内置 ~130 路径） |
| | `port_scan` | 端口扫描（需 nmap） |
| | `whois_lookup` | WHOIS 注册信息查询 |
| | `header_analysis` | HTTP 安全头评分（10 项检查） |
| HTTP | `http_request` | 自定义 HTTP 请求 |
| 文件 | `save_file` | 保存文本到 output/ |
| | `read_file` | 读取 output/ 下的文件 |
| 报告 | `generate_report` | 生成结构化 Markdown 侦察报告 |

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/tools` | 列出所有已注册工具 |
| `/model <name>` | 切换 LLM 模型 |
| `/session save [name]` | 保存当前会话 |
| `/session load <name>` | 加载已保存的会话 |
| `/session list` | 列出所有已保存的会话 |
| `/session delete <name>` | 删除指定会话 |
| `/clear` | 清空对话上下文 |
| `/exit` | 退出程序 |

## 多模型配置

在 `config.toml` 中填入对应 API Key，运行时通过 `/model` 切换：

```
/model deepseek/deepseek-chat    # DeepSeek V3
/model gpt-4o                    # OpenAI GPT-4o
/model claude-sonnet-4-20250514             # Anthropic Claude
/model ollama/qwen2.5            # 本地 Ollama 模型
```

## 安全机制

### 三级审批

| 级别 | 行为 | 工具示例 |
|------|------|---------|
| **safe** | 自动执行 | 浏览器导航、DNS 查询、截图 |
| **confirm** | 需用户确认 | JS 执行、HTTP 请求、站点地图爬取 |
| **block** | 必须确认 + 风险提示 | 子域名枚举、目录爆破、端口扫描 |

### 域名白名单

在 `config.toml` 中配置 `allowed_domains`，限制 Agent 只能扫描指定域名：

```toml
[security]
allowed_domains = ["example.com", "testsite.local"]
```

为空时不限制。

### 工具超时与重试

```toml
[general]
tool_timeout = 60   # 单次工具执行超时（秒）
max_retries = 2     # 失败重试次数
```

## 项目结构

```
agent/
├── main.py                  # CLI 入口
├── config.toml              # 配置文件（gitignored）
├── config.example.toml      # 配置模板
├── requirements.txt
├── README.md
├── agent/
│   ├── engine.py            # Agent 核心循环（审批 + 重试 + 白名单）
│   ├── llm_client.py        # LLM 统一调用层（litellm）
│   ├── tool_registry.py     # 工具注册与分发（超时保护）
│   ├── context.py           # 上下文管理（LLM 智能摘要）
│   ├── session.py           # 会话持久化（SQLite）
│   └── prompts.py           # 系统提示词
├── tools/
│   ├── browser.py           # 浏览器控制（7 工具）
│   ├── devtools.py          # DevTools 交互（4 工具）
│   ├── crawler.py           # 爬虫（5 工具）
│   ├── recon.py             # 侦察（6 工具）
│   ├── recon_wordlists.py   # 内置子域名/目录字典
│   ├── http_client.py       # HTTP 请求（1 工具）
│   ├── file_ops.py          # 文件操作（2 工具）
│   └── report.py            # 报告生成（1 工具）
└── utils/
    ├── logger.py            # 日志（终端 + 文件）
    └── sanitizer.py         # 输入清洗
```

## 靶场测试

推荐使用以下靶场环境测试：

- **DVWA** — `docker run -d -p 80:80 vulnerables/web-dvwa`
- **OWASP Juice Shop** — `docker run -d -p 3000:3000 bkimminich/juice-shop`
- **HackTheBox** — https://www.hackthebox.com

```
# 示例：对本地 DVWA 进行信息收集
> 对 http://localhost 进行全面信息收集，包括页面爬取、表单发现、JS 分析和安全头检查
```

## 安全声明

**本工具仅用于授权目标的安全测试。** 未经授权对他人系统进行扫描、探测属违法行为，使用者需自行承担法律责任。
