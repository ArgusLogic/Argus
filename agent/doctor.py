"""Day3-3: Argus doctor — 启动前体检脚本。

非侵入：跑完打一张 markdown 表，所有检查项都尽量"快、轻、不联网"。
唯一可选的网络项是 LLM provider 连通性 ping（仅当用户配了 key 才发一个最小请求）。

API:
    from agent.doctor import run_doctor
    summary = run_doctor()  # dict
    # or:
    text = render_doctor_report()  # markdown string

CLI: `python main.py --doctor` 单跑此脚本，正常启动时静默执行（仅失败才打印）。
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    optional: bool = False  # optional=True 失败时显示 "ⓘ" 而非 "✗"


# ──────────────────────────────────────────────────────────────────────────
# 单项检查
# ──────────────────────────────────────────────────────────────────────────


def _check_python() -> CheckResult:
    v = sys.version.split()[0]
    ok = sys.version_info >= (3, 11)
    return CheckResult(
        name="Python",
        ok=ok,
        detail=f"{v} ({platform.platform()})",
    )


def _check_dependency(module: str, friendly: str | None = None) -> CheckResult:
    label = friendly or module
    try:
        m = __import__(module)
        version = getattr(m, "__version__", "unknown")
        return CheckResult(name=label, ok=True, detail=f"v{version}")
    except ImportError as e:
        return CheckResult(name=label, ok=False, detail=str(e))


def _check_playwright_chromium() -> CheckResult:
    try:
        from playwright._impl._driver import compute_driver_executable

        compute_driver_executable()  # 触发 path 解析
        # 检查浏览器是否安装：playwright/.local-browsers/chromium-*
        cache_dir = Path.home() / "AppData" / "Local" / "ms-playwright"
        if not cache_dir.exists():
            cache_dir = Path.home() / ".cache" / "ms-playwright"
        if cache_dir.exists() and any(cache_dir.glob("chromium-*")):
            return CheckResult(name="Playwright Chromium", ok=True, detail="installed")
        return CheckResult(
            name="Playwright Chromium",
            ok=False,
            detail="未安装；运行 `playwright install chromium`",
            optional=True,
        )
    except Exception as e:
        return CheckResult(name="Playwright Chromium", ok=False, detail=str(e), optional=True)


def _check_nmap() -> CheckResult:
    nmap_path = shutil.which("nmap")
    if nmap_path:
        try:
            out = subprocess.run(
                [nmap_path, "--version"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.split("\n", 1)[0]
            return CheckResult(name="nmap", ok=True, detail=f"{out.strip()}  @ {nmap_path}")
        except Exception:
            return CheckResult(name="nmap", ok=True, detail=f"@ {nmap_path}")
    return CheckResult(
        name="nmap",
        ok=False,
        detail="未安装（端口扫描会回退到 TCP connect 兜底）",
        optional=True,
    )


def _mask_key(key: str) -> str:
    if not key:
        return "(空)"
    if len(key) <= 12:
        return key[:3] + "..."
    return f"{key[:6]}...{key[-4:]}"


def _check_provider_keys() -> list[CheckResult]:
    """检查 config 中各 provider 的 key 是否配置。"""
    out: list[CheckResult] = []
    try:
        from utils.config import get_section

        keys = get_section("api_keys")
    except Exception as e:
        return [CheckResult(name="Config 读取", ok=False, detail=str(e))]

    provider_labels = {
        "deepseek": "DeepSeek key",
        "openai": "OpenAI key",
        "anthropic": "Anthropic key",
        "xiaomi_mimo": "Xiaomi MiMo key",
    }
    any_configured = False
    for k, label in provider_labels.items():
        v = (keys.get(k) or "").strip()
        if v:
            any_configured = True
            out.append(CheckResult(name=label, ok=True, detail=_mask_key(v)))
        else:
            out.append(
                CheckResult(name=label, ok=False, detail="未配置", optional=True)
            )
    if not any_configured:
        out.append(
            CheckResult(
                name="LLM Provider 总览",
                ok=False,
                detail="至少需配置一个 provider key 才能跑 LLM",
                optional=False,
            )
        )
    return out


def _check_argus_home_writable() -> CheckResult:
    try:
        from utils.paths import SECAGENT_HOME

        p = Path(SECAGENT_HOME)
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".doctor_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult(name="~/.argus 可写", ok=True, detail=str(p))
    except Exception as e:
        return CheckResult(name="~/.argus 可写", ok=False, detail=str(e))


def _check_wordlists() -> list[CheckResult]:
    """检查内置子域 / 目录字典加载正常。"""
    try:
        from tools.recon_wordlists import DIRECTORIES, SUBDOMAINS

        out = [
            CheckResult(
                name="子域字典", ok=len(SUBDOMAINS) >= 1000,
                detail=f"{len(SUBDOMAINS)} 条",
            ),
            CheckResult(
                name="目录字典", ok=len(DIRECTORIES) >= 100,
                detail=f"{len(DIRECTORIES)} 条",
            ),
        ]
        return out
    except Exception as e:
        return [CheckResult(name="字典加载", ok=False, detail=str(e))]


def _check_default_model() -> CheckResult:
    try:
        from utils.config import get_section

        model = get_section("general").get("default_model", "")
        if not model:
            return CheckResult(name="默认模型", ok=False, detail="config.toml 未指定 default_model")
        return CheckResult(name="默认模型", ok=True, detail=model)
    except Exception as e:
        return CheckResult(name="默认模型", ok=False, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────


def collect_checks(*, ping_llm: bool = False) -> list[CheckResult]:
    """收集所有体检项。ping_llm=True 时额外做一次最小 LLM 调用（耗时 1-3s）。"""
    checks: list[CheckResult] = []
    checks.append(_check_python())
    checks.append(_check_dependency("httpx"))
    checks.append(_check_dependency("playwright"))
    checks.append(_check_dependency("litellm"))
    checks.append(_check_dependency("rich"))
    checks.append(_check_dependency("nmap", "python-nmap"))
    checks.append(_check_playwright_chromium())
    checks.append(_check_nmap())
    checks.append(_check_argus_home_writable())
    checks.append(_check_default_model())
    checks.extend(_check_provider_keys())
    checks.extend(_check_wordlists())

    if ping_llm:
        checks.append(_ping_default_model())

    return checks


async def _ping_default_model_async() -> CheckResult:
    """异步版本：在已有 event loop 里调用。"""
    try:
        from agent.llm_client import LLMClient
        from utils.config import get_section

        model = get_section("general").get("default_model", "")
        if not model:
            return CheckResult(name="LLM ping", ok=False, detail="无默认模型，跳过", optional=True)
        keys = get_section("api_keys")
        bases = get_section("api_bases")
        llm = LLMClient(model=model, api_keys=keys, api_bases=bases)
        resp: Any = await llm.chat([{"role": "user", "content": "ping"}])
        out = (resp.choices[0].message.content or "")[:30]
        return CheckResult(name=f"LLM ping ({model})", ok=True, detail=f"reply: {out!r}")
    except Exception as e:
        return CheckResult(name="LLM ping", ok=False, detail=str(e)[:120], optional=True)


def _ping_default_model() -> CheckResult:
    """同步包装：当无活跃 loop 时启 asyncio.run；已有 loop 则跳过。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 无活跃 loop，可以安全用 asyncio.run
        try:
            return asyncio.run(_ping_default_model_async())
        except Exception as e:
            return CheckResult(name="LLM ping", ok=False, detail=str(e)[:120], optional=True)
    # 已在 loop 中：调用方应改用 collect_checks_async / _ping_default_model_async
    return CheckResult(
        name="LLM ping",
        ok=False,
        detail="已在 event loop 中；调用方请用 collect_checks_async()",
        optional=True,
    )


