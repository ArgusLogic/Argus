"""CLI 交互 UI 组件 — 参考 DeepSeek-TUI 风格。

特性：
- 流式 Markdown 渲染
- Thinking 推理过程可见（dim 折叠样式）
- 紧凑工具调用面板（⚡ name → ✓/✗ elapsed）
- 每轮 Token + 费用统计
- prompt_toolkit 输入增强（历史 + / 命令补全）
"""

import json
import time
from dataclasses import dataclass, field

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

console = Console()

# ─── 费率表 (¥/百万 token) ──────────────────────────────────────────────────

_COST_PER_M: dict[str, dict] = {
    # DeepSeek V4 官方定价 (来源: api-docs.deepseek.com/zh-cn/quick_start/pricing)
    "deepseek/deepseek-v4-flash": {"input": 1.0, "output": 2.0, "cached": 0.02},
    "deepseek/deepseek-v4-pro": {"input": 3.0, "output": 6.0, "cached": 0.025},  # 2.5折期至 2026/05/31
    # 旧版
    "deepseek/deepseek-chat": {"input": 1.0, "output": 4.0, "cached": 0.5},
}


# ─── 数据结构 ─────────────────────────────────────────────────────────────────


@dataclass
class ToolCallDisplay:
    """单次工具调用的显示状态。"""

    name: str
    args_str: str = ""
    status: str = "running"  # running / done / error
    result_preview: str = ""
    elapsed: float = 0.0
    start_time: float = field(default_factory=time.time)


# ─── Prompt Toolkit 输入 ──────────────────────────────────────────────────────

_SLASH_COMMANDS = [
    "/help",
    "/tools",
    "/model",
    "/session",
    "/memory",
    "/skills",
    "/clear",
    "/exit",
    "/cost",
    "/yolo",
    "/agent",
    "/effort",
]

_cmd_completer = WordCompleter(
    _SLASH_COMMANDS,
    sentence=True,
)


class _SafeFileHistory(FileHistory):
    """FileHistory 的安全版本：过滤掉孤立 UTF-16 代理字符，避免 Windows 上写入崩溃。

    prompt_toolkit 在 Windows 控制台读取某些字符（如 emoji）时可能产生
    lone surrogates（U+D800-U+DFFF），后续 .encode('utf-8') 会抛 UnicodeEncodeError。
    这里在写入历史前用 'replace' 错误处理策略剔除非法码点。
    """

    @staticmethod
    def _sanitize(text: str) -> str:
        # 用 surrogateescape → utf-8 round-trip 剥离孤立代理
        try:
            return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))

    def store_string(self, string: str) -> None:
        super().store_string(self._sanitize(string))


def create_prompt_session() -> PromptSession:
    """创建带历史 + 自动补全的 PromptSession。"""
    from utils.paths import HISTORY_PATH

    history_path = HISTORY_PATH
    return PromptSession(
        history=_SafeFileHistory(history_path),
        completer=_cmd_completer,
        complete_while_typing=False,
    )


# Rich 用普通色名；prompt_toolkit 用 ansiXxx — 两套都需要
MODE_COLORS: dict[str, str] = {"agent": "cyan", "plan": "yellow", "yolo": "red"}
MODE_ANSI_COLORS: dict[str, str] = {"agent": "ansicyan", "plan": "ansiyellow", "yolo": "ansired"}


def get_prompt_text(model: str = "", mode: str = "agent") -> HTML:
    """构建极简输入提示符（Claude Code 风格）。"""
    model_short = model.split("/")[-1] if "/" in model else model
    color = MODE_ANSI_COLORS.get(mode, "ansicyan")
    mode_tag = "" if mode == "agent" else f'<style fg="{color}">[{mode}]</style> '
    return HTML(
        f'\n{mode_tag}<style fg="ansibrightblack">{model_short}</style> <b><style fg="{color}">› </style></b>'
    )


def print_user_message(
    text: str, mode: str = "agent", target_console: Console | None = None
) -> None:
    """把用户输入回显成左竖线高亮块（Claude Code 风格 + DeepSeek-TUI mode 色彩）。

    左竖线颜色随 mode 变化（agent=cyan / plan=yellow / yolo=red），强化模式视觉一致性。
    """
    from rich.padding import Padding

    c = target_console or console
    color = MODE_COLORS.get(mode, "cyan")
    bar = Text("▎", style=f"{color} bold")
    body = Text(text.strip(), style="bright_white")
    c.print(Padding(Columns([bar, body], padding=(0, 1)), (1, 0, 0, 0)))


