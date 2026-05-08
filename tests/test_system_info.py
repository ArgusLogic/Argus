"""net_info / system_exec 工具测试。

策略：
- net_info: 在 Windows / Linux / macOS 三平台都跑一个 action（"interfaces"），
  断言不抛异常 + 输出非空 + 含命令头 "$ "；其余 action 至少跑一次走完代码路径。
- system_exec: 重点测三道安全门 + 真实跑 whoami（开关开启时）。
"""

from __future__ import annotations

import asyncio
import platform
import shutil

import pytest

import tools.system_info as sysinfo

pytestmark = pytest.mark.asyncio


# ─── net_info ───────────────────────────────────────────────────────────────


async def test_net_info_interfaces_returns_output() -> None:
    """interfaces 必须能在当前平台跑通。如缺命令则跳过（CI 容器可能精简）。"""
    cmd = sysinfo._NET_INFO_COMMANDS.get((platform.system(), "interfaces"))
    if cmd is None or shutil.which(cmd[0]) is None:
        pytest.skip(f"{cmd[0] if cmd else '?'} 不在 PATH")

    out = await sysinfo.net_info("interfaces")
    assert out.startswith("$ ") or "命令" in out
    assert len(out) > 50  # 至少有些内容


async def test_net_info_unknown_action() -> None:
    out = await sysinfo.net_info("magic_action")
    assert "未知 action" in out
    assert "interfaces" in out  # 给出可用列表


async def test_net_info_empty_action() -> None:
    out = await sysinfo.net_info("")
    assert "未知 action" in out


async def test_net_info_action_is_lowercased() -> None:
    """action 应大小写不敏感。"""
    cmd = sysinfo._NET_INFO_COMMANDS.get((platform.system(), "interfaces"))
    if cmd is None or shutil.which(cmd[0]) is None:
        pytest.skip("命令不在 PATH")
    out = await sysinfo.net_info("INTERFACES")
    assert "未知 action" not in out


async def test_net_info_does_not_accept_shell_metachars() -> None:
    """LLM 不能通过 action 注入 shell；非白名单 action 直接拒绝。"""
    out = await sysinfo.net_info("interfaces; rm -rf /")
    assert "未知 action" in out


# ─── system_exec 三道门 ─────────────────────────────────────────────────────


async def test_system_exec_disabled_by_default(monkeypatch) -> None:
    """门 1：默认 disabled。"""
    monkeypatch.setattr(sysinfo, "_load_system_exec_config", lambda: (False, frozenset()))
    out = await sysinfo.system_exec("whoami")
    assert "未启用" in out
    assert "enabled = true" in out


async def test_system_exec_blocks_unlisted_command(monkeypatch) -> None:
    """门 2：命令不在白名单。"""
    monkeypatch.setattr(
        sysinfo,
        "_load_system_exec_config",
        lambda: (True, frozenset({"whoami", "ls"})),
    )
    out = await sysinfo.system_exec("rm")
    assert "不在白名单" in out


async def test_system_exec_strips_command_prefix(monkeypatch) -> None:
    """LLM 不能把整条命令塞进 command 字段绕过白名单。
    例如 command='git status' 应只校验 'git'。"""
    monkeypatch.setattr(
        sysinfo,
        "_load_system_exec_config",
        lambda: (True, frozenset({"whoami"})),  # git 不在白名单
    )
    # 把整条命令塞进 command 字段
    out = await sysinfo.system_exec("git status --short")
    assert "不在白名单" in out
    # 关键：被截断的部分（'status --short'）不应该被 split 后当成 args 偷偷执行
    assert "git" in out  # 提示信息应包含被拒绝的主命令名


async def test_system_exec_runs_whitelisted_command(monkeypatch) -> None:
    """门 3 之后正常执行：跑 whoami（所有平台都有），断言 exit=0 + 有输出。"""
    if shutil.which("whoami") is None:
        pytest.skip("whoami 不在 PATH")
    monkeypatch.setattr(
        sysinfo,
        "_load_system_exec_config",
        lambda: (True, frozenset({"whoami"})),
    )
    out = await sysinfo.system_exec("whoami")
    assert out.startswith("$ whoami  (exit=0)")
    # 输出非空（不同平台格式不一样：DOMAIN\user 或 user）
    assert len(out.split("\n", 1)[1].strip()) > 0


async def test_system_exec_args_must_be_strings(monkeypatch) -> None:
    monkeypatch.setattr(
        sysinfo,
        "_load_system_exec_config",
        lambda: (True, frozenset({"whoami"})),
    )
    out = await sysinfo.system_exec("whoami", args=[123])  # type: ignore[list-item]
    assert "args 中存在非字符串项" in out


async def test_system_exec_shell_metachars_not_interpreted(monkeypatch) -> None:
    """args 里的 shell 元字符应被视为字面量，不会触发 shell 解析。

    实测：shutil.which 找不到带元字符的"命令"。即使绕过 which，
    shell=False 也保证 ; / | / && 不被解析。这里通过白名单即可拦下。
    """
    monkeypatch.setattr(
        sysinfo,
        "_load_system_exec_config",
        lambda: (True, frozenset({"whoami"})),
    )
    # 元字符塞进 command → 主命令变成 'whoami;ls' → 不在白名单
    out = await sysinfo.system_exec("whoami;ls")
    assert "不在白名单" in out


# ─── config 读取 ────────────────────────────────────────────────────────────


async def test_load_config_falls_back_to_safe_defaults() -> None:
    """utils.config 无该 section 时退回 (False, 默认白名单)。"""
    # 真实读 config（依赖项目根 config.toml 不含 [tools.system_exec]）
    _enabled, allowed = sysinfo._load_system_exec_config()
    # 不强求 enabled 一定为 False（用户可能开了），但白名单永远是 frozenset
    assert isinstance(allowed, frozenset)
    assert len(allowed) > 0
    assert "whoami" in allowed


async def test_default_whitelist_contains_safe_commands() -> None:
    """默认白名单只含查询/只读类命令，不含 rm/del/format 等危险命令。"""
    safe = set(sysinfo._DEFAULT_ALLOWED_COMMANDS)
    for danger in ("rm", "del", "format", "mkfs", "shutdown", "reboot", "kill", "taskkill"):
        assert danger not in safe, f"危险命令 {danger!r} 不应出现在默认白名单"


# ─── 集成 ───────────────────────────────────────────────────────────────────


async def test_tools_registered() -> None:
    """两个工具都应已注册（导入 tools.system_info 触发 @registry.tool 装饰器）。"""
    from agent.tool_registry import registry

    names = registry.list_tools()
    assert "net_info" in names
    assert "system_exec" in names


async def test_risk_levels_registered() -> None:
    """engine.TOOL_RISK_LEVELS 必须包含两个新工具，且等级符合预期。"""
    from agent.engine import TOOL_RISK_LEVELS

    assert TOOL_RISK_LEVELS.get("net_info") == "safe"
    assert TOOL_RISK_LEVELS.get("system_exec") == "block"
