"""issue #16: RDAP（Registration Data Access Protocol）客户端 — WHOIS 替代。

RDAP 是 ICANN 的开放标准，所有 gTLD 注册局必须提供，免费、不需要 API key。

工作流程：
  1. bootstrap：从 https://data.iana.org/rdap/dns.json 拉 TLD → RDAP 服务器映射
     缓存到 ~/.argus/cache/rdap_bootstrap.json，TTL 7 天
  2. 查询：GET <rdap_server>/domain/<domain>，标准 JSON
  3. 解析：把 RDAP JSON 抠成易读字段（registrar / registrant / 创建时间 / ...）

参考：
  - https://datatracker.ietf.org/doc/html/rfc7483 (RDAP JSON Responses)
  - https://datatracker.ietf.org/doc/html/rfc7484 (Bootstrap)
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_CACHE_TTL_SECONDS = 7 * 24 * 3600


def _bootstrap_cache_path() -> Path:
    home = Path.home() / ".argus" / "cache"
    home.mkdir(parents=True, exist_ok=True)
    return home / "rdap_bootstrap.json"


def _load_cached_bootstrap() -> dict | None:
    """读本地缓存；超过 TTL 返 None。"""
    p = _bootstrap_cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = data.get("_argus_cached_at", 0)
        if time.time() - ts > _CACHE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _save_cached_bootstrap(data: dict) -> None:
    p = _bootstrap_cache_path()
    payload = dict(data)
    payload["_argus_cached_at"] = time.time()
    with contextlib.suppress(Exception):
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


async def fetch_bootstrap(client: httpx.AsyncClient) -> dict | None:
    """拿 IANA bootstrap 表（带本地缓存）。失败返 None。"""
    cached = _load_cached_bootstrap()
    if cached:
        return cached
    try:
        resp = await client.get(_BOOTSTRAP_URL, timeout=10.0)
        if resp.status_code != 200:
            return None
        data = resp.json()
        _save_cached_bootstrap(data)
        return data
    except Exception:
        return None


def find_rdap_server(bootstrap: dict, tld: str) -> str | None:
    """在 bootstrap services 列表里找 TLD 对应的 RDAP base URL。

    RFC 7484 services 结构：[ [ [tld, ...], [server_url, ...] ], ... ]
    """
    tld = tld.lower().lstrip(".")
    services = bootstrap.get("services") or []
    for entry in services:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        tlds, servers = entry
        if not isinstance(tlds, list) or not isinstance(servers, list):
            continue
        if tld in [t.lower() for t in tlds] and servers:
            # 取第一个 https 服务器，结尾不带 /
            for s in servers:
                if isinstance(s, str) and s.startswith("https://"):
                    return s.rstrip("/")
            return str(servers[0]).rstrip("/")
    return None


def _extract_vcard_field(vcard: list, key: str) -> str | None:
    """从 jCard (vcard array) 找指定字段，比如 'fn' / 'org' / 'email'。

    jCard 结构：["vcard", [ [name, params, type, value], ... ]]
    """
    if not isinstance(vcard, list) or len(vcard) < 2:
        return None
    items = vcard[1]
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, list) and len(item) >= 4 and item[0] == key:
            v = item[3]
            return v if isinstance(v, str) else str(v)
    return None


def parse_rdap_response(data: dict) -> dict:
    """把 RDAP JSON 抠成简化的人类可读字段集合。

    返回包含可能 None 的字段：domain / status / registrar / registrant_org /
    creation / expiration / last_changed / nameservers。
    """
    out: dict[str, Any] = {
        "domain": data.get("ldhName") or data.get("handle"),
        "status": data.get("status") or [],
    }

    # 事件：注册 / 到期 / 最后修改
    for evt in data.get("events") or []:
        action = evt.get("eventAction")
        date = evt.get("eventDate")
        if action == "registration":
            out["creation"] = date
        elif action == "expiration":
            out["expiration"] = date
        elif action == "last changed":
            out["last_changed"] = date

    # entities：注册商 / 注册人
    for ent in data.get("entities") or []:
        roles = ent.get("roles") or []
        vcard = ent.get("vcardArray")
        if "registrar" in roles:
            name = _extract_vcard_field(vcard, "fn") if vcard else None
            out["registrar"] = name or ent.get("handle")
        if "registrant" in roles:
            org = _extract_vcard_field(vcard, "org") if vcard else None
            fn = _extract_vcard_field(vcard, "fn") if vcard else None
            out["registrant_org"] = org or fn or ent.get("handle")

    # 名称服务器
    ns = []
    for n in data.get("nameservers") or []:
        ldh = n.get("ldhName")
        if ldh:
            ns.append(ldh)
    if ns:
        out["nameservers"] = ns

    return out


def format_rdap_summary(parsed: dict) -> str:
    """把 parse_rdap_response 输出 pretty-print 成展示用文本。"""
    lines = []
    if parsed.get("_queried_as") and parsed.get("_resolved_via"):
        lines.append(
            f"  (子域查询 {parsed['_queried_as']} 回退到注册域 {parsed['_resolved_via']})"
        )
    if parsed.get("domain"):
        lines.append(f"  域名:        {parsed['domain']}")
    if parsed.get("registrar"):
        lines.append(f"  注册商:      {parsed['registrar']}")
    if parsed.get("registrant_org"):
        lines.append(f"  注册人:      {parsed['registrant_org']}")
    if parsed.get("creation"):
        lines.append(f"  创建时间:    {parsed['creation']}")
    if parsed.get("expiration"):
        lines.append(f"  到期时间:    {parsed['expiration']}")
    if parsed.get("last_changed"):
        lines.append(f"  最后修改:    {parsed['last_changed']}")
    if parsed.get("status"):
        lines.append(f"  状态:        {', '.join(parsed['status'])}")
    if parsed.get("nameservers"):
        ns_lines = "\n".join(f"               {ns}" for ns in parsed["nameservers"])
        lines.append(f"  名称服务器:\n{ns_lines}")
    return "\n".join(lines) if lines else "(无可解析字段)"


def _registrable_candidates(domain: str) -> list[str]:
    """生成尝试链：原样 -> 最后 2 段 -> 最后 3 段。

    RDAP 只认可注册域（eTLD+1）；子域名（如 a.b.example.com）需要退到 `example.com`。
    没接 PSL，所以按"去掉一级 label"的贪婪回退，足以覆盖 .com/.org/.net 等常见 gTLD；
    对 .co.uk 这类双段 TLD 会在第二轮命中。
    """
    domain = domain.strip().rstrip(".").lower()
    if "." not in domain:
        return []
    labels = domain.split(".")
    seen: list[str] = []
    # 从最长到最短尝试；RDAP 服务端对未注册的子域返 404，对父域会返 200
    for cut in range(len(labels) - 1):
        candidate = ".".join(labels[cut:])
        if candidate not in seen and "." in candidate:
            seen.append(candidate)
    return seen


async def _try_lookup_one(client: httpx.AsyncClient, bootstrap: dict, domain: str) -> dict | None:
    tld = domain.rsplit(".", 1)[-1]
    server = find_rdap_server(bootstrap, tld)
    if not server:
        return None
    try:
        resp = await client.get(f"{server}/domain/{domain}", timeout=10.0)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return parse_rdap_response(resp.json())
    except Exception:
        return None


async def lookup_rdap(domain: str, *, client: httpx.AsyncClient | None = None) -> dict | None:
    """对外主入口：拿到 RDAP 解析结果。失败返 None。

    支持子域名：先试原样，失败按 label 逐级回退到注册域。
    """
    candidates = _registrable_candidates(domain)
    if not candidates:
        return None

    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)

    try:
        bootstrap = await fetch_bootstrap(client)
        if not bootstrap:
            return None
        for candidate in candidates:
            result = await _try_lookup_one(client, bootstrap, candidate)
            if result:
                # 查子域命中父域时，保留输入子域在 domain 字段前面作提示
                original = candidates[0]
                if candidate != original:
                    result["_queried_as"] = original
                    result["_resolved_via"] = candidate
                return result
        return None
    finally:
        if own_client:
            await client.aclose()
