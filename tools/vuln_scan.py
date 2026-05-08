"""Stage 3 / Tier-1+2: 轻量被动漏洞探测。

六个工具：
  Tier-1（公开页 / 已知模式）：
  - vuln_sqli_timing       SQL 时间盲注（baseline + SLEEP 时延对比）
  - vuln_xss_reflection    XSS 反射探针（probe + 编码检测）
  - vuln_open_redirect     开放重定向（外域 Location 检测）
  - vuln_cors_misconfig    CORS 误配（任意 Origin 回声 + 凭据组合）
  Tier-2（语义参数 / 高交互）：
  - vuln_cmd_injection     OS 命令注入（echo 探针 + 降级 timing 探针双路径）
  - vuln_ssrf              SSRF（file:// + 内网/AWS-GCP metadata + gopher 探针，纯 in-band）

⚠ 法律守护：每个工具调用前都过 ``utils.authorization.is_authorized_target``
门，目标必须在 config 的 allowed_domains 或 credentials.toml 的 targets 内，
否则直接拒绝。risk = block，且审批面板里有 BLOCK_RISK_HINTS 醒目提示。

非授权目标永远不会发出 payload。
"""

from __future__ import annotations

import json
import random
import statistics
import string
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from agent.tool_registry import registry
from utils.authorization import is_authorized_target

_DEFAULT_TIMEOUT = 15.0
_USER_AGENT = "Mozilla/5.0 (Argus-VulnScan)"


