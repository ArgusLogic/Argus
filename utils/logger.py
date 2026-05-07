"""统一日志模块，基于 rich 提供彩色终端输出，同时支持文件日志。"""

import contextlib
import os
from datetime import datetime

from rich.console import Console
from rich.theme import Theme

custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "tool": "bold green",
        "agent": "bold magenta",
        "user": "bold blue",
    }
)

console = Console(theme=custom_theme)


class FileLogger:
    """将日志同时写入文件（纯文本，无 ANSI 颜色）。"""

    def __init__(self):
        self._file = None
        self._enabled = False

    def enable(self, log_dir: str | None = None) -> None:
        """启用文件日志。"""
        if log_dir is None:
            from utils.paths import LOGS_DIR

            log_dir = LOGS_DIR
        os.makedirs(log_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        filepath = os.path.join(log_dir, f"argus_{date_str}.log")
        # FileLogger 持有长期文件句柄，故不使用 with 语句
        self._file = open(filepath, "a", encoding="utf-8")  # noqa: SIM115
        self._enabled = True
        self.write("INFO", f"日志文件已打开: {filepath}")

    def write(self, level: str, msg: str) -> None:
        """写一行日志到文件。"""
        if not self._enabled or not self._file:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with contextlib.suppress(Exception):
            self._file.write(f"[{timestamp}] [{level}] {msg}\n")
            self._file.flush()

    def close(self) -> None:
        """关闭日志文件。"""
        if self._file:
            with contextlib.suppress(Exception):
                self._file.close()
            self._file = None
            self._enabled = False


# 全局文件日志实例
file_logger = FileLogger()

# 全局 Live 引用：流式渲染期间设置此项，让日志输出也走 Live console
_active_live = None


def set_active_live(live) -> None:
    """流式渲染期间设置活跃的 Live 对象。"""
    global _active_live
    _active_live = live


def _get_console() -> Console:
    """获取当前应使用的 Console（普通 or Live 内的）。"""
    if _active_live and _active_live.is_started:
        return _active_live.console
    return console


def log_info(msg: str) -> None:
    _get_console().print(f"[info][*] {msg}[/info]")
    file_logger.write("INFO", msg)


def log_warning(msg: str) -> None:
    _get_console().print(f"[warning][!] {msg}[/warning]")
    file_logger.write("WARN", msg)


def log_error(msg: str) -> None:
    _get_console().print(f"[error][✗] {msg}[/error]")
    file_logger.write("ERROR", msg)


def log_tool(name: str, msg: str) -> None:
    _get_console().print(f"[tool][Tool] {name}[/tool] → {msg}")
    file_logger.write("TOOL", f"{name} → {msg}")


def log_agent(msg: str) -> None:
    _get_console().print(f"[agent][Agent][/agent] {msg}")
    file_logger.write("AGENT", msg)


def log_user(msg: str) -> None:
    _get_console().print(f"[user][You][/user] {msg}")
    file_logger.write("USER", msg)