async def collect_checks_async(*, ping_llm: bool = False) -> list[CheckResult]:
    """异步版 collect_checks：在已有 loop 中也能跑 LLM ping。"""
    checks = collect_checks(ping_llm=False)
    if ping_llm:
        checks.append(await _ping_default_model_async())
    return checks


async def run_doctor_async(
    *, ping_llm: bool = False, silent_unless_failure: bool = False
) -> bool:
    checks = await collect_checks_async(ping_llm=ping_llm)
    has_blocking = any(not c.ok and not c.optional for c in checks)
    if has_blocking or not silent_unless_failure:
        print(render_doctor_report(checks))
    return not has_blocking


def render_doctor_report(checks: list[CheckResult]) -> str:
    """把 check 列表渲染成可视化文本（无 Rich，纯 ASCII 兼容）。"""
    lines: list[str] = []
    lines.append("Argus doctor")
    lines.append("─" * 50)
    blocking_failures: list[str] = []
    for c in checks:
        if c.ok:
            mark = "✓"
        elif c.optional:
            mark = "ⓘ"
        else:
            mark = "✗"
            blocking_failures.append(c.name)
        lines.append(f"  {mark}  {c.name:<28} {c.detail}")
    lines.append("─" * 50)
    if blocking_failures:
        lines.append("⚠ 阻塞项: " + ", ".join(blocking_failures))
        lines.append("Argus 在上述项目修复前可能无法正常工作。")
    else:
        lines.append("Ready. 启动 `python main.py` 进入交互模式。")
    return "\n".join(lines)


def run_doctor(*, ping_llm: bool = False, silent_unless_failure: bool = False) -> bool:
    """执行体检并打印；返回 True 表示无阻塞失败。

    silent_unless_failure=True：所有项都过则不打印（启动时静默体检）。
    """
    checks = collect_checks(ping_llm=ping_llm)
    has_blocking = any(not c.ok and not c.optional for c in checks)
    if has_blocking or not silent_unless_failure:
        print(render_doctor_report(checks))
    return not has_blocking


def has_blocking_failures(checks: list[CheckResult]) -> bool:
    return any(not c.ok and not c.optional for c in checks)
