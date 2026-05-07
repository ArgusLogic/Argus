"""报告生成工具：将侦察结果汇总为结构化 Markdown 报告。"""

import os
from datetime import datetime

from agent.tool_registry import registry


@registry.tool(
    name="generate_report",
    description="将本次信息收集的结果汇总为结构化 Markdown 侦察报告并保存到文件。传入各部分内容即可。",
    params={
        "target": {"type": "string", "description": "目标域名或 URL"},
        "summary": {"type": "string", "description": "简要概述本次侦察发现"},
        "dns_info": {
            "type": "string",
            "description": "DNS 查询结果",
            "required": False,
        },
        "subdomains": {
            "type": "string",
            "description": "子域名枚举结果",
            "required": False,
        },
        "open_ports": {
            "type": "string",
            "description": "端口扫描结果",
            "required": False,
        },
        "directories": {
            "type": "string",
            "description": "目录枚举结果",
            "required": False,
        },
        "headers": {
            "type": "string",
            "description": "HTTP 安全头分析结果",
            "required": False,
        },
        "cookies": {
            "type": "string",
            "description": "Cookie 信息",
            "required": False,
        },
        "links": {
            "type": "string",
            "description": "页面链接/站点地图",
            "required": False,
        },
        "forms": {
            "type": "string",
            "description": "表单信息",
            "required": False,
        },
        "js_analysis": {
            "type": "string",
            "description": "JS 分析结果（API 端点、敏感信息等）",
            "required": False,
        },
        "whois_info": {
            "type": "string",
            "description": "WHOIS 注册信息",
            "required": False,
        },
        "additional": {
            "type": "string",
            "description": "其他补充信息或发现",
            "required": False,
        },
    },
)
async def generate_report(
    target: str,
    summary: str,
    dns_info: str = "",
    subdomains: str = "",
    open_ports: str = "",
    directories: str = "",
    headers: str = "",
    cookies: str = "",
    links: str = "",
    forms: str = "",
    js_analysis: str = "",
    whois_info: str = "",
    additional: str = "",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_name = target.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
    filename = f"report_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    sections = []
    sections.append(f"# 侦察报告 — {target}\n")
    sections.append(f"> 生成时间: {now}\n")
    sections.append(f"## 概述\n\n{summary}\n")

    optional_sections = [
        ("DNS 信息", dns_info),
        ("子域名枚举", subdomains),
        ("开放端口", open_ports),
        ("目录枚举", directories),
        ("HTTP 安全头分析", headers),
        ("Cookie 信息", cookies),
        ("站点链接", links),
        ("表单发现", forms),
        ("JS 分析", js_analysis),
        ("WHOIS 信息", whois_info),
        ("其他发现", additional),
    ]

    for title, content in optional_sections:
        if content and content.strip():
            sections.append(f"## {title}\n\n```\n{content}\n```\n")

    sections.append("---\n*由 Argus 自动生成*\n")

    report_content = "\n".join(sections)

    # 保存到文件
    from utils.paths import REPORTS_DIR
    report_dir = REPORTS_DIR
    os.makedirs(report_dir, exist_ok=True)
    filepath = os.path.join(report_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    return f"报告已生成并保存: {filepath} ({len(report_content)} 字符)"
