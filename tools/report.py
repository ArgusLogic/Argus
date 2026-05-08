"""报告生成工具：将侦察结果汇总为结构化 Markdown 报告。"""

import os
from datetime import datetime

from agent.tool_registry import registry


@registry.tool(
    name="generate_report",
    description=(
        "【作用】把本次侦察的所有发现汇总成结构化 Markdown 报告，自动生成 Top-3 风险卡（critical / high 优先）+ "
        "ASCII 拓扑图（≤5 节点时）+ LESSONS 命中。保存到 ~/.argus/output/reports/<timestamp>_<target>.md，返回路径。"
        "【关键参数】target（域名或 URL，必填）；summary（一句话总结，必填）；"
        "其余 dns_info / subdomains / open_ports / directories / headers / cookies / links / forms / js_analysis / whois_info / additional 都可选——传哪些有数据就填哪些。"
        "【何时用】每次侦察任务的最后一步。**不要自己拼 Markdown**——Top-3 算法、信号库、风险评分都封装在这里，你拼的不会比它好。"
        "【避坑】(1) 不传 summary 会被拒；"
        "(2) additional 是兜底字段，扫描类原始数据全往这塞会让 Top-3 信号库错过 → 优先填到 cookies / forms / links / js_analysis 专用字段；"
        "(3) Top-3 信号库识别 .git 暴露（critical）/ setup.php / swagger / GraphQL introspection / CORS 反射 / HSTS 缺失 / JSESSIONID 等关键模式，"
        "原始 dump 文本里包含这些字符串就会命中；"
        "(4) 已有报告再调一次会产生新文件不会覆盖。"
    ),
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

    # Day2-1: 顶部 Top-3 执行摘要（启发式扫描；无信号时不渲染）
    try:
        from tools._report_summary import build_executive_summary

        # 把页面类 / 表单 / JS / 补充 等非结构化文本合并成 body_hints，
        # 用于扫默认凭据 / GraphQL introspection 等需要 body 上下文的信号
        body_hints_text = "\n".join(
            s for s in (cookies, links, forms, js_analysis, additional) if s and s.strip()
        )
        summary_block = build_executive_summary(
            dns_info=dns_info,
            headers=headers,
            subdomains=subdomains,
            open_ports=open_ports,
            directories=directories,
            whois_info=whois_info,
            body_hints=body_hints_text,
        )
        if summary_block:
            sections.append(summary_block)
    except Exception:
        pass  # 摘要失败不阻塞报告生成

    # Day2-2: 顶部拓扑图
    try:
        from tools._report_topology import build_topology

        topology_block = build_topology(
            target=target,
            dns_info=dns_info,
            subdomains=subdomains,
            open_ports=open_ports,
        )
        if topology_block:
            sections.append(topology_block)
    except Exception:
        pass

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

    # Day2-3: 底部追加 LESSONS 命中（仅在有相关历史教训时渲染）
    try:
        from tools._report_lessons import render_lessons_block

        lessons_block = render_lessons_block(target)
        if lessons_block:
            sections.append(lessons_block)
    except Exception:
        pass

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
