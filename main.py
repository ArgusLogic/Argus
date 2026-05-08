"""Argus - 网络安全信息收集 Agent CLI 入口。"""

import asyncio
import contextlib
import os
import sys
from typing import Any

from rich.table import Table

from agent.engine import AgentEngine
from agent.errors import ArgusError
from agent.llm_client import LLMClient
from agent.session import delete_session, list_sessions, load_session, save_session
from agent.tool_registry import registry
from utils.logger import console, file_logger, log_error, log_info, log_warning
from utils.ui import LiveUI, SessionStats, create_prompt_session, get_prompt_text

# 自动发现并注册 tools/ 下的所有工具
registry.auto_discover("tools")


def load_config() -> dict:
    """加载配置文件。issue #9：委托给 utils.config 单例（带缓存）。"""
    from utils.config import get_config
    from utils.paths import CONFIG_PATH

    cfg = get_config()
    if not cfg:
        log_error(f"配置文件不存在: {CONFIG_PATH}")
        log_info(f"请将 config.example.toml 复制到 {CONFIG_PATH} 并填入 API Key")
        sys.exit(1)
    return cfg


# ─── Argus Panoptes Matrix（4 行宽幅版，照搬 React Ink 源） ─────────
_ARGUS_FRAME = "#30363d"
_ARGUS_EYE = "#58A6FF"
_ARGUS_WHITE = "#e6edf3"

_ARGUS_LINES = [
    f"[{_ARGUS_FRAME}] ▄▄███████████████▄▄ [/]",
    f"[{_ARGUS_EYE}]▐██[/][{_ARGUS_WHITE}]▀█▀█▀█▀█▀█▀█▀█▀[/][{_ARGUS_EYE}]██▌[/]",
    f"[{_ARGUS_EYE}]▐██[/][{_ARGUS_WHITE}]▄█▄█▄█▄█▄█▄█▄█▄[/][{_ARGUS_EYE}]██▌[/]",
    f"[{_ARGUS_FRAME}] ▀▀███████████████▀▀ [/]",
]


def print_banner(model: str) -> None:
    """精简版启动横幅：左侧 logo + 右侧 3 行关键信息（Claude Code 风）。"""
    from rich.table import Table
    from rich.text import Text as RichText

    from utils._native import has_native

    cwd = os.getcwd()
    model_short = model.split("/")[-1] if "/" in model else model
    n_tools = len(registry.list_tools())
    native_tag = "[#3fb950]⚡rust[/]" if has_native() else "[#484f58]py[/]"

    # 右侧 3 行（logo 占 4 行，顶格对齐 logo 第 2 行）
    info_rows = [
        "",
        f"[bold #e6edf3]Argus[/] [#7d8590]v0.1[/] [#484f58]·[/] [#7d8590]{model_short}[/]",
        f"[#7d8590]{n_tools} tools loaded[/] [#484f58]·[/] [#7d8590]/help[/] [#484f58]·[/] [#7d8590]Esc to interrupt[/] [#484f58]·[/] {native_tag}",
        f"[#484f58]{cwd}[/]",
    ]

    tbl = Table.grid(padding=(0, 2))
    tbl.add_column(no_wrap=True)
    tbl.add_column(no_wrap=True)
    for i in range(4):
        tbl.add_row(
            RichText.from_markup(_ARGUS_LINES[i]),
            RichText.from_markup(info_rows[i]),
        )

    console.print()
    console.print(tbl)
    console.print()


def print_help() -> None:
    """打印帮助信息。"""
    table = Table(title="可用命令", border_style="cyan")
    table.add_column("命令", style="bold green")
    table.add_column("说明")
    table.add_row("/help", "显示帮助信息")
    table.add_row("/tools", "列出所有可用工具")
    table.add_row("/model [name]", "切换 LLM 模型（无参数显示当前）")
    table.add_row("/yolo", "开启 YOLO 模式（跳过所有工具审批）")
    table.add_row("/agent", "恢复 Agent 模式（工具需审批）")
    table.add_row("/effort [off|high|max]", "切换思考强度（无参数显示当前）")
    table.add_row("/memory", "查看 MEMORY.md 和 USER.md 当前内容")
    table.add_row("/session save [name]", "保存当前会话")
    table.add_row("/session load <name>", "加载已保存的会话")
    table.add_row("/session list", "列出所有已保存的会话")
    table.add_row("/session delete <name>", "删除指定会话")
    table.add_row("/skills list", "列出所有技能")
    table.add_row("/skills show <name>", "查看技能详情")
    table.add_row("/skills delete <name>", "删除技能")
    table.add_row("/cost", "查看会话累计 Token 和费用")
    table.add_row("/clear", "清空对话上下文")
    table.add_row("/exit", "退出程序")
    console.print(table)


