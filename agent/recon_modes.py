"""issue #8：一键侦察模式模板。

被 main.py `--target / --mode` 一次性 CLI 入口使用，把简单参数转成 Agent 任务 prompt。
故意保持纯字符串模板（无 LLM 调用），方便测试和后续迭代。
"""

from __future__ import annotations

RECON_TEMPLATES: dict[str, str] = {
    "recon": (
        "对目标 `{target}` 做被动侦察（read-only），按顺序执行：\n"
        "1. dns_lookup —— 查询 A/AAAA/MX/NS/TXT/CNAME 记录\n"
        "2. whois_lookup —— 拉取注册信息\n"
        "3. http_security_headers —— 评估 HSTS/CSP/X-Frame-Options 等头\n"
        "4. subdomain_enum —— 用内置词表枚举存活子域名\n"
        "5. generate_report —— 汇总以上发现，输出结构化 markdown 报告\n"
        "整个过程禁止主动扫描或写操作。"
    ),
    "scan": (
        "对目标 `{target}` 做主动侦察（中强度），按顺序执行：\n"
        "1. 完成 recon 流程（dns_lookup / whois_lookup / http_security_headers / subdomain_enum）\n"
        "2. dir_bruteforce —— 用内置/自定义字典枚举常见路径\n"
        "3. port_scan —— 扫常用端口（默认 21-25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017）\n"
        "4. generate_report —— 汇总报告\n"
        "对每个工具失败时记录原因继续，不要因单点失败放弃整体流程。"
    ),
    "full": (
        "对目标 `{target}` 做完整侦察链（含浏览器爬取），按顺序执行：\n"
        "1. 完成 scan 流程（dns/whois/headers/subdomain/dir/port）\n"
        "2. browser_navigate 打开目标首页\n"
        "3. browser_screenshot 抓首页截图\n"
        "4. browser_get_html 提取页面，识别 JS 端点 / 表单 / 入口链接\n"
        "5. generate_report —— 输出 markdown 报告，引用截图和发现的端点\n"
        "如浏览器初始化失败，回退到 http_request 抓 HTML。"
    ),
}


VALID_MODES: tuple[str, ...] = tuple(RECON_TEMPLATES.keys())


def render_prompt(target: str, mode: str = "recon") -> str:
    """渲染一键侦察 prompt。

    Args:
        target: 域名或 URL，原样代入模板
        mode: recon | scan | full

    Raises:
        ValueError: mode 不在 VALID_MODES
    """
    if mode not in RECON_TEMPLATES:
        raise ValueError(f"未知 --mode 值：{mode}（合法：{', '.join(VALID_MODES)}）")
    target = target.strip()
    if not target:
        raise ValueError("--target 不能为空")
    return RECON_TEMPLATES[mode].format(target=target)