def _rand_token(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _set_query_param(url: str, key: str, value: str) -> str:
    """在 URL 上设置 / 替换单个 query 参数（其它参数保持）。"""
    parsed = urlparse(url)
    params: dict[str, str] = {}
    if parsed.query:
        for chunk in parsed.query.split("&"):
            if not chunk:
                continue
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                params[k] = v
            else:
                params[chunk] = ""
    params[key] = value
    new_q = urlencode(params, doseq=False)
    return urlunparse(parsed._replace(query=new_q))


# ──────────────────────────────────────────────────────────────────────────
# vuln_sqli_timing
# ──────────────────────────────────────────────────────────────────────────

_SQLI_PAYLOADS: tuple[str, ...] = (
    "' AND SLEEP(3)-- ",
    "' OR SLEEP(3)-- ",
    '" AND SLEEP(3)-- ',
    "); WAITFOR DELAY '0:0:3'-- ",
)


@registry.tool(
    name="vuln_sqli_timing",
    description=(
        "【作用】时间盲注 SQLi 检测——注入 SLEEP(3) / WAITFOR DELAY '0:0:3' payload 到 url 指定参数，对比"
        "与基线请求时延，≥2s 且 <8s 算命中。返回 JSON: {vulnerable, confidence, baseline_ms, results}。"
        "【关键参数】url（含目标参数，值任意）；param（要测的 query 参数名）；method（GET/POST，默认 GET）；"
        "baseline_samples（基线采样次数，默认 3）。需要 [security].allowed_domains 或 credentials.toml 已配（双路授权）。"
        "【何时用】参数无回显、无错误信息时用。常见可疑点：login id / search keyword / order_by / category_id。"
        "【避坑】(1) “**DVWA SQLi 关卡是 in-band 不是 time-blind**” → 本工具必然 vulnerable=false，要用 http_request 手注 "
        "' OR '1'='1 / ' UNION SELECT 1,2,3-- -；(2) 网络抖动会引发假阳性，工具已用中位数对比缓解；"
        "(3) 单 payload triggered 不算确认 (confidence=low)，要 ≥3/4 才 high；"
        "(4) 授权门拒绝是 feature 不是 bug，不要建议用户改 allowed_domains 绕过。"
    ),
    params={
        "url": {"type": "string", "description": "完整 URL，含目标参数（值任意）"},
        "param": {"type": "string", "description": "要测试注入的 query 参数名"},
        "method": {
            "type": "string",
            "description": "GET / POST，默认 GET",
            "required": False,
        },
        "baseline_samples": {
            "type": "string",
            "description": "基线采样次数，默认 3",
            "required": False,
        },
    },
)
async def vuln_sqli_timing(
    url: str,
    param: str,
    method: str = "GET",
    baseline_samples: str = "3",
) -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_sqli_timing 拒绝执行：\n{reason}"

    try:
        n = max(1, min(5, int(baseline_samples)))
    except ValueError:
        n = 3

    method = (method or "GET").upper()
    headers = {"User-Agent": _USER_AGENT}

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT, follow_redirects=False, verify=False
    ) as client:
        # 基线（无 payload，正常值 = 1）
        baseline_url = _set_query_param(url, param, "1")
        baseline_times: list[float] = []
        for _ in range(n):
            t = await _measure(client, method, baseline_url, headers)
            if t is None:
                return f"vuln_sqli_timing 失败：基线请求 {baseline_url!r} 网络异常"
            baseline_times.append(t)
        m_base = statistics.median(baseline_times)

        # payload 探测
        payload_results: list[dict[str, Any]] = []
        triggered = 0
        for payload in _SQLI_PAYLOADS:
            test_url = _set_query_param(url, param, payload)
            t = await _measure(client, method, test_url, headers)
            if t is None:
                payload_results.append({"payload": payload, "ms": None, "triggered": False})
                continue
            delta = t - m_base
            # 命中条件：≥2s（说明 SLEEP 生效），<8s（避免把超时网络也认作命中）
            is_triggered = 2.0 <= delta < 8.0
            if is_triggered:
                triggered += 1
            payload_results.append(
                {
                    "payload": payload,
                    "ms": round(t * 1000),
                    "delta_ms": round(delta * 1000),
                    "triggered": is_triggered,
                }
            )

    # confidence
    if triggered >= 3:
        confidence = "high"
    elif triggered >= 1:
        confidence = "medium" if triggered >= 2 else "low"
    else:
        confidence = "none"

    summary = {
        "vulnerable": triggered >= 1,
        "confidence": confidence,
        "param": param,
        "baseline_ms": round(m_base * 1000),
        "triggered_count": triggered,
        "total_payloads": len(_SQLI_PAYLOADS),
        "results": payload_results,
        "authorization": reason,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


async def _measure(
    client: httpx.AsyncClient, method: str, url: str, headers: dict
) -> float | None:
    """发一次请求并返回耗时（秒）。任何异常返 None。"""
    import time

    try:
        t0 = time.monotonic()
        resp = await client.request(method, url, headers=headers)
        # 强制读完响应体
        await resp.aread()
        return time.monotonic() - t0
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# vuln_xss_reflection
# ──────────────────────────────────────────────────────────────────────────


@registry.tool(
    name="vuln_xss_reflection",
    description=(
        "【作用】反射型 XSS 检测——注入随机 <argus_xss_probe_*> 探针到指定参数，检查响应体是否原样反射且未"
        "HTML 转义。返回 JSON: {vulnerable, reflected, encoded, context, status}。"
        "【关键参数】url（含目标参数）；param（要探测的 query 参数名）；method。需要 allowed_domains 或 credentials 双路授权。"
        "【何时用】怀疑 search / comment / echo 类参数无过滤；优先在登录后受保护页面跑（公开页常见 WAF 拦）。"
        "【避坑】(1) “**encoded=true 不是漏洞**”——HTML 转义是正确防御，只有 reflected=true 且 encoded=false 才 vulnerable=true；"
        "(2) DOM XSS / stored XSS 本工具测不出，要用浏览器渲染 + 手测；"
        "(3) 命中后看 context 字段判断注入位置（attribute / script / html）才能写真实 PoC；"
        "(4) 一次只测一个参数，多参数要多次调用。"
    ),
    params={
        "url": {"type": "string", "description": "完整 URL"},
        "param": {"type": "string", "description": "要探测的 query 参数名"},
        "method": {
            "type": "string",
            "description": "GET / POST，默认 GET",
            "required": False,
        },
    },
)
async def vuln_xss_reflection(url: str, param: str, method: str = "GET") -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_xss_reflection 拒绝执行：\n{reason}"

    method = (method or "GET").upper()
    token = _rand_token()
    raw_probe = f"<argus_xss_probe_{token}>"
    encoded_probe = f"&lt;argus_xss_probe_{token}&gt;"

    test_url = _set_query_param(url, param, raw_probe)
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT, follow_redirects=True, verify=False
        ) as client:
            resp = await client.request(method, test_url, headers=headers)
            body = resp.text
    except Exception as e:
        return f"vuln_xss_reflection 失败：网络异常 {type(e).__name__}: {e}"

    raw_in_body = raw_probe in body
    encoded_in_body = encoded_probe in body
    # 未编码反射 = 真实 XSS 风险
    vulnerable = raw_in_body and not encoded_in_body

    # 抠取 context（命中位置 ±60 字符）
    context = ""
    if raw_in_body:
        idx = body.find(raw_probe)
        ctx_s = max(0, idx - 60)
        ctx_e = min(len(body), idx + len(raw_probe) + 60)
        context = body[ctx_s:ctx_e].replace("\n", "\\n")

    summary = {
        "vulnerable": vulnerable,
        "reflected": raw_in_body,
        "encoded": encoded_in_body,
        "param": param,
        "probe": raw_probe,
        "context": context[:240],
        "status": resp.status_code,
        "authorization": reason,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# vuln_open_redirect
# ──────────────────────────────────────────────────────────────────────────

_REDIRECT_PROBES: tuple[str, ...] = (
    "//argus-redirect-probe.example",
    "https://argus-redirect-probe.example",
    "/\\argus-redirect-probe.example",
)


@registry.tool(
    name="vuln_open_redirect",
    description=(
        "开放重定向探测。对 url 的指定参数注入外域 URL，检查响应 Location 头是否跳到外域。"
        "仅在已授权目标上可用。"
    ),
    params={
        "url": {"type": "string", "description": "完整 URL"},
        "param": {
            "type": "string",
            "description": "重定向参数名，常见: next / url / redirect / return / target",
        },
    },
)
async def vuln_open_redirect(url: str, param: str) -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_open_redirect 拒绝执行：\n{reason}"

    headers = {"User-Agent": _USER_AGENT}
    findings: list[dict[str, Any]] = []
    vulnerable = False

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT, follow_redirects=False, verify=False
    ) as client:
        for probe in _REDIRECT_PROBES:
            test_url = _set_query_param(url, param, probe)
            try:
                resp = await client.request("GET", test_url, headers=headers)
            except Exception as e:
                findings.append({"probe": probe, "error": f"{type(e).__name__}: {e}"})
                continue
            location = resp.headers.get("location") or resp.headers.get("Location") or ""
            # 命中：3xx 重定向 + Location 含 probe 域
            is_hit = 300 <= resp.status_code < 400 and "argus-redirect-probe.example" in location
            if is_hit:
                vulnerable = True
            findings.append(
                {
                    "probe": probe,
                    "status": resp.status_code,
                    "location": location[:200],
                    "vulnerable": is_hit,
                }
            )

    summary = {
        "vulnerable": vulnerable,
        "param": param,
        "findings": findings,
        "authorization": reason,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# vuln_cors_misconfig
# ──────────────────────────────────────────────────────────────────────────

_PROBE_ORIGIN = "https://argus-cors-probe.example"


@registry.tool(
    name="vuln_cors_misconfig",
    description=(
        "CORS 误配探测。发送任意 Origin 头，检查响应 Access-Control-Allow-Origin 是否"
        "回声任意源；若同时 Access-Control-Allow-Credentials: true 则严重。"
        "仅在已授权目标上可用。"
    ),
    params={
        "url": {"type": "string", "description": "目标 URL（通常是 API 端点）"},
    },
)
async def vuln_cors_misconfig(url: str) -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_cors_misconfig 拒绝执行：\n{reason}"

    headers = {"User-Agent": _USER_AGENT, "Origin": _PROBE_ORIGIN}
    try:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT, follow_redirects=True, verify=False
        ) as client:
            resp = await client.request("GET", url, headers=headers)
    except Exception as e:
        return f"vuln_cors_misconfig 失败：网络异常 {type(e).__name__}: {e}"

    # 大小写不敏感找 ACAO / ACAC
    acao = ""
    acac = ""
    for k, v in resp.headers.items():
        kl = k.lower()
        if kl == "access-control-allow-origin":
            acao = v
        elif kl == "access-control-allow-credentials":
            acac = v

    # 任意 Origin 回声（命中 probe 域）= 高危信号；ACAO: * 是通配符，单独低档
    reflects_arbitrary = bool(acao) and acao.strip() == _PROBE_ORIGIN
    credentials_allowed = acac.strip().lower() == "true"
    is_wildcard = acao.strip() == "*"

    if reflects_arbitrary and credentials_allowed:
        severity = "high"
        risk = "任意 Origin 回声 + 允许凭据 — 跨源泄漏 cookies/凭据"
    elif reflects_arbitrary:
        severity = "medium"
        risk = "任意 Origin 回声（无凭据）— 可读取响应数据"
    elif is_wildcard:
        severity = "low"
        risk = "ACAO: * — 通配符开放，需评估接口敏感度"
    else:
        severity = "none"
        risk = "未发现明显 CORS 误配"

    summary = {
        "vulnerable": reflects_arbitrary or is_wildcard,
        "severity": severity,
        "risk": risk,
        "probe_origin": _PROBE_ORIGIN,
        "acao": acao,
        "acac": acac,
        "status": resp.status_code,
        "authorization": reason,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# vuln_cmd_injection (Tier-2)
# 双路径：先 echo 探针（快），未命中再降级 timing 探针（慢但全面）
# ──────────────────────────────────────────────────────────────────────────

# echo 探针：跨 OS 兼容（POSIX shell + cmd.exe）
# 注入后期望响应体回显 argus_cmdi_<token>，证明命令实际执行了 echo
_CMDI_ECHO_PAYLOADS: tuple[str, ...] = (
    ";echo argus_cmdi_{token};",
    "|echo argus_cmdi_{token}",
    "&& echo argus_cmdi_{token}",
    "`echo argus_cmdi_{token}`",
    "$(echo argus_cmdi_{token})",
)

# timing 探针：3-5s 延迟，跨 OS（sleep / timeout / ping）
_CMDI_TIMING_PAYLOADS: tuple[str, ...] = (
    ";sleep 5",
    "|sleep 5",
    "&& sleep 5",
    "`sleep 5`",
    "& timeout /t 5 /nobreak",  # Windows cmd
    "& ping -n 6 127.0.0.1",  # Windows fallback
)

_CMDI_TIMING_HIT_LOWER = 4.0  # delta_s ≥ 4s 算命中（payload 设计 5s）
_CMDI_TIMING_HIT_UPPER = 10.0  # < 10s 排除网络抖动 / 超时


@registry.tool(
    name="vuln_cmd_injection",
    description=(
        "【作用】OS 命令注入检测——双路径策略。先注入 ;echo argus_cmdi_<token>; 系列 payload 看响应体是否"
        "回显 token（快路径，~3s）；不命中则降级注入 ;sleep 5 系列 timing payload，对比基线时延 4-10s 区间"
        "判命中（慢路径，~30s）。返回 JSON: {vulnerable, confidence, path, param, echo_results, timing_results}。"
        "【关键参数】url（含目标参数）；param（要测的 query 参数名）；method（GET/POST，默认 GET）。"
        "需要 [security].allowed_domains 或 credentials.toml 已配（双路授权）。"
        "【何时用】参数像 host / cmd / file / target / domain（功能描述含 'ping' / 'lookup' / 'convert'）；"
        "Web 管理面板的 'system tools' 类页面；任何把用户输入拼到 shell 的 CGI / API。"
        "【避坑】(1) **path=echo 是 high confidence**（明确证明命令执行）；**path=timing 是 medium**（可能是数据库/网络抖动）；"
        "(2) WAF 会 strip 分号 / 反引号 → 全部 payload 都被拒绝时不代表无漏洞，看 status 是否一致 403/406；"
        "(3) Windows cmd.exe 不支持 ';' 分隔，要靠 '&' 和 'timeout /t' payload；"
        "(4) 命中后**不要再继续注入更危险的 payload**（rm/del/wget），合规研究只到 PoC 即止；"
        "(5) 同一参数 echo 不命中也别立刻放弃，timing 路径有时是唯一证据（盲执行场景）。"
    ),
    params={
        "url": {"type": "string", "description": "完整 URL，含目标参数（值任意）"},
        "param": {"type": "string", "description": "要测试注入的 query 参数名"},
        "method": {
            "type": "string",
            "description": "GET / POST，默认 GET",
            "required": False,
        },
    },
)
async def vuln_cmd_injection(url: str, param: str, method: str = "GET") -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_cmd_injection 拒绝执行：\n{reason}"

    method = (method or "GET").upper()
    headers = {"User-Agent": _USER_AGENT}
    token = _rand_token(10)

    echo_results: list[dict[str, Any]] = []
    timing_results: list[dict[str, Any]] = []
    echo_hits = 0

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT, follow_redirects=True, verify=False
    ) as client:
        # ── 路径 1：echo 探针（快） ──
        marker = f"argus_cmdi_{token}"
        for payload_tpl in _CMDI_ECHO_PAYLOADS:
            payload = payload_tpl.format(token=token)
            test_url = _set_query_param(url, param, payload)
            try:
                resp = await client.request(method, test_url, headers=headers)
                body = resp.text
            except Exception as e:
                echo_results.append(
                    {"payload": payload, "error": f"{type(e).__name__}: {e}", "marker_hit": False}
                )
                continue
            hit = marker in body
            if hit:
                echo_hits += 1
            echo_results.append(
                {
                    "payload": payload,
                    "status": resp.status_code,
                    "marker_hit": hit,
                }
            )

        # ── 路径 2：timing 探针（慢，仅 echo 全部未命中时跑） ──
        if echo_hits == 0:
            # 基线：用合法值 1（与其它 vuln_* 一致）
            baseline_url = _set_query_param(url, param, "1")
            baseline_times: list[float] = []
            for _ in range(3):
                t = await _measure(client, method, baseline_url, headers)
                if t is not None:
                    baseline_times.append(t)
            if baseline_times:
                m_base = statistics.median(baseline_times)
                for payload in _CMDI_TIMING_PAYLOADS:
                    test_url = _set_query_param(url, param, payload)
                    t = await _measure(client, method, test_url, headers)
                    if t is None:
                        timing_results.append({"payload": payload, "ms": None, "triggered": False})
                        continue
                    delta = t - m_base
                    triggered = _CMDI_TIMING_HIT_LOWER <= delta < _CMDI_TIMING_HIT_UPPER
                    timing_results.append(
                        {
                            "payload": payload,
                            "ms": round(t * 1000),
                            "delta_ms": round(delta * 1000),
                            "triggered": triggered,
                        }
                    )

    timing_hits = sum(1 for r in timing_results if r.get("triggered"))

    if echo_hits >= 1:
        path = "echo"
        vulnerable = True
        confidence = "high"
    elif timing_hits >= 2:
        path = "timing"
        vulnerable = True
        confidence = "medium"
    elif timing_hits == 1:
        path = "timing"
        vulnerable = True
        confidence = "low"
    else:
        path = "none"
        vulnerable = False
        confidence = "none"

    summary: dict[str, Any] = {
        "vulnerable": vulnerable,
        "confidence": confidence,
        "path": path,
        "param": param,
        "echo_hits": echo_hits,
        "timing_hits": timing_hits,
        "echo_results": echo_results,
        "authorization": reason,
    }
    if timing_results:
        summary["timing_results"] = timing_results
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# vuln_ssrf (Tier-2)
# 纯 in-band：内网指针 + 协议绕过 + 响应差异分级
# ──────────────────────────────────────────────────────────────────────────