def print_tools() -> None:
    """打印所有已注册的工具。"""
    table = Table(title="已注册工具", border_style="green")
    table.add_column("#", style="dim")
    table.add_column("工具名", style="bold green")
    table.add_column("说明")

    schemas = registry.get_tools_schema()
    for i, schema in enumerate(schemas, 1):
        func = schema["function"]
        table.add_row(str(i), func["name"], func["description"])

    console.print(table)


_AVAILABLE_MODELS = [
    ("deepseek/deepseek-v4-flash", "V4 Flash · ¥1/2 per Mtok"),
    ("deepseek/deepseek-v4-pro", "V4 Pro · ¥3/6 per Mtok (2.5折)"),
    ("deepseek/deepseek-chat", "旧版 Chat（将于 2026/07 弃用）"),
    # 小米 MiMo V2.5 系列（platform.xiaomimimo.com，开源、1M 上下文）
    ("xiaomi_mimo/mimo-v2.5-pro", "MiMo V2.5 Pro · 旗舰推理 / Coding / Agent · 1M ctx"),
    ("xiaomi_mimo/mimo-v2.5", "MiMo V2.5 · 多模态（文本+图像）· 1M ctx"),
    ("xiaomi_mimo/mimo-v2.5-flash", "MiMo V2.5 Flash · 推理快 / 价格低 · 1M ctx"),
]

_EFFORT_LEVELS = ["off", "high", "max"]