def print_startup_hint(target_console: Console | None = None, mode: str = "agent") -> None:
    """启动 banner 之后打印一行键位 / 模式提示（Claude Code + DeepSeek-TUI 风格）。"""
    c = target_console or console
    color = MODE_COLORS.get(mode, "cyan")
    line = Text.assemble(
        ("  [", "dim"),
        (mode, f"dim {color}"),
        ("] · ", "dim"),
        ("Esc", "dim bold"),
        (" to interrupt · ", "dim"),
        ("/help", "dim cyan"),
        (" · ", "dim"),
        ("/yolo", "dim red"),
        (" · ", "dim"),
        ("/effort", "dim cyan"),
        (" · ", "dim"),
        ("/cost", "dim cyan"),
    )
    c.print(line)
    c.print()


# ─── 核心 UI 渲染器 ──────────────────────────────────────────────────────────


class LiveUI:
    """驱动 Agent 对话的终端实时渲染。"""

    def __init__(self, target_console: Console | None = None, model: str = ""):
        self._console = target_console or console
        self._live: Live | None = None
        self._phase = "idle"  # idle / thinking / streaming / tool / done
        self._text_buffer = ""
        self._thinking_buffer = ""
        self._tool_calls: list[ToolCallDisplay] = []
        self._current_tool: ToolCallDisplay | None = None
        self._start_time = 0.0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0
        self._model = model
        self._completed_sections: list = []
        self._tool_count = 0

    def start(self) -> None:
        """开始 Live 渲染上下文。"""
        self._start_time = time.time()
        self._text_buffer = ""
        self._thinking_buffer = ""
        self._tool_calls = []
        self._completed_sections = []
        self._tool_count = 0
        self._phase = "idle"
        self._live = Live(
            "",
            console=self._console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()

    def stop(self) -> None:
        """结束 Live 渲染，输出最终静态内容。"""
        from rich.rule import Rule

        if self._live:
            self._live.stop()
            self._live = None

        # 输出已完成的 sections（工具调用、中间文本）
        for section in self._completed_sections:
            self._console.print(section)

        # 输出 thinking 崩缩为单行总结（Claude Code 风格：Crunched for Xs，无 chars 数）
        if self._thinking_buffer.strip():
            think_elapsed = time.time() - self._start_time
            self._console.print(
                Text(f"※ Crunched for {think_elapsed:.0f}s", style="dim")
            )

        # 输出最终回复（纯 Markdown，无 ● 前缀以避免 Columns 错位）
        if self._text_buffer.strip():
            self._console.print(Markdown(self._text_buffer.strip()))

        # 每轮间淡灰水平线分隔（Claude Code 风格）
        # 每轮 tokens / ¥ 行已隐藏，仅 /cost 命令显示累计统计
        self._console.print(Rule(style="dim"))

    # ─── 阶段切换 ─────────────────────────────────────────────────────────

    def set_thinking(self) -> None:
        """进入思考状态（旋转动画）。"""
        self._phase = "thinking"
        self._update()

    def set_streaming(self) -> None:
        """进入流式输出状态。"""
        self._phase = "streaming"
        self._update()

    def append_thinking(self, delta: str) -> None:
        """追加 thinking/reasoning 内容。"""
        self._thinking_buffer += delta
        if self._phase == "idle" or self._phase == "thinking":
            self._phase = "thinking"
        self._update()

    def append_text(self, delta: str) -> None:
        """追加流式文本片段（自动脱敏敏感信息）。"""
        from utils.sanitizer import redact_secrets

        if self._phase != "streaming":
            self._phase = "streaming"
        self._text_buffer += redact_secrets(delta)
        self._update()

    def add_tool_call(self, name: str, args_str: str = "") -> None:
        """添加一个工具调用（开始执行）。"""
        # 如果有正在流式的文本，先固化为项目符风格
        if self._text_buffer.strip():
            self._completed_sections.append(_render_inline_reply(self._text_buffer.strip()))
            self._text_buffer = ""

        tc = ToolCallDisplay(name=name, args_str=args_str)
        self._tool_calls.append(tc)
        self._current_tool = tc
        self._tool_count += 1
        self._phase = "tool"
        self._update()

    def finish_tool_call(self, name: str, result: str, elapsed: float = 0.0) -> None:
        """标记工具调用完成（结果自动脱敏）。"""
        from utils.sanitizer import redact_secrets

        for tc in self._tool_calls:
            if tc.name == name and tc.status == "running":
                tc.status = "done"
                tc.elapsed = elapsed
                tc.result_preview = _truncate_result(redact_secrets(result), max_lines=3)
                break
        self._current_tool = None
        self._flush_done_tools()
        self._phase = "streaming"
        self._update()

    def fail_tool_call(self, name: str, error: str, elapsed: float = 0.0) -> None:
        """标记工具调用失败（错误信息自动脱敏）。"""
        from utils.sanitizer import redact_secrets

        for tc in self._tool_calls:
            if tc.name == name and tc.status == "running":
                tc.status = "error"
                tc.elapsed = elapsed
                tc.result_preview = redact_secrets(error)[:200]
                break
        self._current_tool = None
        self._flush_done_tools()
        self._phase = "streaming"
        self._update()

    def set_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """设置 token 计数。"""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def finish(
        self, input_tokens: int = 0, output_tokens: int = 0, cache_hit: int = 0, cache_miss: int = 0
    ) -> None:
        """完成本次对话渲染。"""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._cache_hit_tokens = cache_hit
        self._cache_miss_tokens = cache_miss
        self._phase = "done"
        self.stop()

    # ─── 内部渲染 ─────────────────────────────────────────────────────────

    def _flush_done_tools(self) -> None:
        """将已完成的工具调用移入 completed_sections。"""
        done_tools = [tc for tc in self._tool_calls if tc.status != "running"]
        for tc in done_tools:
            self._completed_sections.append(_render_tool_call(tc))
            self._tool_calls.remove(tc)

    def _update(self) -> None:
        """刷新 Live 显示内容。"""
        if not self._live:
            return

        renderables: list = []

        # 正在执行的工具调用
        for tc in self._tool_calls:
            if tc.status == "running":
                renderables.append(_render_tool_call_live(tc))

        # 思考动画（显示 thinking 内容尾部）
        if self._phase == "thinking":
            parts: list = []
            parts.append(
                Columns(
                    [
                        Spinner("dots", style="cyan"),
                        Text(" thinking...", style="dim cyan"),
                    ],
                    padding=(0, 0),
                )
            )
            # 显示 thinking 内容的最后几行
            if self._thinking_buffer.strip():
                lines = self._thinking_buffer.strip().split("\n")
                tail = "\n".join(lines[-4:])  # 最后 4 行
                parts.append(Text(tail, style="dim italic"))
            renderables.extend(parts)

        # 流式文本（纯 Markdown，无 ● 前缀）
        elif self._phase == "streaming" and self._text_buffer.strip():
            try:
                lines = self._text_buffer.strip().split("\n")
                max_live_lines = 20
                if len(lines) > max_live_lines:
                    tail = "\n".join(lines[-max_live_lines:])
                    renderables.append(Text("  ⋯", style="dim"))
                else:
                    tail = "\n".join(lines)
                renderables.append(_render_inline_reply(tail))
            except Exception:
                renderables.append(Text(self._text_buffer[-500:]))

        if renderables:
            self._live.update(Group(*renderables))
        else:
            self._live.update(Text(""))

    def _build_stats(self, elapsed: float):
        """构建底部统计栏（含费用估算）。"""
        parts = []

        if self._input_tokens or self._output_tokens:
            # 显示 cache 命中信息
            if self._cache_hit_tokens:
                parts.append(
                    f"tokens: {self._input_tokens:,} in "
                    f"({self._cache_hit_tokens:,} cached) / "
                    f"{self._output_tokens:,} out"
                )
            else:
                parts.append(f"tokens: {self._input_tokens:,} in / {self._output_tokens:,} out")

            # 费用估算（区分缓存命中价格）
            cost = _estimate_cost(
                self._model,
                self._input_tokens,
                self._output_tokens,
                self._cache_hit_tokens,
                self._cache_miss_tokens,
            )
            if cost > 0:
                parts.append(f"¥{cost:.4f}")

        parts.append(f"{elapsed:.1f}s")
        if self._tool_count:
            parts.append(f"{self._tool_count} tool calls")

        if parts:
            return Text("  " + " · ".join(parts), style="dim")
        return None


# ─── 累积会话统计 ─────────────────────────────────────────────────────────────


class SessionStats:
    """跟踪整个会话的 token 和费用累计。"""

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.turn_count = 0

    def add_turn(
        self, model: str, input_tokens: int, output_tokens: int, cache_hit: int = 0, cache_miss: int = 0
    ) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += _estimate_cost(model, input_tokens, output_tokens, cache_hit, cache_miss)
        self.turn_count += 1

    def format(self) -> str:
        return (
            f"会话累计: {self.turn_count} 轮 | "
            f"tokens: {self.total_input_tokens:,} in / {self.total_output_tokens:,} out | "
            f"¥{self.total_cost:.4f}"
        )


# ─── 辅助渲染函数 ─────────────────────────────────────────────────────────────


def _render_inline_reply(text: str):
    """渲染 Agent 回复为纯 Markdown（Claude Code 风格——去掉 ● 避免 Columns 错位）。"""
    return Markdown(text)


def _render_tool_call_live(tc: ToolCallDisplay):
    """渲染正在执行的工具调用（带 spinner，Panel 包裹）。"""
    from rich.box import ROUNDED
    from rich.panel import Panel

    elapsed = time.time() - tc.start_time
    args_preview = _format_args(tc.args_str)

    header = Text.assemble(
        ("⚡ ", "yellow"),
        (tc.name, "bold green"),
        (f"({args_preview})", "dim"),
    )
    spinner_line = Columns(
        [
            Spinner("dots", style="yellow"),
            Text(f" running... ({elapsed:.1f}s)", style="dim yellow"),
        ],
        padding=(0, 0),
    )
    return Panel(
        Group(header, spinner_line),
        box=ROUNDED,
        border_style="yellow",
        padding=(0, 1),
        expand=False,
    )


def _render_tool_call(tc: ToolCallDisplay):
    """渲染已完成的工具调用：成功默认折叠成单行 Panel；失败展开多行 Panel。"""
    from rich.box import ROUNDED
    from rich.panel import Panel

    args_preview = _format_args(tc.args_str)

    # 成功路径：单行 Panel（DeepSeek-TUI 风格折叠）
    if tc.status == "done":
        one_line = Text.assemble(
            ("⚡ ", "yellow"),
            (tc.name, "bold green"),
            (f"({args_preview})", "dim"),
            ("  ✓ ", "bold green"),
            (f"{tc.elapsed:.1f}s", "dim"),
        )
        return Panel(one_line, box=ROUNDED, border_style="dim green", padding=(0, 1), expand=False)

    # 失败路径：展开 Panel，含错误预览
    header = Text.assemble(
        ("⚡ ", "yellow"),
        (tc.name, "bold red"),
        (f"({args_preview})", "dim"),
    )
    status_line = Text.assemble(
        ("✗ ", "bold red"),
        (f"failed ({tc.elapsed:.1f}s)", "dim"),
    )
    lines: list = [header, status_line]
    if tc.result_preview:
        for line in tc.result_preview.split("\n"):
            lines.append(Text(line, style="dim red"))
    return Panel(
        Group(*lines), box=ROUNDED, border_style="red", padding=(0, 1), expand=False
    )


def _format_args(args_str: str) -> str:
    """格式化工具参数为简短预览。"""
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
        if isinstance(args, dict):
            parts = []
            for k, v in args.items():
                v_str = str(v)
                if len(v_str) > 40:
                    v_str = v_str[:37] + "..."
                parts.append(f"{k}={v_str}")
            return ", ".join(parts)
    except Exception:
        pass
    if len(args_str) > 60:
        return args_str[:57] + "..."
    return args_str


def _truncate_result(result: str, max_lines: int = 3) -> str:
    """截断工具结果到指定行数。"""
    if not result:
        return ""
    lines = result.strip().split("\n")
    if len(lines) <= max_lines:
        return result.strip()
    truncated = "\n".join(lines[:max_lines])
    return truncated + f"\n... ({len(lines) - max_lines} more lines)"


def _estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cache_hit: int = 0, cache_miss: int = 0
) -> float:
    """估算费用（¥），区分缓存命中和未命中的输入价格。"""
    rates = _COST_PER_M.get(model)
    if not rates:
        return 0.0
    if cache_hit or cache_miss:
        # 精确计费：缓存命中用 cached 价，未命中用 input 价
        input_cost = (
            cache_hit * rates.get("cached", rates["input"]) + cache_miss * rates["input"]
        ) / 1_000_000
    else:
        input_cost = input_tokens * rates["input"] / 1_000_000
    output_cost = output_tokens * rates["output"] / 1_000_000
    return input_cost + output_cost