# (probe_url, kind, marker_substr) — marker 命中即 high confidence
# marker=None 表示靠状态/时延差异判（lower confidence）
_SSRF_PROBES: tuple[tuple[str, str, str | None], ...] = (
    ("file:///etc/passwd", "linux_passwd", "root:x:0"),
    ("file:///c:/windows/win.ini", "win_ini", "[fonts]"),
    ("http://127.0.0.1:22", "localhost_ssh", None),
    ("http://169.254.169.254/latest/meta-data/", "aws_metadata", "ami-id"),
    ("http://metadata.google.internal/computeMetadata/v1/", "gcp_metadata", "Metadata-Flavor"),
    ("gopher://127.0.0.1:6379/_INFO", "gopher_redis", None),
)

_SSRF_BASELINE_VALUE = "https://example.com/"  # 合法外域作 baseline
_SSRF_LATENCY_DIFF_S = 2.0  # delta ≥ 2s 算 latency suspect
_SSRF_STATUS_DIFF_OK = 200  # baseline 期望 200 / probe 显著不同算 status suspect


@registry.tool(
    name="vuln_ssrf",
    description=(
        "【作用】SSRF（服务器端请求伪造）in-band 检测——把内网指针 / 协议绕过 payload 注入到 url-like 参数，"
        "对比 baseline 响应判定服务端是否真的发起了请求。6 类探针：file:///etc/passwd, file:///c:/windows/win.ini, "
        "http://127.0.0.1:22, AWS metadata 169.254.169.254, GCP metadata, gopher://127.0.0.1:6379。"
        "返回 JSON: {vulnerable, severity, baseline, findings[]}。**不依赖外部 OOB 服务**（无 Burp Collaborator 类）。"
        "【关键参数】url（含目标参数）；param（参数名，常见 url/fetch_url/image_url/callback/next/redirect/import）。"
        "需要 [security].allowed_domains 或 credentials.toml 已配（双路授权）。"
        "【何时用】(1) 参数明显是 URL（'image_url' / 'webhook' / 'callback'）；(2) 功能涉及'抓取远程资源'（导入、预览、缩略图）；"
        "(3) 内部服务发现 / 内网横移评估（已合法授权时）。"
        "【避坑】(1) **severity=high 仅当 marker_hit=true**（如响应含 'root:x:0' 才能确认读到 /etc/passwd）；"
        "(2) status 差异 / latency 差异 = medium/low，可能是合法过滤而非漏洞——需要进一步验证；"
        "(3) 大多数现代框架默认禁 file:// 协议；这种 probe 失败不代表整体 vulnerable=false；"
        "(4) AWS/GCP metadata probe 仅在云上目标有意义，自建机房会全 timeout；"
        "(5) 命中后**不要继续读敏感文件**（/etc/shadow / private keys），PoC 即止。"
    ),
    params={
        "url": {"type": "string", "description": "完整 URL，含目标参数"},
        "param": {
            "type": "string",
            "description": "要探测的参数名，常见: url / fetch_url / image_url / callback / next / redirect / import",
        },
    },
)
async def vuln_ssrf(url: str, param: str) -> str:
    ok, reason = is_authorized_target(url)
    if not ok:
        return f"vuln_ssrf 拒绝执行：\n{reason}"

    headers = {"User-Agent": _USER_AGENT}
    findings: list[dict[str, Any]] = []
    overall_severity = "none"
    severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT, follow_redirects=False, verify=False
    ) as client:
        # 基线：合法外域 URL，期望成功代理或预期错误
        import time

        baseline_url = _set_query_param(url, param, _SSRF_BASELINE_VALUE)
        baseline: dict[str, Any] = {"status": None, "size": None, "latency_ms": None}
        try:
            t0 = time.monotonic()
            resp = await client.request("GET", baseline_url, headers=headers)
            content = await resp.aread()
            baseline["status"] = resp.status_code
            baseline["size"] = len(content)
            baseline["latency_ms"] = round((time.monotonic() - t0) * 1000)
        except Exception as e:
            baseline["error"] = f"{type(e).__name__}: {e}"

        # 逐个 probe
        for probe_url, kind, marker in _SSRF_PROBES:
            test_url = _set_query_param(url, param, probe_url)
            entry: dict[str, Any] = {"probe": probe_url, "kind": kind}
            try:
                t0 = time.monotonic()
                resp = await client.request("GET", test_url, headers=headers)
                content = await resp.aread()
                latency_ms = round((time.monotonic() - t0) * 1000)
                body_text = ""
                try:
                    body_text = content.decode("utf-8", errors="replace")
                except Exception:
                    body_text = ""

                entry["status"] = resp.status_code
                entry["size"] = len(content)
                entry["latency_ms"] = latency_ms

                # 1. marker 命中 = high
                marker_hit = bool(marker and marker in body_text)
                entry["marker_hit"] = marker_hit
                if marker_hit:
                    entry["severity"] = "high"
                # 2. status 显著差异 = medium
                elif (
                    baseline["status"] is not None
                    and resp.status_code != baseline["status"]
                    and resp.status_code in (500, 502, 504)
                ):
                    entry["severity"] = "medium"
                # 3. latency 差异 = low（可能服务端真的去请求了内网）
                elif (
                    baseline["latency_ms"] is not None
                    and (latency_ms - baseline["latency_ms"]) / 1000.0 >= _SSRF_LATENCY_DIFF_S
                ):
                    entry["severity"] = "low"
                else:
                    entry["severity"] = "none"
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                entry["severity"] = "none"

            if severity_rank[entry["severity"]] > severity_rank[overall_severity]:
                overall_severity = entry["severity"]
            findings.append(entry)

    summary = {
        "vulnerable": overall_severity in ("high", "medium"),
        "severity": overall_severity,
        "param": param,
        "baseline": baseline,
        "findings": findings,
        "authorization": reason,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


# 静态分析器友好：声明工具集合
__all__ = [
    "vuln_cmd_injection",
    "vuln_cors_misconfig",
    "vuln_open_redirect",
    "vuln_sqli_timing",
    "vuln_ssrf",
    "vuln_xss_reflection",
]
