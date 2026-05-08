"""侦察工具：DNS 查询、子域名枚举、目录爆破、端口扫描、WHOIS、安全头分析。"""

import asyncio
import contextlib
import hashlib
import json
import secrets

import dns.resolver
import httpx
import nmap

from agent.tool_registry import registry
from tools.recon_wordlists import DIRECTORIES, SUBDOMAINS
from utils.logger import log_warning
from utils.rate_limiter import target_slot
from utils.sanitizer import sanitize_url, truncate


def _load_custom_wordlist(kind: str) -> list[str] | None:
    """issue #7：从 config.toml [security] 读取自定义字典文件路径。

    Args:
        kind: 'subdomain_wordlist' 或 'directory_wordlist'

    Returns:
        非空 list 或 None（沿用内置字典）。文件每行一个条目，'#' 起始为注释。
    """
    import os

    try:
        from utils.config import get_section

        path = get_section("security").get(kind, "")
        if not path:
            return None
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            log_warning(f"自定义字典文件不存在: {path}")
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            entries = [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
        return entries or None
    except Exception as e:
        log_warning(f"加载自定义字典 {kind} 失败: {e}")
        return None


def _parse_port_spec(spec: str) -> list[int]:
    """解析 nmap 风格端口表达式 '21-25,80,443' → 排序去重 int list。"""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a), int(b)
                if 1 <= lo <= hi <= 65535:
                    out.update(range(lo, hi + 1))
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= 65535:
                    out.add(p)
            except ValueError:
                continue
    return sorted(out)


async def _tcp_connect_scan(target: str, ports: str, timeout: float = 1.5) -> str:
    """nmap 不可用时的纯 Python 兜底（issue #4）。

    并发 TCP connect，仅判定 open/closed；无服务指纹识别。
    最多扫 1024 个端口，避免被滥用做大范围扫描。
    """
    port_list = _parse_port_spec(ports)
    if not port_list:
        return "端口表达式无法解析"
    if len(port_list) > 1024:
        return f"TCP connect 兜底扫描限 ≤1024 端口（当前 {len(port_list)}）"

    sem = asyncio.Semaphore(50)
    open_ports: list[int] = []

    async def probe(port: int) -> None:
        async with target_slot(target), sem:
            try:
                fut = asyncio.open_connection(target, port)
                _reader, writer = await asyncio.wait_for(fut, timeout=timeout)
                open_ports.append(port)
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            except (TimeoutError, OSError):
                return

    await asyncio.gather(*(probe(p) for p in port_list))
    open_ports.sort()
    if not open_ports:
        return f"未发现 {target} 的开放端口（TCP connect 兜底，{len(port_list)} 端口）"
    lines = [f"  {p}/tcp  open  (nmap 未安装，仅 connect 探测)" for p in open_ports]
    return f"端口扫描结果（TCP connect 兜底）:\n主机: {target}\n" + "\n".join(lines)


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
        [record_type.upper()] if record_type.upper() != "ALL" else ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]
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

    # issue #7：优先用自定义字典
    wordlist = _load_custom_wordlist("subdomain_wordlist") or SUBDOMAINS

    async def check(sub: str) -> str | None:
        # 全局 per-target 限流（#15.4）：防多个子代理叠加击同一目标
        async with target_slot(domain), semaphore:
            return await _resolve_subdomain(sub, domain)

    tasks = [check(sub) for sub in wordlist]
    results = await asyncio.gather(*tasks)
    found = [r for r in results if r is not None]

    if not found:
        return f"未发现 {domain} 的存活子域名（已检测 {len(wordlist)} 个）"

    lines = [f"  {r}" for r in found]
    return f"子域名枚举 ({domain}) — 发现 {len(found)}/{len(wordlist)}:\n" + "\n".join(lines)


# ─── 目录爆破 ─────────────────────────────────────────────────────────────────


# issue #17: 状态码白名单 —— 真正算"发现"的码（30x 默认不算，除非偏离基线）
_DIR_HIT_CODES: frozenset[int] = frozenset({200, 201, 204, 401, 403, 405})


def _body_fingerprint(content: bytes) -> str:
    """取 body 前 4096 字节的 sha1 前 16 位作为指纹（用来识别 Vercel/SPA 统一回首页）。"""
    return hashlib.sha1(content[:4096]).hexdigest()[:16]


