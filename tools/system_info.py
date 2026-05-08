"""系统信息工具：net_info（网络只读查询）+ system_exec（受限 shell 执行）。

为什么需要：

侦察 Agent 在很多场景需要"先了解自己所在的环境"——本机网络配置、当前进程、
git 仓库状态等。如果完全没有 shell 通道，LLM 只能靠浏览器 / HTTP 兜圈子，
最终烧大量 token 仍无解（曾经一次"取本机局域网 IP"消耗 330K token / ¥0.35
后才回答"你自己开终端查"）。

设计原则：

  1. **net_info**——零风险只读查询，硬编码命令白名单，LLM 只能传 action enum，
     不接受任意 shell 字符串。risk = safe，自动执行。

  2. **system_exec**——可执行任意 shell 命令，但必须满足三道门：
        a. config.toml `[tools.system_exec] enabled = true`，否则永远拒绝
        b. 命令必须在 `allowed_commands` 白名单内
        c. ``shell=False`` + 命令以 list 拼装，杜绝 shell 元字符注入
     再叠加 60s 超时、8KB 输出截断、强制审批。risk = confirm。
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import shutil
from typing import Final

from agent.tool_registry import registry
from utils.logger import log_warning
from utils.sanitizer import truncate

# ──────────────────────────────────────────────────────────────────────────
# net_info：跨平台只读网络查询
# ──────────────────────────────────────────────────────────────────────────

# (system, action) -> [executable, *args]
# 命令完全硬编码，LLM 不能注入任何参数。
_NET_INFO_COMMANDS: Final[dict[tuple[str, str], list[str]]] = {
    # Windows
    ("Windows", "interfaces"): ["ipconfig", "/all"],
    ("Windows", "routes"): ["route", "print"],
    ("Windows", "connections"): ["netstat", "-ano"],
    ("Windows", "arp"): ["arp", "-a"],
    ("Windows", "dns"): ["ipconfig", "/all"],  # DNS 服务器同样从 ipconfig 解析
    # Linux
    ("Linux", "interfaces"): ["ip", "addr"],
    ("Linux", "routes"): ["ip", "route"],
    ("Linux", "connections"): ["ss", "-tunap"],
    ("Linux", "arp"): ["ip", "neigh"],
    ("Linux", "dns"): ["cat", "/etc/resolv.conf"],
    # macOS
    ("Darwin", "interfaces"): ["ifconfig", "-a"],
    ("Darwin", "routes"): ["netstat", "-rn"],
    ("Darwin", "connections"): ["netstat", "-an"],
    ("Darwin", "arp"): ["arp", "-a"],
    ("Darwin", "dns"): ["scutil", "--dns"],
}

_NET_INFO_VALID_ACTIONS: Final[tuple[str, ...]] = (
    "interfaces",
    "routes",
    "connections",
    "arp",
    "dns",
)


@registry.tool(
    name="net_info",
    description=(
        "查询本机网络信息（只读、跨平台、零风险）。LLM 只能传 action 枚举，"
        "不接受任意 shell 命令。可选 action："
        "interfaces（网卡 IP/MAC/网关）/ routes（路由表）/ "
        "connections（TCP/UDP 连接）/ arp（ARP 缓存）/ dns（本机 DNS 服务器）。"
    ),
    params={
        "action": {
            "type": "string",
            "description": "interfaces / routes / connections / arp / dns",
        },
    },
)
async def net_info(action: str) -> str:
    act = (action or "").strip().lower()
    if act not in _NET_INFO_VALID_ACTIONS:
        return (
            f"未知 action {action!r}。可用："
            f"{' / '.join(_NET_INFO_VALID_ACTIONS)}"
        )

    system = platform.system()
    cmd = _NET_INFO_COMMANDS.get((system, act))
    if cmd is None:
        return f"当前平台 {system!r} 不支持 net_info action {act!r}"

    # 命令存在性预检：避免 FileNotFoundError 又回退到通用 [TOOL_ERROR]
    if shutil.which(cmd[0]) is None:
        return f"命令 {cmd[0]!r} 不在 PATH 中（{system}）。可能需要安装相应工具。"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return "net_info 执行超时（15s）"
    except FileNotFoundError as e:
        return f"命令不存在: {' '.join(cmd)} ({e})"
    except Exception as e:
        return f"net_info 执行失败: {type(e).__name__}: {e}"

    out_text = stdout.decode("utf-8", errors="replace")
    err_text = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return (
            f"命令退出码 {proc.returncode}\n"
            f"--- stderr ---\n{truncate(err_text, max_len=2000)}\n"
            f"--- stdout ---\n{truncate(out_text, max_len=4000)}"
        )
    return f"$ {' '.join(cmd)}\n{truncate(out_text, max_len=8000)}"


# ──────────────────────────────────────────────────────────────────────────
# system_exec：受限 shell 命令执行
# ──────────────────────────────────────────────────────────────────────────

# 默认命令白名单（只读类查询为主）。可在 config.toml [tools.system_exec] 覆盖。
_DEFAULT_ALLOWED_COMMANDS: Final[tuple[str, ...]] = (
    # 身份/环境
    "whoami", "hostname", "uname", "ver", "id", "uptime", "date",
    "echo", "env", "set", "printenv",
    # 文件查看（不修改）
    "pwd", "ls", "dir", "tree", "type", "cat", "head", "tail",
    "wc", "where", "which", "stat", "file",
    # 进程/资源
    "ps", "tasklist", "top", "df", "du", "free", "vmstat",
    # 开发者工具（只读子命令由 LLM 配合，但工具层只校验主命令）
    "git", "python", "python3", "node", "npm", "pip", "go", "rustc",
    # 文本处理（只读）
    "sort", "uniq", "grep", "findstr", "awk", "sed",
)


def _load_system_exec_config() -> tuple[bool, frozenset[str]]:
    """读取 config.toml [tools.system_exec]。返回 (enabled, allowed_commands)。

    任意异常都退回安全默认值 (False, 默认白名单)。"""
    try:
        from utils.config import get_section

        section = get_section("tools").get("system_exec", {})
        enabled = bool(section.get("enabled", False))
        allowed = section.get("allowed_commands")
        if isinstance(allowed, list) and allowed:
            return enabled, frozenset(str(x).strip() for x in allowed if x)
        return enabled, frozenset(_DEFAULT_ALLOWED_COMMANDS)
    except Exception:
        return False, frozenset(_DEFAULT_ALLOWED_COMMANDS)


@registry.tool(
    name="system_exec",
    description=(
        "在本机执行受限的 shell 命令（默认 disabled，需在 config.toml "
        "[tools.system_exec] enabled=true 开启）。命令必须在白名单内，"
        "shell 元字符（&、|、;、$()、反引号）不会被解析（shell=False）。"
        "用于：查 git 状态、看进程列表、读本地文件等系统级查询。"
    ),
    params={
        "command": {
            "type": "string",
            "description": "命令名（不含参数），必须在白名单内，如 'git' / 'ps' / 'whoami'",
        },
        "args": {
            "type": "array",
            "description": "命令参数列表，每项一个字符串，如 ['status','--short']",
            "items": {"type": "string"},
            "required": False,
        },
    },
)
async def system_exec(command: str, args: list[str] | None = None) -> str:
    enabled, allowed = _load_system_exec_config()
    if not enabled:
        return (
            "system_exec 未启用。如需开启，在 config.toml 添加：\n"
            "  [tools.system_exec]\n"
            "  enabled = true\n"
            "  # allowed_commands = [\"whoami\", \"git\", ...]   # 可选自定义白名单"
        )

    cmd_name = (command or "").strip()
    if not cmd_name:
        return "command 不能为空"
    # 只取第一个 token，杜绝 LLM 把整条命令塞进 command 字段绕过白名单
    cmd_name = cmd_name.split()[0]
    if cmd_name not in allowed:
        return (
            f"命令 {cmd_name!r} 不在白名单内。当前允许：\n"
            f"  {', '.join(sorted(allowed))}"
        )

    if shutil.which(cmd_name) is None:
        return f"命令 {cmd_name!r} 不在 PATH 中"

    arg_list: list[str] = []
    if args:
        for a in args:
            if not isinstance(a, str):
                return f"args 中存在非字符串项: {a!r}"
            arg_list.append(a)

    full_cmd = [cmd_name, *arg_list]
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return "system_exec 执行超时（60s）"
    except FileNotFoundError as e:
        return f"命令不存在: {full_cmd!r} ({e})"
    except PermissionError as e:
        log_warning(f"system_exec 权限拒绝: {e}")
        return f"权限被拒绝: {e}"
    except Exception as e:
        return f"system_exec 执行失败: {type(e).__name__}: {e}"

    out_text = stdout.decode("utf-8", errors="replace")
    err_text = stderr.decode("utf-8", errors="replace")
    head = f"$ {' '.join(full_cmd)}  (exit={proc.returncode})"
    body = truncate(out_text, max_len=8000)
    if proc.returncode != 0 and err_text.strip():
        body += f"\n--- stderr ---\n{truncate(err_text, max_len=2000)}"
    return f"{head}\n{body}"
