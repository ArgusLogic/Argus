"""单次会话内的对话历史管理：token 计数 + 自动压缩（含 LLM 摘要）。

注意此模块**不**保存任何跨会话状态。三层记忆架构详见 `docs/architecture.md`：

  - ContextManager (this file)        : 单会话对话历史，进程结束即丢
  - SessionIndex   (session_index.py) : 跨会话 SQLite/FTS5 倒排索引
  - MemoryMD       (memory_md.py)     : LLM 主动维护的 MD 文件型记忆
"""

import tiktoken

from utils.logger import log_info, log_warning


class ContextManager:
    """管理对话上下文，跟踪 token 使用并在必要时压缩。"""

    def __init__(self, max_tokens: int = 120000, compress_threshold: float = 0.8):
        self.max_tokens = max_tokens
        self.compress_threshold = compress_threshold
        self._llm = None  # 延迟注入，避免循环依赖
        try:
            self.encoder = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            self.encoder = tiktoken.get_encoding("cl100k_base")

    def set_llm(self, llm) -> None:
        """注入 LLM 客户端以启用智能摘要。"""
        self._llm = llm

    def count_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 token 数量。"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(self.encoder.encode(content))
            # tool_calls 中的参数也计入
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                total += len(self.encoder.encode(func.get("name", "")))
                total += len(self.encoder.encode(func.get("arguments", "")))
            # 每条消息的 role/name 等元数据约 4 token
            total += 4
        return total

    def needs_compression(self, messages: list[dict]) -> bool:
        """判断是否需要压缩上下文。"""
        tokens = self.count_tokens(messages)
        threshold = int(self.max_tokens * self.compress_threshold)
        return tokens > threshold

    async def compress(self, messages: list[dict]) -> list[dict]:
        """压缩历史消息：优先用 LLM 智能摘要，失败时回退到简单截断。"""
        if len(messages) <= 4:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        keep_recent = 6
        if len(non_system) <= keep_recent:
            return messages

        # issue #3.5：边界不能切断 assistant.tool_calls -> tool 结果对，
        # 否则 LLM API 会拒绝（"tool message must follow assistant w/ tool_calls"）。
        # 策略：从默认切点起，若 recent 首条是 tool 角色，向前推进直到不是。
        cut = max(0, len(non_system) - keep_recent)
        while cut < len(non_system) and non_system[cut].get("role") == "tool":
            cut += 1
        # Bug 6 (Coco 报告): 极端场景全 tool 消息 → 之前直接 return messages 不压缩，
        # 长会话下会 token 溢出。改为强制截断到最近 keep_recent 条 + 跳过开头 tool 边界
        if cut >= len(non_system):
            log_warning(
                f"上下文极端场景（{len(non_system)} 条消息全是 tool 结果）：强制截断到最近 {keep_recent} 条"
            )
            forced_keep = non_system[-keep_recent:]
            # tool message 必须跟在 assistant.tool_calls 之后，开头若是 tool 则丢弃
            while forced_keep and forced_keep[0].get("role") == "tool":
                forced_keep = forced_keep[1:]
            summary_msg = {
                "role": "user",
                "content": "[上下文已强制截断：之前消息均为工具结果，已舍弃以避免 token 溢出]",
            }
            compressed = [*system_msgs, summary_msg, *forced_keep]
            log_info(f"上下文强制截断: {len(messages)} → {len(compressed)} 条消息")
            return compressed
        old_msgs = non_system[:cut]
        recent_msgs = non_system[cut:]

        # 尝试 LLM 智能摘要
        summary_text = await self._llm_summarize(old_msgs)
        if not summary_text:
            # 回退：简单截断
            summary_text = self._simple_summarize(old_msgs)

        summary_msg = {"role": "user", "content": summary_text}
        compressed = [*system_msgs, summary_msg, *recent_msgs]
        log_info(f"上下文已压缩: {len(messages)} → {len(compressed)} 条消息")
        return compressed

    async def _llm_summarize(self, old_msgs: list[dict]) -> str | None:
        """用 LLM 生成智能摘要。"""
        if not self._llm:
            return None

        # 构造要摘要的文本
        parts = []
        for m in old_msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                parts.append(f"[{role}] {content[:300]}")

        if not parts:
            return None

        conversation_text = "\n".join(parts[-20:])  # 最近 20 条

        summarize_messages = [
            {
                "role": "system",
                "content": (
                    "你是一个对话摘要助手。请将以下对话历史压缩为简洁的摘要，"
                    "保留关键发现、已执行的操作和重要结果。"
                    "用中文输出，控制在 500 字以内。"
                ),
            },
            {"role": "user", "content": f"请摘要以下对话：\n\n{conversation_text}"},
        ]

        try:
            response = await self._llm.chat(
                messages=summarize_messages,
                tools=None,
                temperature=0.0,
            )
            summary = response.choices[0].message.content
            if summary and len(summary) > 20:
                log_info("使用 LLM 智能摘要压缩上下文")
                return f"[之前对话的摘要]\n{summary}"
        except Exception as e:
            log_warning(f"LLM 摘要失败，回退到简单截断: {e}")

        return None

    def _simple_summarize(self, old_msgs: list[dict]) -> str:
        """简单截断摘要（回退方案）。"""
        summary_parts = []
        for m in old_msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                summary_parts.append(f"[{role}] {content[:100]}")

        return "以下是之前对话的摘要:\n" + "\n".join(summary_parts[-10:])
