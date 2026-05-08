"""Stage 3 / Tier-1: 轻量被动漏洞探测。

四个工具：
  - vuln_sqli_timing       SQL 时间盲注（baseline + SLEEP 时延对比）
  - vuln_xss_reflection    XSS 反射探针（probe + 编码检测）
  - vuln_open_redirect     开放重定向（外域 Location 检测）
  - vuln_cors_misconfig    CORS 误配（任意 Origin 回声 + 凭据组合）

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
        "时间盲注探测。对 url 的指定 query 参数注入 SLEEP(3) 系列 payload，"
        "对比与基线请求的时延差是否 ≥2s 且 <8s。仅在已授权目标上可用。"
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
        "XSS 反射探针。注入随机 token 探针并检查响应体是否原样回显（且未被 HTML 编码）。"
        "仅在已授权目标上可用。"
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


# 静态分析器友好：声明工具集合
__all__ = [
    "vuln_cors_misconfig",
    "vuln_open_redirect",
    "vuln_sqli_timing",
    "vuln_xss_reflection",
]