async def _probe_baseline(client: httpx.AsyncClient, url: str) -> dict:
    """issue #17: 用 2 条保证不存在的路径打基线，识别 CDN/SPA 全站重定向情况。

    返回 {"codes": set[int], "fps": set[str], "size": int | None, "ok": bool}。
    探测失败 ok=False，调用方退回老逻辑。
    """
    probes = [
        f"/__argus_baseline_{secrets.token_hex(8)}__",
        f"/argus_404_{secrets.token_hex(8)}.dummy",
    ]
    codes: set[int] = set()
    fps: set[str] = set()
    sizes: list[int] = []
    for probe in probes:
        try:
            resp = await client.get(f"{url}{probe}", follow_redirects=False)
        except Exception:
            return {"codes": set(), "fps": set(), "size": None, "ok": False}
        codes.add(resp.status_code)
        fps.add(_body_fingerprint(resp.content))
        sizes.append(len(resp.content))
    return {
        "codes": codes,
        "fps": fps,
        "size": sizes[0] if sizes else None,
        "ok": True,
    }


def _is_baseline_match(resp: httpx.Response, baseline: dict) -> bool:
    """命中基线 = 看起来跟"那条不存在路径"一样的响应，应跳过。"""
    if not baseline.get("ok"):
        return False
    if resp.status_code not in baseline["codes"]:
        return False
    fp = _body_fingerprint(resp.content)
    if fp in baseline["fps"]:
        return True
    base_size = baseline.get("size")
    return bool(base_size is not None and abs(len(resp.content) - base_size) < 32)


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

    # issue #7：优先用自定义字典；条目自动补 / 前缀
    raw_wordlist = _load_custom_wordlist("directory_wordlist") or DIRECTORIES
    wordlist = [p if p.startswith("/") else "/" + p for p in raw_wordlist]

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0 Argus/0.1"},
        ) as client:
            # issue #17：先打基线，识别全站重定向 / SPA 回退
            baseline = await _probe_baseline(client, url)

            async def check_path(path: str) -> None:
                async with target_slot(url), semaphore:
                    target = f"{url}{path}"
                    try:
                        resp = await client.get(target, follow_redirects=False)
                    except Exception:
                        return

                    # 基线匹配 → 假阳性，跳过
                    if _is_baseline_match(resp, baseline):
                        return

                    # baseline 探测失败时退回老逻辑（status<404 全报）
                    if not baseline.get("ok"):
                        if resp.status_code < 404:
                            found.append(f"  [{resp.status_code}] {path}  ({len(resp.content)} bytes)")
                        return

                    # 正常路径：状态码白名单内才算发现
                    if resp.status_code in _DIR_HIT_CODES:
                        found.append(f"  [{resp.status_code}] {path}  ({len(resp.content)} bytes)")

            tasks = [check_path(path) for path in wordlist]
            await asyncio.gather(*tasks)
    except Exception as e:
        return f"目录枚举失败: {e}"

    # issue #17：全站重定向警告头
    header_lines = []
    if baseline.get("ok") and baseline["codes"] and all(300 <= c < 400 for c in baseline["codes"]):
        codes_str = ",".join(str(c) for c in sorted(baseline["codes"]))
        header_lines.append(f"⚠ 目标疑似全站重定向（baseline 状态码 {codes_str}），结果已按基线过滤")
    elif not baseline.get("ok"):
        header_lines.append("⚠ baseline 探测失败，已退回宽松判定（status<404 全报）")

    if not found:
        msg = f"未发现可访问路径（已检测 {len(wordlist)} 个）"
        return ("\n".join(header_lines) + "\n" + msg) if header_lines else msg

    found.sort()
    body = f"目录枚举 ({url}) — 发现 {len(found)}/{len(wordlist)}:\n" + "\n".join(found)
    return ("\n".join(header_lines) + "\n" + body) if header_lines else body


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
async def port_scan(
    target: str, ports: str = "21-25,53,80,110,143,443,993,995,3306,3389,5432,6379,8080,8443,8888,9090,27017"
) -> str:
    target = target.strip()

    def _scan():
        nm = nmap.PortScanner()
        nm.scan(hosts=target, ports=ports, arguments="-sT -T4 --open")
        return nm

    try:
        loop = asyncio.get_event_loop()
        nm = await loop.run_in_executor(None, _scan)
    except nmap.PortScannerError as e:
        # issue #4：nmap 未安装时回退到纯 Python TCP connect 扫描
        log_warning(f"nmap 不可用，回退 TCP connect 扫描: {e}")
        return await _tcp_connect_scan(target, ports)
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
            timeout=15.0,
            verify=False,
            follow_redirects=True,
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
