"""结构化异常体系。

设计原则：
- 所有 Argus 内部错误继承 ArgusError，外层（main loop）可统一捕获并友好展示
- 每个错误带 code 和 recoverable 标志，便于上层决策（重试 / 中止 / 提示用户）
- 错误信息面向用户（中文，可直接 console.print）；技术细节用 repr() 暴露给日志
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArgusError(Exception):
    """Argus 通用错误基类。"""

    message: str
    code: str = "ARGUS_ERROR"
    recoverable: bool = True

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# ─── 工具执行类 ────────────────────────────────────────────────────────


@dataclass
class ToolError(ArgusError):
    """工具执行通用错误。"""

    tool_name: str = ""
    code: str = "TOOL_ERROR"

    def __str__(self) -> str:
        prefix = f"工具 {self.tool_name} " if self.tool_name else "工具"
        return f"[{self.code}] {prefix}执行失败: {self.message}"


@dataclass
class ToolTimeout(ToolError):
    """工具执行超时。"""

    timeout_seconds: int = 0
    code: str = "TOOL_TIMEOUT"
    recoverable: bool = True

    def __str__(self) -> str:
        prefix = f"工具 {self.tool_name} " if self.tool_name else "工具"
        return f"[{self.code}] {prefix}执行超时 ({self.timeout_seconds}s): {self.message}"


@dataclass
class ToolNotFound(ArgusError):
    """LLM 请求了未注册的工具。"""

    tool_name: str = ""
    code: str = "TOOL_NOT_FOUND"
    recoverable: bool = False

    def __str__(self) -> str:
        return f"[{self.code}] 未知工具: {self.tool_name}"


# ─── 安全 / 审批类 ─────────────────────────────────────────────────────


@dataclass
class SecurityBlock(ArgusError):
    """工具调用被安全策略拦截（白名单 / 域名黑名单 / 审批拒绝）。"""

    reason: str = ""
    code: str = "SECURITY_BLOCK"
    recoverable: bool = False

    def __str__(self) -> str:
        return (
            f"[{self.code}] 操作被拦截: {self.message} (原因: {self.reason})"
            if self.reason
            else f"[{self.code}] {self.message}"
        )


@dataclass
class UserRejected(ArgusError):
    """用户在审批环节拒绝。"""

    code: str = "USER_REJECTED"
    recoverable: bool = False


# ─── LLM API 类 ───────────────────────────────────────────────────────


@dataclass
class LLMError(ArgusError):
    """LLM 调用通用错误。"""

    code: str = "LLM_ERROR"


@dataclass
class APIBalanceError(LLMError):
    """API 余额不足或配额耗尽。"""

    code: str = "API_BALANCE"
    recoverable: bool = False


@dataclass
class APIRateLimit(LLMError):
    """触发 API 速率限制。"""

    code: str = "API_RATE_LIMIT"
    recoverable: bool = True


@dataclass
class APIAuthError(LLMError):
    """API Key 无效或权限不足。"""

    code: str = "API_AUTH"
    recoverable: bool = False


# ─── 配置 / 数据类 ─────────────────────────────────────────────────────


@dataclass
class ConfigError(ArgusError):
    """配置加载或校验失败。"""

    code: str = "CONFIG_ERROR"
    recoverable: bool = False


@dataclass
class MemoryFullError(ArgusError):
    """记忆容量已满。"""

    target: str = ""
    used: int = 0
    cap: int = 0
    code: str = "MEMORY_FULL"
    recoverable: bool = True

    def __str__(self) -> str:
        return f"[{self.code}] 记忆 [{self.target}] 已满 ({self.used}/{self.cap}): {self.message}"


# ─── 辅助工具 ──────────────────────────────────────────────────────────


def classify_llm_error(exc: Exception) -> LLMError:
    """根据底层异常文本启发式分类为对应 LLMError 子类。

    LiteLLM/OpenAI 的错误层次不统一，此处通过字符串匹配做兜底分类。
    """
    msg = str(exc).lower()
    if any(k in msg for k in ("balance", "insufficient", "quota", "credit")):
        return APIBalanceError(message=str(exc))
    if any(k in msg for k in ("rate limit", "too many requests", "429")):
        return APIRateLimit(message=str(exc))
    if any(k in msg for k in ("unauthorized", "401", "invalid api key", "authentication")):
        return APIAuthError(message=str(exc))
    return LLMError(message=str(exc))


__all__ = [
    "APIAuthError",
    "APIBalanceError",
    "APIRateLimit",
    "ArgusError",
    "ConfigError",
    "LLMError",
    "MemoryFullError",
    "SecurityBlock",
    "ToolError",
    "ToolNotFound",
    "ToolTimeout",
    "UserRejected",
    "classify_llm_error",
]
