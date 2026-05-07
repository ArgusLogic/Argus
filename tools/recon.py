"""侦察工具：DNS 查询、子域名枚举、目录爆破、端口扫描、WHOIS、安全头分析。"""

import asyncio
import json

import dns.resolver
import httpx
import nmap

from agent.tool_registry import registry
from tools.recon_wordlists import DIRECTORIES, SUBDOMAINS
from utils.sanitizer import sanitize_url, truncate


@registry.tool(
    name="dns_lookup",
    description="对目标域名进行 DNS 查询，支持 A/AAAA/MX/NS/TXT/CNAME 记录类型",
    params={
        "domain": {"type": "string", "description": "目标域名，如 example.com"},
        "record_type": {
            "type": "string",
            "description": "DNS 记录类型（A/AAAA/MX/NS/TXT/CNAME），默认查询全部",
            "required": False,
        },
    },
)
async def dns_lookup(domain: str, record_type: str = "ALL") -> str:
    domain = domain.strip().rstrip(".")
    record_types = (
        [record_type.upper()]
        if record_type.upper() != "ALL"
        else ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]
    )

    results = []
    for rtype in record_types:
        try:
            answers = dns.resolver.resolve(domain, rtype)
            records = []
            for rdata in answers:
                records.append(str(rdata))
            if records:
                results.append(f"  {rtype}: {', '.join(records)}")
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            return f"域名不存在: {domain}"
        except dns.resolver.NoNameservers:
            results.append(f"  {rtype}: 无法联系 DNS 服务器")
        except Exception as e:
            results.append(f"  {rtype}: 查询失败 ({e})")

    if not results:
        return f"未查询到 {domain} 的 DNS 记录"

    return f"DNS 查询结果 ({domain}):\n" + "\n".join(results)


# ─── 子域名枚举 ──────────────────────────────────────────────────────────────


async def _resolve_subdomain(sub: str, domain: str) -> str | None:
    """尝试解析一个子域名，返回 IP 或 None。"""
    fqdn = f"{sub}.{domain}"
    try:
        answers = await asyncio.get_event_loop().run_in_executor(
            None, lambda: dns.resolver.resolve(fqdn, "A")
        )
        ips = [str(r) for r in answers]
        return f"{fqdn} → {', '.join(ips)}"
    except Exception:
        return None


@registry.tool(
    name="subdomain_enum",
    description="对目标域名进行子域名枚举，使用内置字典通过 DNS 验证存活子域名",
    params={
        "domain": {"type": "string", "description": "目标根域名，如 example.com"},
        "concurrency": {
            "type": "string",
            "description": "并发数（默认 20）",
            "required": False,
        },
    },
)
async def subdomain_enum(domain: str, concurrency: str = "20") -> str:
    domain = domain.strip().rstrip(".")
    max_concurrent = int(concurrency)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def check(sub: str) -> str | None:
        async with semaphore:
            return await _resolve_subdomain(sub, domain)

    tasks = [check(sub) for sub in SUBDOMAINS]
    results = await asyncio.gather(*tasks)
    found = [r for r in results if r is not None]

    if not found:
        return f"未发现 {domain} 的存活子域名（已检测 {len(SUBDOMAINS)} 个）"

    lines = [f"  {r}" for r in found]
    return f"子域名枚举 ({domain}) — 发现 {len(found)}/{len(SUBDOMAINS)}:\n" + "\n".join(lines)


# ─── 目录爆破 ─────────────────────────────────────────────────────────────────


@registry.tool(
    name="dir_bruteforce",
    description="对目标 URL 进行目录/路径枚举，发现隐藏路径和敏感文件",
    params={
        "url": {"type": "string", "description": "目标 URL（如 https://example.com）"},
        "concurrency": {
            "type": "string",
            "description": "并发数（默认 10）",
            "required": False,
        },
    },
)
async def dir_bruteforce(url: str, concurrency: str = "10") -> str:
    url = sanitize_url(url).rstrip("/")
    max_concurrent = int(concurrency)
    semaphore = asyncio.Semaphore(max_concurrent)
    found = []

    async def check_path(client: httpx.AsyncClient, path: str) -> None:
        async with semaphore:
            target = f"{url}{path}"
            try:
                resp = await client.get(target, follow_redirects=False)
                if resp.status_code < 404:
                    size = len(resp.content)
                    found.append(f"  [{resp.status_code}] {path}  ({size} bytes)")
            except Exception:
                pass

    try:
        async with httpx.AsyncClient(
            timeout=10.0, verify=False,
            headers={"User-Agent": "Mozilla/5.0 Argus/0.1"},
        ) as client:
            tasks = [check_path(client, path) for path in DIRECTORIES]
            await asyncio.gather(*tasks)
    except Exception as e:
        return f"目录枚举失败: {e}"

    if not found:
        return f"未发现可访问路径（已检测 {len(DIRECTORIES)} 个）"

    found.sort()
    return f"目录枚举 ({url}) — 发现 {len(found)}/{len(DIRECTORIES)}:\n" + "\n".join(found)


# ─── 端口扫描 ─────────────────────────────────────────────────────────────────


