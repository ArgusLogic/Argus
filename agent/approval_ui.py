"""Claude Code 风格的工具审批面板（prompt_toolkit Application）。

替代之前的 `input("y/n")` 单行 prompt：

    ┌─ <上一句 user 提问> ────────────────────────────────────────────┐
    │                                                                │
    │  Tool: subdomain_enum                                          │
    │                                                                │
    │  {                                                             │
    │    "domain": "limingjing.codes"                                │
    │  }                                                             │
    │                                                                │
    │  ⚠ 高风险：将对目标域名发起大量 DNS 请求                        │
    │                                                                │
    │  This tool requires approval                                   │
    │                                                                │
    │  Do you want to proceed?                                       │
    │  ❯ 1. Yes                                                      │
    │    2. Yes, and don't ask again this session for: subdomain_enum│
    │    3. No                                                       │
    │                                                                │
    │  Esc to cancel · ↑↓ to move · 1/2/3 to pick · Enter to confirm │
    └────────────────────────────────────────────────────────────────┘

非 TTY / prompt_toolkit 异常时自动回退到原始 `input("y/n")`。
"""

from __future__ import annotations

import enum
import json
import sys
from dataclasses import dataclass


class ApprovalChoice(enum.Enum):
    """三选一审批结果。"""

    APPROVE = "approve"
    APPROVE_SKIP_SESSION = "approve_skip_session"
    REJECT = "reject"


@dataclass
class _PromptParams:
    user_request: str
    tool_name: str
    tool_args: str
    risk_level: str
    risk_hint: str | None


def _pretty_args(args: str) -> str:
    """尽力把工具参数 JSON 美化成多行；解析失败原样返回。"""
    try:
        parsed = json.loads(args)
    except Exception:
        return args
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _truncate(s: str, limit: int = 70) -> str:
    s = s.strip().splitlines()[0] if s else ""
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


# ────────────────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────────────────


async def prompt_for_approval(
    *,
    user_request: str,
    tool_name: str,
    tool_args: str,
    risk_level: str,
    risk_hint: str | None = None,
) -> ApprovalChoice:
    """弹出审批面板。返回用户选择。

    实现策略：
      - 优先 prompt_toolkit Application（带边框、键盘选择）
      - 任何异常或非 TTY → 回退到 `input("y/n")`
    """
    params = _PromptParams(
        user_request=user_request,
        tool_name=tool_name,
        tool_args=_pretty_args(tool_args),
        risk_level=risk_level,
        risk_hint=risk_hint,
    )

    # 非 TTY（CI / pipe / pytest）直接走纯文本
    try:
        if not sys.stdin.isatty():
            return _fallback_text_prompt(params)
    except Exception:
        return _fallback_text_prompt(params)

    try:
        return await _run_ptk_app(params)
    except Exception:
        return _fallback_text_prompt(params)


# ────────────────────────────────────────────────────────────────────────────
# prompt_toolkit Application
# ────────────────────────────────────────────────────────────────────────────


async def _run_ptk_app(p: _PromptParams) -> ApprovalChoice:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.widgets import Frame

    # 高风险红框，普通确认蓝框
    is_block = p.risk_level == "block"
    title_color = "ansired" if is_block else "ansicyan"
    title = _truncate(p.user_request) if p.user_request else "Tool approval"

    options: list[tuple[str, ApprovalChoice]] = [
        ("Yes", ApprovalChoice.APPROVE),
        (
            f"Yes, and don't ask again this session for: {p.tool_name}",
            ApprovalChoice.APPROVE_SKIP_SESSION,
        ),
        ("No", ApprovalChoice.REJECT),
    ]
    cursor: list[int] = [0]  # 用 list 装 int 以便闭包 mutate
    result: list[ApprovalChoice | None] = [None]

    def _render() -> FormattedText:
        lines: list[tuple[str, str]] = []

        lines.append(("bold", f"  Tool: {p.tool_name}\n\n"))
        for ln in p.tool_args.splitlines():
            lines.append(("ansigreen", f"  {ln}\n"))
        lines.append(("", "\n"))

        if is_block and p.risk_hint:
            lines.append(("ansired bold", f"  ⚠ 高风险: {p.risk_hint}\n\n"))
        elif p.risk_hint:
            lines.append(("ansiyellow", f"  ⚠ {p.risk_hint}\n\n"))

        lines.append(("ansigray", "  This tool requires approval\n\n"))
        lines.append(("bold", "  Do you want to proceed?\n"))

        for idx, (label, _val) in enumerate(options):
            if idx == cursor[0]:
                lines.append(("ansicyan bold", f"  ❯ {idx + 1}. {label}\n"))
            else:
                lines.append(("", f"    {idx + 1}. {label}\n"))

        lines.append(
            (
                "ansigray",
                "\n  Esc to cancel · ↑↓ to move · 1/2/3 to pick · Enter to confirm",
            )
        )
        return FormattedText(lines)

    kb = KeyBindings()

    @kb.add("up")
    def _(event):  # type: ignore[no-untyped-def]
        cursor[0] = (cursor[0] - 1) % len(options)
        event.app.invalidate()

    @kb.add("down")
    def _(event):  # type: ignore[no-untyped-def]
        cursor[0] = (cursor[0] + 1) % len(options)
        event.app.invalidate()

    @kb.add("1")
    def _(event):  # type: ignore[no-untyped-def]
        result[0] = options[0][1]
        event.app.exit()

    @kb.add("2")
    def _(event):  # type: ignore[no-untyped-def]
        result[0] = options[1][1]
        event.app.exit()

    @kb.add("3")
    def _(event):  # type: ignore[no-untyped-def]
        result[0] = options[2][1]
        event.app.exit()

    @kb.add("enter")
    def _(event):  # type: ignore[no-untyped-def]
        result[0] = options[cursor[0]][1]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):  # type: ignore[no-untyped-def]
        result[0] = ApprovalChoice.REJECT
        event.app.exit()

    body = Window(FormattedTextControl(_render), wrap_lines=True)
    root = Frame(body, title=f"[{title}]", style=title_color)
    layout = Layout(HSplit([root]))

    app: Application = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )
    await app.run_async()
    return result[0] if result[0] is not None else ApprovalChoice.REJECT


# ────────────────────────────────────────────────────────────────────────────
# Fallback：纯文本 stdin
# ────────────────────────────────────────────────────────────────────────────


def _fallback_text_prompt(p: _PromptParams) -> ApprovalChoice:
    """无 TTY 或 prompt_toolkit 不可用时的回退。"""
    print()
    if p.risk_level == "block":
        print(f"[!] 高风险: {p.risk_hint or '此操作可能对目标产生可检测的影响'}")
    elif p.risk_hint:
        print(f"[!] {p.risk_hint}")
    print(f"    Tool: {p.tool_name}")
    print(f"    Args: {p.tool_args}")
    print("    1) Yes")
    print(f"    2) Yes, and skip this session for: {p.tool_name}")
    print("    3) No")
    try:
        ans = input("    Choose [1/2/3] (default 1): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ApprovalChoice.REJECT

    if ans in ("", "1", "y", "yes"):
        return ApprovalChoice.APPROVE
    if ans == "2":
        return ApprovalChoice.APPROVE_SKIP_SESSION
    return ApprovalChoice.REJECT