async def _interactive_model_select(
    current_model: str, current_effort: str | None
) -> tuple[str | None, str | None]:
    """内联式模型选择器：↑↓ 切换模型，← → 切换 effort，Enter 确认，Esc 取消。"""
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    # 构建模型列表
    models = list(_AVAILABLE_MODELS)
    # 如果当前模型不在列表里，加到开头
    model_ids = [m[0] for m in models]
    if current_model not in model_ids:
        models.insert(0, (current_model, "(自定义)"))
        model_ids = [m[0] for m in models]

    selected_idx = model_ids.index(current_model) if current_model in model_ids else 0
    effort = current_effort or "high"
    effort_idx = _EFFORT_LEVELS.index(effort) if effort in _EFFORT_LEVELS else 1
    result: dict[str, str | None] = {"model": None, "effort": None}

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(models)

    @kb.add("down")
    def _down(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(models)

    @kb.add("left")
    def _left(event):
        nonlocal effort_idx
        effort_idx = (effort_idx - 1) % len(_EFFORT_LEVELS)

    @kb.add("right")
    def _right(event):
        nonlocal effort_idx
        effort_idx = (effort_idx + 1) % len(_EFFORT_LEVELS)

    @kb.add("enter")
    def _enter(event):
        result["model"] = model_ids[selected_idx]
        result["effort"] = _EFFORT_LEVELS[effort_idx]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit()

    def _get_text():
        lines: list[tuple[str, str]] = []
        lines.append(("bold green", "Select model\n"))
        lines.append(("", "切换模型。↑↓ 选择模型，← → 调整思考强度，Enter 确认，Esc 取消。\n\n"))

        for i, (model_id, desc) in enumerate(models):
            is_current = model_id == current_model
            is_selected = i == selected_idx

            if is_selected:
                prefix = "› "
                style = "bold"
            else:
                prefix = "  "
                style = ""

            num = f"{i + 1}. "
            check = " ✓" if is_current else ""
            lines.append((style, f"  {prefix}{num}"))
            lines.append((style, f"{model_id}"))
            if check:
                lines.append(("bold green", check))
            lines.append(("dim", f"  {desc}"))
            lines.append(("", "\n"))

        # effort 指示器
        lines.append(("", "\n"))
        effort_label = _EFFORT_LEVELS[effort_idx].capitalize()
        effort_display = {"Off": "💤 Off", "High": "🧠 High", "Max": "🔥 Max"}
        lines.append(("yellow", f"  ● {effort_display.get(effort_label, effort_label)} effort"))
        lines.append(("dim", "  ← → to adjust\n"))
        lines.append(("dim", "\n  Enter to confirm · Esc to exit\n"))

        return FormattedText(lines)

    control = FormattedTextControl(_get_text)
    app: Application = Application(
        layout=Layout(Window(control)),
        key_bindings=kb,
        full_screen=False,
    )

    with contextlib.suppress(KeyboardInterrupt, EOFError):
        await app.run_async()

    return result.get("model"), result.get("effort")


async def handle_command(cmd: str, engine: AgentEngine) -> bool:
    """处理 CLI 命令，返回 True 表示继续循环，False 表示退出。"""
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/help":
        print_help()

    elif command == "/tools":
        print_tools()

    elif command == "/model":
        if len(parts) >= 2:
            engine.llm.switch_model(parts[1])
        else:
            new_model, new_effort = await _interactive_model_select(
                engine.llm.model, engine.llm.reasoning_effort
            )
            if new_model:
                if new_model != engine.llm.model:
                    engine.llm.switch_model(new_model)
                if new_effort != engine.llm.reasoning_effort:
                    engine.llm.reasoning_effort = new_effort
                    labels = {"off": "💤 Off", "high": "🧠 High", "max": "🔥 Max"}
                    log_info(f"思考强度: {labels.get(new_effort or '', new_effort or '')}")

    elif command == "/yolo":
        engine.approval_mode = False
        log_info("🚨 YOLO 模式已开启 — 工具将自动执行，无需审批")

    elif command == "/agent":
        engine.approval_mode = True
        log_info("🛡️ Agent 模式已恢复 — 高风险工具需用户审批")

    elif command == "/effort":
        if len(parts) < 2:
            current = engine.llm.reasoning_effort or "默认"
            log_info(f"当前思考强度: {current}")
        else:
            level = parts[1].lower()
            if level in ("off", "high", "max"):
                engine.llm.reasoning_effort = level
                labels = {"off": "💤 关闭思考", "high": "🧠 深度思考", "max": "🔥 最强思考"}
                log_info(f"思考强度已切换: {labels[level]} ({level})")
            else:
                log_warning("用法: /effort off|high|max")

    elif command == "/memory":
        # 显示当前 MEMORY.md 和 USER.md 内容（含容量条）
        from rich.panel import Panel

        console.print(
            Panel(
                engine.memory_md.render_block("memory"),
                border_style="cyan",
                padding=(0, 1),
            )
        )
        console.print(
            Panel(
                engine.memory_md.render_block("user"),
                border_style="magenta",
                padding=(0, 1),
            )
        )

    elif command == "/session":
        if len(parts) < 2:
            log_warning("用法: /session save|load|list [name]")
        elif parts[1] == "save":
            name = parts[2] if len(parts) > 2 else None
            await save_session(engine.messages, name)
        elif parts[1] == "load":
            if len(parts) < 3:
                log_warning("用法: /session load <name>")
            else:
                messages = await load_session(parts[2])
                if messages:
                    engine.set_messages(messages)
        elif parts[1] == "list":
            sessions = await list_sessions()
            if sessions:
                for s in sessions:
                    console.print(f"  • {s}")
            else:
                log_info("暂无已保存的会话")
        elif parts[1] == "delete":
            if len(parts) < 3:
                log_warning("用法: /session delete <name>")
            else:
                await delete_session(parts[2])

    elif command == "/skills":
        if len(parts) < 2:
            log_warning("用法: /skills list|show|delete|pin|unpin")
        elif parts[1] == "list":
            skills = engine.skills.list_skills()
            if skills:
                for sk in skills:
                    pin_marker = "📌 " if sk.get("pinned") else ""
                    console.print(
                        f"  {pin_marker}[bold]{sk['name']}[/bold] — {sk['description']} "
                        f"({sk['steps_count']} 步, 成功 {sk['success_count']} 次)"
                    )
            else:
                log_info("暂无已保存的技能")
        elif parts[1] == "show":
            if len(parts) < 3:
                log_warning("用法: /skills show <name>")
            else:
                import json as _json

                skill = engine.skills.get_skill(parts[2])
                if skill:
                    console.print(_json.dumps(skill, ensure_ascii=False, indent=2))
                else:
                    log_warning(f"技能不存在: {parts[2]}")
        elif parts[1] == "delete":
            if len(parts) < 3:
                log_warning("用法: /skills delete <name>")
            else:
                engine.skills.delete_skill(parts[2])
        elif parts[1] == "pin":
            if len(parts) < 3:
                log_warning("用法: /skills pin <name>")
            elif engine.skills.set_pinned(parts[2], True):
                log_info(f"📌 已 pin: {parts[2]}（curator 不会动它）")
            else:
                log_warning(f"技能不存在: {parts[2]}")
        elif parts[1] == "unpin":
            if len(parts) < 3:
                log_warning("用法: /skills unpin <name>")
            elif engine.skills.set_pinned(parts[2], False):
                log_info(f"已 unpin: {parts[2]}")
            else:
                log_warning(f"技能不存在: {parts[2]}")
        elif parts[1] == "export":
            # C3: /skills export <name> [dest_dir]
            if len(parts) < 3:
                log_warning("用法: /skills export <name> [dest_dir]")
            else:
                from agent.skill_interop import export_skill

                skill = engine.skills.get_skill(parts[2])
                if not skill:
                    log_warning(f"技能不存在: {parts[2]}")
                else:
                    dest = (
                        parts[3]
                        if len(parts) > 3
                        else os.path.join(os.path.expanduser("~"), ".argus", "skills_export")
                    )
                    try:
                        out_path = export_skill(skill, dest)
                        log_info(f"📦 已导出 agentskills 格式 → {out_path}")
                    except Exception as e:
                        log_error(f"导出失败: {e}")
        elif parts[1] == "import":
            # C3: /skills import <path>（可指向 SKILL.md 或包含它的目录）
            if len(parts) < 3:
                log_warning("用法: /skills import <path>")
            else:
                from agent.skill_interop import import_skill

                try:
                    imported = import_skill(parts[2])
                    if engine.skills.get_skill(imported["name"]):
                        log_warning(f"技能已存在，跳过覆盖: {imported['name']}（删后重导）")
                    else:
                        engine.skills.save_skill(imported)
                        log_info(f"📥 已导入 agentskills 技能: {imported['name']}")
                except Exception as e:
                    log_error(f"导入失败: {e}")

    elif command == "/curator":
        # B1: /curator run [--dry-run] — 立即执行一次 curator
        from agent.curator import run_curator, write_report

        dry_run = "--dry-run" in parts or "--dry" in parts
        report = run_curator(engine.skills, dry_run=dry_run)
        path = write_report(report)
        console.print(report.render_markdown())
        log_info(f"curator 完成 → {path}")

    elif command == "/insights":
        # C1: /insights [--days N] — 跨会话趋势报表
        from agent.insights import collect_insights, render_table

        days = 7
        for i, p in enumerate(parts):
            if p == "--days" and i + 1 < len(parts):
                with contextlib.suppress(ValueError):
                    days = int(parts[i + 1])
        ins_report = await collect_insights(days=days)
        console.print(
            f"\n📈 Sessions: {ins_report.session_count} · "
            f"Messages: {ins_report.message_count} · "
            f"Tool calls: {ins_report.tool_call_count}\n"
        )
        if ins_report.tool_call_count:
            console.print(render_table(ins_report))
        else:
            log_info(f"最近 {days} 天没有已保存的会话工具调用")

    elif command == "/clear":
        from agent.prompts import SYSTEM_PROMPT

        engine.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        log_info("上下文已清空")

    elif command == "/exit":
        return False

    else:
        log_warning(f"未知命令: {command}，输入 /help 查看帮助")

    return True


def _parse_cli_args() -> dict[str, Any]:
    """解析顶层 CLI 参数（不抢占 / 命令）。

    支持：
      --yolo / -y                  : 启动即 YOLO 模式（issue #6）
      --target / -t <url|domain>   : issue #8 一键侦察目标
      --mode <recon|scan|full>     : issue #8 侦察强度，默认 recon
      --model <id>                 : 覆盖 config 的 default_model（如 xiaomi_mimo/mimo-v2.5-pro）
      --doctor                     : 仅运行体检（Day3-3）后退出
      --help / -h                  : 提示用法
    """
    from agent.recon_modes import VALID_MODES

    args: dict[str, Any] = {
        "yolo": False,
        "target": None,
        "mode": "recon",
        "model": None,
        "doctor": False,
    }
    argv = sys.argv[1:]
    if any(a in ("--help", "-h") for a in argv):
        print("用法: python main.py [--yolo|-y] [-t <target> [--mode <recon|scan|full>]] [--model <id>] [--doctor]")
        print("  --yolo, -y           启动即跳过审批（CI / 非交互终端）")
        print("  --target, -t URL     一次性侦察该目标，跑完即退出（issue #8）")
        print(f"  --mode MODE          侦察强度: {' | '.join(VALID_MODES)}（默认 recon）")
        print("  --model ID           覆盖 config.toml 的 default_model")
        print("  --doctor             启动前体检（依赖 / key / 字典 / 路径）后退出")
        sys.exit(0)

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--yolo", "-y"):
            args["yolo"] = True
        elif a in ("--target", "-t"):
            if i + 1 >= len(argv):
                print("错误: --target/-t 需要参数", file=sys.stderr)
                sys.exit(2)
            args["target"] = argv[i + 1]
            i += 1
        elif a == "--mode":
            if i + 1 >= len(argv):
                print("错误: --mode 需要参数", file=sys.stderr)
                sys.exit(2)
            mode = argv[i + 1]
            if mode not in VALID_MODES:
                print(
                    f"错误: --mode 必须是 {' | '.join(VALID_MODES)}（当前: {mode}）",
                    file=sys.stderr,
                )
                sys.exit(2)
            args["mode"] = mode
            i += 1
        elif a == "--model":
            if i + 1 >= len(argv):
                print("错误: --model 需要参数", file=sys.stderr)
                sys.exit(2)
            args["model"] = argv[i + 1]
            i += 1
        elif a == "--doctor":
            args["doctor"] = True
        i += 1

    if args["mode"] != "recon" and args["target"] is None:
        print("错误: --mode 需配合 --target/-t 使用", file=sys.stderr)
        sys.exit(2)
    return args


async def main() -> None:
    """主函数：初始化并运行 CLI 交互循环。"""
    from utils.paths import ensure_dirs

    cli_args = _parse_cli_args()
    ensure_dirs()  # 确保 ~/.argus/ 目录结构存在

    # Day3-3: --doctor 单独分支：跑完体检退出
    if cli_args.get("doctor"):
        from agent.doctor import run_doctor_async

        ok = await run_doctor_async(ping_llm=True, silent_unless_failure=False)
        sys.exit(0 if ok else 1)

    # 一次性迁移旧 SQLite 记忆到 MD 文件（无副作用，已迁移过会跳过）
    try:
        from agent.memory_migrate import migrate_once

        await migrate_once()
    except Exception as e:
        log_warning(f"记忆迁移跳过: {e}")

    config = load_config()

    general = config.get("general", {})
    model = cli_args.get("model") or general.get("default_model", "deepseek/deepseek-chat")
    approval_mode = general.get("approval_mode", True)

    # CLI --yolo / --target / stdin 非 TTY：自动跳过审批，避免卡死（issue #6 / #8）
    is_non_tty = not sys.stdin.isatty()
    is_oneshot = cli_args.get("target") is not None
    if cli_args["yolo"] or is_non_tty or is_oneshot:
        if approval_mode:
            reason = (
                "--yolo CLI flag"
                if cli_args["yolo"]
                else ("--target one-shot" if is_oneshot else "non-interactive stdin")
            )
            log_warning(f"approval_mode=False enforced ({reason})")
        approval_mode = False
    verbose = general.get("verbose", True)
    tool_timeout = general.get("tool_timeout", 60)
    max_retries = general.get("max_retries", 2)
    log_to_file = general.get("log_to_file", True)
    context_max_tokens = general.get("context_max_tokens", 200000)

    api_keys = config.get("api_keys", {})
    api_bases = config.get("api_bases", {})
    security = config.get("security", {})
    allowed_domains = security.get("allowed_domains", [])
    tool_allowlist = security.get("tool_allowlist", [])
    tool_blocklist = security.get("tool_blocklist", [])
    require_approval_for = security.get("require_approval_for", [])

    # 自演化（A1+）配置
    skills_cfg = config.get("skills", {})
    track_skill_usage = skills_cfg.get("track_usage", True)
    auto_extract_skills = skills_cfg.get("auto_extract", False)
    memory_cfg = config.get("memory", {})
    track_lessons = memory_cfg.get("track_lessons", True)
    track_failure_replays = memory_cfg.get("track_failure_replays", False)

    # 启用文件日志
    if log_to_file:
        file_logger.enable()

    # 初始化 LLM 客户端
    llm = LLMClient(model=model, api_keys=api_keys, api_bases=api_bases)

    # 初始化 Agent 引擎
    engine = AgentEngine(
        llm=llm,
        registry=registry,
        approval_mode=approval_mode,
        verbose=verbose,
        tool_timeout=tool_timeout,
        max_retries=max_retries,
        allowed_domains=allowed_domains,
        context_max_tokens=context_max_tokens,
        tool_allowlist=tool_allowlist,
        tool_blocklist=tool_blocklist,
        require_approval_for=require_approval_for,
        track_skill_usage=track_skill_usage,
        track_lessons=track_lessons,
        auto_extract_skills=auto_extract_skills,
        track_failure_replays=track_failure_replays,
    )

    print_banner(model)

    # issue #8：一键侦察模式 —— 跑完 prompt 即退出，不进入 REPL
    if cli_args.get("target"):
        from agent.recon_modes import render_prompt

        oneshot_prompt = render_prompt(cli_args["target"], cli_args["mode"])
        log_info(f"一键侦察模式 [{cli_args['mode']}] target={cli_args['target']}")
        try:
            result = await engine.run(oneshot_prompt)
            console.print(result)
        except KeyboardInterrupt:
            log_warning("任务被用户中断")
        except Exception as e:
            log_error(f"一键侦察失败: {e}")
        finally:
            with contextlib.suppress(Exception):
                from tools.browser import close_browser

                await close_browser()
            file_logger.close()
        return

    # prompt_toolkit 会话（历史 + 补全）
    prompt_session = create_prompt_session()
    session_stats = SessionStats()

    # 交互循环
    while True:
        try:
            mode = "yolo" if not engine.approval_mode else "agent"
            prompt = get_prompt_text(model=engine.llm.model, mode=mode)

            def _read_prompt(p: Any = prompt) -> str:
                return prompt_session.prompt(p)

            user_input = await asyncio.get_event_loop().run_in_executor(None, _read_prompt)
            user_input = user_input.strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见！")
            break

        if not user_input:
            continue

        # 命令处理
        if user_input.startswith("/"):
            if user_input.strip() == "/cost":
                console.print(f"  {session_stats.format()}", style="dim")
                continue
            should_continue = await handle_command(user_input, engine)
            if not should_continue:
                console.print("再见！")
                break
            continue

        # 正常任务：运行 Agent（流式渲染）+ ESC 中断监听
        ui = None
        try:
            ui = LiveUI(console, model=engine.llm.model)
            ui.start()

            from utils.interrupt import EscInterruptListener

            _loop = asyncio.get_event_loop()
            _cancel_event = asyncio.Event()

            def _on_esc(loop=_loop, ev=_cancel_event) -> None:  # type: ignore[no-untyped-def]
                loop.call_soon_threadsafe(ev.set)

            esc_listener = EscInterruptListener(on_press=_on_esc)
            esc_listener.start()
            run_task = asyncio.create_task(engine.run_stream(user_input, ui=ui))
            cancel_task = asyncio.create_task(_cancel_event.wait())
            try:
                _done, _pending = await asyncio.wait(
                    {run_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if _cancel_event.is_set() and not run_task.done():
                    run_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await run_task
                    if ui and ui._live:
                        ui.stop()
                    log_warning("已按 ESC 中断 — 上下文已保存，可继续对话")
                else:
                    # 自然完成：取消 cancel_task 释放资源
                    cancel_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await cancel_task
                    # 累积统计
                    session_stats.add_turn(
                        engine.llm.model,
                        ui._input_tokens,
                        ui._output_tokens,
                        cache_hit=ui._cache_hit_tokens,
                        cache_miss=ui._cache_miss_tokens,
                    )
            finally:
                esc_listener.stop()
        except KeyboardInterrupt:
            if ui and ui._live:
                ui.stop()
            log_warning("任务被用户中断")
        except ArgusError as e:
            # 结构化错误：友好展示，不打印 traceback
            if ui and ui._live:
                ui.stop()
            console.print(f"[red]✗ {e}[/red]")
            if not e.recoverable:
                console.print("[dim]提示: 此错误不可恢复，请检查配置或 API 状态后重启[/dim]")
        except Exception as e:
            if ui and ui._live:
                ui.stop()
            log_error(f"执行异常: {e}")

    # 清理资源
    with contextlib.suppress(Exception):
        from tools.browser import close_browser

        await close_browser()
    file_logger.close()


def cli_entry():
    """包安装后的 CLI 入口点：argus 命令。"""
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
    except SystemExit:
        pass


if __name__ == "__main__":
    cli_entry()
