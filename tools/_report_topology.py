"""Day2-2: 从 dns/subdomains/open_ports 文本里抽取信息，渲染 ASCII 拓扑图。

零 LLM、纯字符串扫描。设计目标：让用户瞬间看清"这个目标长啥样"。

输出形如：

```
example.com
├── NS:   elliott.ns.cloudflare.com
├── NS:   hera.ns.cloudflare.com
├── A:    198.18.0.4
│   ├── :80/tcp   http   (open)
│   └── :443/tcp  https  (open)
├── MX:   alt1.aspmx.l.google.com
└── 子域: 1998 项被 wildcard 过滤 ⚠
```
"""

from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────────────────
# DNS 解析
# ──────────────────────────────────────────────────────────────────────────


_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}\b", re.IGNORECASE)
# 域名（含至少一个点；末尾可有点；只取 ascii 字母数字 - .）
_HOSTNAME = re.compile(r"\b(?:[a-z0-9][a-z0-9-]{0,62}\.)+[a-z]{2,}\.?", re.IGNORECASE)


def _extract_dns_records(dns_text: str) -> dict[str, list[str]]:
    """从 dns_lookup 文本里抽 A/AAAA/MX/NS/CNAME 列表。

    每条记录用类型对应的严格正则识别：
      - A:    IPv4 格式
      - AAAA: IPv6 格式（含 ':'）
      - MX/NS/CNAME: 域名格式（至少 a.b 形式）

    不再误把"无记录""IPv6"这种说明性中文当成值。
    """
    records: dict[str, list[str]] = {"A": [], "AAAA": [], "MX": [], "NS": [], "CNAME": []}
    if not dns_text:
        return records

    type_patterns = {
        "A": _IPV4,
        "AAAA": _IPV6,
        "NS": _HOSTNAME,
        "MX": _HOSTNAME,
        "CNAME": _HOSTNAME,
    }

    for line in dns_text.splitlines():
        stripped = line.strip()
        # 去除 markdown 噪声字符
        clean = stripped
        for ch in ("|", "*", "•", "·", "`"):
            clean = clean.replace(ch, " ")
        clean = clean.strip()
        if not clean:
            continue

        # 找出该行声明的 record type（最长前缀优先：AAAA > A 等）
        upper = clean.upper()
        rec_type = None
        for rt in ("AAAA", "CNAME", "NAME", "A", "MX", "NS"):
            # 行开头出现 rec_type，后接 : / 空格 / 表格分隔
            if re.match(rf"^{rt}\b", upper) or re.search(rf"\b{rt}\b\s*[:：]", upper):
                rec_type = "A" if rt == "NAME" else rt
                if rec_type not in records:
                    rec_type = None
                else:
                    break
        if not rec_type:
            continue

        pattern = type_patterns.get(rec_type)
        if not pattern:
            continue

        # 只去掉行首的 type 关键字（防止把 hostname 中的 'NS' / 'A' 等也擦掉）
        value_part = re.sub(rf"^\s*{rec_type}\b\s*[:：]?\s*", "", clean, count=1, flags=re.IGNORECASE)
        for match in pattern.finditer(value_part):
            item = match.group(0).rstrip(".").strip()
            if not item or item in records[rec_type]:
                continue
            # 防止把 "0" / "0." 当 IP；防止把 cf 自己当 hostname 收进 NS 时漏匹配
            records[rec_type].append(item)

    return records


# ──────────────────────────────────────────────────────────────────────────
# 端口
# ──────────────────────────────────────────────────────────────────────────


_PORT_SERVICE_HINT = {
    "21": "ftp",
    "22": "ssh",
    "23": "telnet",
    "25": "smtp",
    "53": "dns",
    "80": "http",
    "110": "pop3",
    "143": "imap",
    "443": "https",
    "993": "imaps",
    "995": "pop3s",
    "3306": "mysql",
    "3389": "rdp",
    "5432": "postgres",
    "6379": "redis",
    "8080": "http-alt",
    "8443": "https-alt",
    "8888": "http-alt",
    "9090": "prometheus",
    "27017": "mongodb",
}


