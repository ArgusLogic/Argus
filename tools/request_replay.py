"""B4: 请求重放工具。

从 devtools 的 _network_log 中按 index 或 url 子串选中一条已捕获的请求，
默认复用浏览器 session 重放，可选修改 headers / body。
"""

from __future__ import annotations

import json

from agent.tool_registry import registry


def _filter_requests(filter_str: str) -> list[tuple[int, dict]]:
    """从 _network_log 中过滤 type=request，返回 [(原始 index, entry), ...]。"""
    from tools.devtools import _network_log

    out: list[tuple[int, dict]] = []
    for i, entry in enumerate(_network_log):
        if entry.get("type") != "request":
            continue
        if filter_str and filter_str.lower() not in entry.get("url", "").lower():
            continue
        out.append((i, entry))
    return out


@registry.tool(
    name="request_replay_list",
    description=(
        "列出 devtools 抓包中已捕获的请求（仅 type=request 的条目），"
        "可用 filter 关键词过滤 URL。返回索引、方法、URL，便于 request_replay 使用。"
    ),
    params={
        "filter": {
            "type": "string",
            "description": "URL 关键词过滤（可选）",
            "required": False,
        },
        "limit": {
            "type": "string",
            "description": "返回最大条数，默认 30",
            "required": False,
        },
    },
)
async def request_replay_list(filter: str = "", limit: str = "30") -> str:
    try:
        max_count = int(limit)
    except ValueError:
        max_count = 30

    matches = _filter_requests(filter)[-max_count:]
    if not matches:
        return "无匹配请求。请先访问页面让 devtools 捕获，或调整 filter。"

    lines = [f"共 {len(matches)} 条请求 (idx | method | url):"]
    for idx, e in matches:
        lines.append(f"  [{idx}] {e.get('method', '?'):6s} {e.get('url', '?')}")
    return "\n".join(lines)


@registry.tool(
    name="request_replay",
    description=(
        "从 devtools 抓包记录中重放一个请求。默认使用浏览器 session（Cookie/UA/Referer）。"
        "可通过 modify_headers / modify_body 覆盖原始头部和 body。"
        "用 request_replay_list 先获取 index。"
    ),
    params={
        "index": {
            "type": "string",
            "description": "请求在 _network_log 中的索引（用 request_replay_list 查询）",
        },
        "modify_headers": {
            "type": "string",
            "description": "可选：覆盖请求头的 JSON 字符串，如 '{\"X-Custom\": \"val\"}'",
            "required": False,
        },
        "modify_body": {
            "type": "string",
            "description": "可选：覆盖请求体（仅 POST/PUT/PATCH）",
            "required": False,
        },
        "use_browser_session": {
            "type": "string",
            "description": "默认 'true'。设 'false' 则发独立请求（不带 Cookie）",
            "required": False,
        },
    },
)
async def request_replay(
    index: str,
    modify_headers: str = "",
    modify_body: str = "",
    use_browser_session: str = "true",
) -> str:
    from tools.devtools import _network_log
    from tools.http_client import http_request

    try:
        idx = int(index)
    except ValueError:
        return f"index 必须是整数: {index}"

    log_list = list(_network_log)
    if idx < 0 or idx >= len(log_list):
        return f"index 越界: {idx} (共 {len(log_list)} 条)"

    entry = log_list[idx]
    if entry.get("type") != "request":
        return f"索引 {idx} 不是请求条目（type={entry.get('type')}）"

    url = entry.get("url", "")
    method = entry.get("method", "GET")
    original_headers = entry.get("headers", {}) or {}

    # 合并：原始头部 + 用户修改
    merged: dict = dict(original_headers)
    if modify_headers:
        try:
            override = json.loads(modify_headers)
            if isinstance(override, dict):
                merged.update({str(k): str(v) for k, v in override.items()})
        except json.JSONDecodeError as e:
            return f"modify_headers JSON 解析失败: {e}"

    # 剔除 hop-by-hop / 浏览器自动管理的头（避免冲突）
    for hop in ("connection", "host", "content-length", "transfer-encoding"):
        for k in list(merged.keys()):
            if k.lower() == hop:
                del merged[k]

    return await http_request(
        url=url,
        method=method,
        headers=json.dumps(merged, ensure_ascii=False),
        body=modify_body,
        use_browser_session=use_browser_session,
    )