@registry.tool(
    name="port_scan",
    description="对目标主机进行端口扫描（需要本地安装 nmap）。扫描常用端口或指定端口范围。",
    params={
        "target": {"type": "string", "description": "目标 IP 或域名"},
        "ports": {
            "type": "string",
            "description": "端口范围（如 '1-1000' 或 '80,443,8080'），默认扫描常用端口",
            "required": False,
        },
    },
)
async def port_scan(target: str, ports: str = "21-25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017") -> str:
    target = target.strip()

    def _scan():
        nm = nmap.PortScanner()
        nm.scan(hosts=target, ports=ports, arguments="-sT -T4 --open")
        return nm

    try:
        loop = asyncio.get_event_loop()
        nm = await loop.run_in_executor(None, _scan)
    except nmap.PortScannerError as e:
        return f"nmap 未安装或执行失败: {e}\n请确保系统已安装 nmap (https://nmap.org/download)"
    except Exception as e:
        return f"端口扫描失败: {e}"

    results = []
    for host in nm.all_hosts():
        results.append(f"主机: {host} ({nm[host].hostname()})")
        results.append(f"  状态: {nm[host].state()}")
        for proto in nm[host].all_protocols():
            ports_list = sorted(nm[host][proto].keys())
            for port in ports_list:
                state = nm[host][proto][port]["state"]
                service = nm[host][proto][port].get("name", "unknown")
                results.append(f"  {port}/{proto}  {state}  {service}")

    if not results:
        return f"未发现 {target} 的开放端口"

    return "端口扫描结果:\n" + "\n".join(results)


# ─── WHOIS 查询 ──────────────────────────────────────────────────────────────


@registry.tool(
    name="whois_lookup",
    description="查询目标域名的 WHOIS 注册信息（通过公共 API）",
    params={
        "domain": {"type": "string", "description": "目标域名，如 example.com"},
    },
)
async def whois_lookup(domain: str) -> str:
    domain = domain.strip().rstrip(".")
    api_url = f"https://whois.freeaiapi.xyz/?name={domain}&lang=zh"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return f"WHOIS 查询失败 (HTTP {resp.status_code})"

            data = resp.json()
            if not data:
                return f"未查询到 {domain} 的 WHOIS 信息"

            return f"WHOIS 信息 ({domain}):\n{truncate(json.dumps(data, ensure_ascii=False, indent=2), 4000)}"
    except Exception as e:
        return f"WHOIS 查询失败: {e}"


# ─── HTTP 安全头分析 ──────────────────────────────────────────────────────────


SECURITY_HEADERS = {
    "strict-transport-security": {
        "name": "HSTS (Strict-Transport-Security)",
        "description": "强制 HTTPS，防止降级攻击",
    },
    "content-security-policy": {
        "name": "CSP (Content-Security-Policy)",
        "description": "限制资源加载来源，防止 XSS",
    },
    "x-frame-options": {
        "name": "X-Frame-Options",
        "description": "防止点击劫持（Clickjacking）",
    },
    "x-content-type-options": {
        "name": "X-Content-Type-Options",
        "description": "防止 MIME 类型嗅探",
    },
    "x-xss-protection": {
        "name": "X-XSS-Protection",
        "description": "浏览器 XSS 过滤（已过时但仍常见）",
    },
    "referrer-policy": {
        "name": "Referrer-Policy",
        "description": "控制 Referer 头泄露",
    },
    "permissions-policy": {
        "name": "Permissions-Policy",
        "description": "控制浏览器特性（摄像头、地理位置等）",
    },
    "cross-origin-opener-policy": {
        "name": "COOP (Cross-Origin-Opener-Policy)",
        "description": "跨域窗口隔离",
    },
    "cross-origin-resource-policy": {
        "name": "CORP (Cross-Origin-Resource-Policy)",
        "description": "跨域资源加载策略",
    },
    "cross-origin-embedder-policy": {
        "name": "COEP (Cross-Origin-Embedder-Policy)",
        "description": "跨域嵌入策略",
    },
}


@registry.tool(
    name="header_analysis",
    description="分析目标 URL 的 HTTP 响应头安全配置，检查 HSTS/CSP/X-Frame-Options 等安全头",
    params={
        "url": {"type": "string", "description": "目标 URL"},
    },
)
async def header_analysis(url: str) -> str:
    url = sanitize_url(url)

    try:
        async with httpx.AsyncClient(
            timeout=15.0, verify=False, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 Argus/0.1"},
        ) as client:
            resp = await client.get(url)
    except Exception as e:
        return f"请求失败: {e}"

    headers_lower = {k.lower(): v for k, v in resp.headers.items()}
    lines = [f"目标: {url} (HTTP {resp.status_code})\n"]

    present = []
    missing = []

    for header_key, info in SECURITY_HEADERS.items():
        value = headers_lower.get(header_key)
        if value:
            present.append(f"  ✓ {info['name']}: {value}")
        else:
            missing.append(f"  ✗ {info['name']} — 缺失 ({info['description']})")

    lines.append(f"已配置 ({len(present)}):")
    lines.extend(present)
    lines.append(f"\n缺失 ({len(missing)}):")
    lines.extend(missing)

    # 额外检查：Server 头泄露
    server = headers_lower.get("server")
    if server:
        lines.append(f"\n⚠ Server 头泄露: {server}")

    x_powered = headers_lower.get("x-powered-by")
    if x_powered:
        lines.append(f"⚠ X-Powered-By 头泄露: {x_powered}")

    score = len(present)
    total = len(SECURITY_HEADERS)
    lines.append(f"\n安全头评分: {score}/{total}")

    return "\n".join(lines)