def _extract_open_ports(port_text: str) -> list[tuple[str, str]]:
    """返回 [(port, service), ...] 列表。"""
    if not port_text:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    # 注意：service 字段必须和 'open' 在同一行（[^\S\n] 匹配空格但不匹配 \n）
    for match in re.finditer(
        r"\b(\d+)/(tcp|udp)[^\S\n]+(?:open|status:?[^\S\n]*open)\b(?:[^\S\n]+(\S+))?",
        port_text,
        re.IGNORECASE,
    ):
        port = match.group(1)
        if port in seen:
            continue
        seen.add(port)
        service = match.group(3) or _PORT_SERVICE_HINT.get(port, "?")
        out.append((port, service))
    out.sort(key=lambda x: int(x[0]))
    return out


# ──────────────────────────────────────────────────────────────────────────
# 子域计数 / wildcard 提示
# ──────────────────────────────────────────────────────────────────────────


def _summarize_subdomains(sub_text: str) -> dict:
    """提取 wildcard 标志、过滤数、命中数。"""
    if not sub_text:
        return {"wildcard": False, "filtered": 0, "found": 0}
    info = {"wildcard": False, "filtered": 0, "found": 0}
    if "wildcard" in sub_text.lower() or "wildcard DNS" in sub_text:
        info["wildcard"] = True
    fil_match = re.search(r"已过滤\s*(\d+)\s*条", sub_text)
    if fil_match:
        info["filtered"] = int(fil_match.group(1))
    found_match = re.search(r"发现\s*(\d+)\s*/\s*(\d+)", sub_text)
    if found_match:
        info["found"] = int(found_match.group(1))
    return info


# ──────────────────────────────────────────────────────────────────────────
# 渲染
# ──────────────────────────────────────────────────────────────────────────


def build_topology(
    target: str,
    dns_info: str = "",
    subdomains: str = "",
    open_ports: str = "",
) -> str:
    """生成拓扑图 markdown 块；信息全无时返回空串。"""
    records = _extract_dns_records(dns_info)
    ports = _extract_open_ports(open_ports)
    sub_info = _summarize_subdomains(subdomains)

    has_any = (
        any(records[k] for k in records)
        or ports
        or sub_info["found"]
        or sub_info["filtered"]
    )
    if not has_any:
        return ""

    # 收集要渲染的"分支"
    branches: list[tuple[str, str]] = []
    for ns in records["NS"]:
        branches.append(("NS", ns))
    for a in records["A"]:
        branches.append(("A", a))
    for aaaa in records["AAAA"]:
        branches.append(("AAAA", aaaa))
    for mx in records["MX"]:
        branches.append(("MX", mx))
    for cname in records["CNAME"]:
        branches.append(("CNAME", cname))

    # 子域汇总
    sub_summary = ""
    if sub_info["wildcard"] and sub_info["filtered"]:
        sub_summary = f"{sub_info['filtered']} 项被 wildcard 过滤 ⚠"
    elif sub_info["found"]:
        sub_summary = f"{sub_info['found']} 项存活"
    if sub_summary:
        branches.append(("子域", sub_summary))

    # 拼 ASCII 树
    lines = ["```", target]
    for i, (kind, value) in enumerate(branches):
        is_last = i == len(branches) - 1
        # A 记录下挂端口
        connector = "└──" if (is_last and not (kind == "A" and ports)) else "├──"
        lines.append(f"{connector} {kind:<5} {value}")
        # A 记录第一项 + 有端口 → 端口挂在第一个 A 下面
        if kind == "A" and ports and i == next(idx for idx, (k, _) in enumerate(branches) if k == "A"):
            indent = "│   " if not is_last else "    "
            for j, (port, service) in enumerate(ports):
                p_last = j == len(ports) - 1
                p_conn = "└──" if p_last else "├──"
                lines.append(f"{indent}{p_conn} :{port:<5}/tcp  {service}  (open)")
    lines.append("```")
    return "## 🌐 拓扑\n\n" + "\n".join(lines) + "\n"
