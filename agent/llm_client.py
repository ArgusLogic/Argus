"""LLM 统一调用层，基于 litellm 适配多模型。"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import litellm
from litellm import acompletion

from utils.logger import log_info, log_warning


@dataclass
class StreamEvent:
    """流式响应中的一个事件。"""

    type: str  # "text_delta" | "reasoning_delta" | "tool_call_start" | "tool_call_delta" | "done"
    text: str = ""
    tool_index: int = 0
    tool_id: str = ""
    tool_name: str = ""
    tool_args_delta: str = ""
    # 完整的拼接结果（仅 done 事件）
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class LLMClient:
    """封装 litellm，提供流式 + function calling 的统一接口。"""

    def __init__(self, model: str, api_keys: dict | None = None):
        self.model = model
        self.reasoning_effort: str | None = None  # None=默认, "off"/"high"/"max"
        self._setup_api_keys(api_keys or {})
        # 关闭 litellm 自带日志，用我们自己的
        litellm.suppress_debug_info = True

    def _setup_api_keys(self, keys: dict) -> None:
        """将配置中的 API Key 注入环境变量供 litellm 使用。"""
        mapping = {
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        for provider, env_var in mapping.items():
            key = keys.get(provider, "")
            if key and not os.environ.get(env_var):
                os.environ[env_var] = key

    def switch_model(self, model: str) -> None:
        log_info(f"模型切换: {self.model} → {model}")
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ) -> dict:
        """非流式调用，返回完整 response。"""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.reasoning_effort and self.reasoning_effort != "off":
            kwargs["reasoning_effort"] = self.reasoning_effort
        elif self.reasoning_effort == "off":
            kwargs["thinking"] = {"type": "disabled"}

        try:
            response = await acompletion(**kwargs)
            return response
        except Exception as e:
            log_warning(f"LLM 调用失败: {e}")
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ) -> AsyncIterator:
        """流式调用，返回 async iterator。"""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.reasoning_effort and self.reasoning_effort != "off":
            kwargs["reasoning_effort"] = self.reasoning_effort
        elif self.reasoning_effort == "off":
            kwargs["thinking"] = {"type": "disabled"}

        try:
            response = await acompletion(**kwargs)
            return response
        except Exception as e:
            log_warning(f"LLM 流式调用失败: {e}")
            raise

    async def chat_stream_events(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ):
        """流式调用，yield StreamEvent 事件序列。

        自动处理 tool_calls 的 delta 拼接，最终 yield 一个 done 事件
        包含完整的 content 和 tool_calls 列表。
        """
        raw_stream = await self.chat_stream(messages=messages, tools=tools, temperature=temperature)

        full_content = ""
        full_reasoning = ""
        # tool_calls 拼接缓冲: {index: {"id": ..., "name": ..., "arguments": ...}}
        tc_buffer: dict[int, dict] = {}
        usage_info = {}
        first_token = True

        async for chunk in raw_stream:
            # 提取 usage（通常在最后一个 chunk）
            if hasattr(chunk, "usage") and chunk.usage:
                usage_info = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                    "prompt_cache_hit_tokens": getattr(chunk.usage, "prompt_cache_hit_tokens", 0) or 0,
                    "prompt_cache_miss_tokens": getattr(chunk.usage, "prompt_cache_miss_tokens", 0) or 0,
                }

            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # reasoning_content delta（DeepSeek V4 thinking mode）
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                full_reasoning += reasoning_delta
                yield StreamEvent(type="reasoning_delta", text=reasoning_delta)

            # 文本内容 delta
            if delta.content:
                if first_token:
                    first_token = False
                full_content += delta.content
                yield StreamEvent(type="text_delta", text=delta.content)

            # tool_calls delta
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if hasattr(tc_delta, "index") else 0

                    if idx not in tc_buffer:
                        tc_buffer[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }

                    buf = tc_buffer[idx]

                    if hasattr(tc_delta, "id") and tc_delta.id:
                        buf["id"] = tc_delta.id

                    func = getattr(tc_delta, "function", None)
                    if func:
                        if hasattr(func, "name") and func.name:
                            old_name = buf["name"]
                            buf["name"] = func.name
                            if not old_name:
                                yield StreamEvent(
                                    type="tool_call_start",
                                    tool_index=idx,
                                    tool_id=buf["id"],
                                    tool_name=func.name,
                                )

                        if hasattr(func, "arguments") and func.arguments:
                            buf["arguments"] += func.arguments
                            yield StreamEvent(
                                type="tool_call_delta",
                                tool_index=idx,
                                tool_name=buf["name"],
                                tool_args_delta=func.arguments,
                            )

        # 构建最终 tool_calls 列表
        final_tool_calls = []
        for idx in sorted(tc_buffer.keys()):
            buf = tc_buffer[idx]
            final_tool_calls.append(
                {
                    "id": buf["id"],
                    "type": "function",
                    "function": {
                        "name": buf["name"],
                        "arguments": buf["arguments"],
                    },
                }
            )

        yield StreamEvent(
            type="done",
            content=full_content,
            reasoning_content=full_reasoning,
            tool_calls=final_tool_calls,
            usage=usage_info,
        )
