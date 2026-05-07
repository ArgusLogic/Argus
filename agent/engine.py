"""Agent 核心循环引擎：LLM 推理 → 工具调用 → 结果回传 → 记忆/技能提炼。"""

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse

from agent.context import ContextManager
from agent.llm_client import LLMClient
from agent.memory import MemoryStore
from agent.memory_md import MemoryMD
from agent.prompts import SYSTEM_PROMPT, PromptBuilder
from agent.skills import SkillManager
from agent.subagent import SubAgentOrchestrator, set_global_orchestrator
from agent.tool_registry import ToolRegistry
from utils.logger import console, log_agent, log_error, log_info, log_warning

# ─── 工具安全分级 ─────────────────────────────────────────────────────────────
# safe:    只读/无副作用，自动执行
# confirm: 可能有副作用，审批模式下需用户确认
# block:   主动探测/高风险，审批模式下必须确认且显示风险提示

TOOL_RISK_LEVELS: dict[str, str] = {
    # safe — 自动执行
    "browser_navigate": "safe",
    "browser_get_html": "safe",
    "browser_get_text": "safe",
    "browser_screenshot": "safe",
    "browser_click": "confirm",
    "browser_fill": "confirm",
    "devtools_start_capture": "safe",
    "devtools_network_log": "safe",
    "devtools_cookies": "safe",
    "devtools_headers": "safe",
    "crawl_links": "safe",
    "crawl_forms": "safe",
    "crawl_js_sources": "safe",
    "crawl_js_endpoints": "safe",
    "dns_lookup": "safe",
    "whois_lookup": "safe",
    "header_analysis": "safe",
    "save_file": "safe",
    "read_file": "safe",
    "generate_report": "safe",
    "memory_manage": "safe",
    "skill_manage": "safe",
    "session_search": "safe",
    # 新增 v9 工具（read-only）
    "browser_wait_for": "safe",
    "browser_tabs": "safe",
    "browser_frame": "safe",
    "browser_keyboard": "confirm",
    "devtools_sse_log": "safe",
    "devtools_sse_clear": "safe",
    "request_replay_list": "safe",
    "project_save": "safe",
    "project_load": "safe",
    "project_list": "safe",
    "project_delete": "safe",
    "request_replay": "confirm",
    "delegate_subagents": "confirm",
    # confirm — 需用户确认（有副作用 / 触发请求）
    "browser_console_exec": "confirm",
    "browser_upload": "confirm",
    "browser_download": "confirm",
    "http_request": "confirm",
    "crawl_site_map": "confirm",
    # block — 高风险，必须确认 + 风险提示
    "subdomain_enum": "block",
    "dir_bruteforce": "block",
    "port_scan": "block",
}

BLOCK_RISK_HINTS: dict[str, str] = {
    "subdomain_enum": "将对目标域名发起大量 DNS 请求，可能触发安全警报",
    "dir_bruteforce": "将对目标发起大量 HTTP 请求进行路径枚举",
    "port_scan": "将对目标主机进行端口扫描（需本地安装 nmap）",
}


class AgentEngine:
    """驱动 Agent 的核心循环。"""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        max_turns: int = 0,  # 已废弃：保留参数以兼容外部调用，运行时不使用
        approval_mode: bool = True,
        verbose: bool = True,
        tool_timeout: int = 60,
        max_retries: int = 2,
        allowed_domains: list[str] | None = None,
        context_max_tokens: int = 200000,
        tool_allowlist: list[str] | None = None,
        tool_blocklist: list[str] | None = None,
        require_approval_for: list[str] | None = None,
        track_skill_usage: bool = True,
        track_lessons: bool = True,
        auto_extract_skills: bool = False,
        track_failure_replays: bool = False,
    ):
        self.llm = llm
        self.registry = registry
        self.max_turns = max_turns  # 已废弃，仅作兼容保留
        self.approval_mode = approval_mode
        self.verbose = verbose
        self.tool_timeout = tool_timeout
        self.max_retries = max_retries
        self.allowed_domains = allowed_domains or []
        # 工具级访问控制（P2.2 命令白名单）
        self.tool_allowlist: set[str] = set(tool_allowlist or [])
        self.tool_blocklist: set[str] = set(tool_blocklist or [])
        self.require_approval_for: set[str] = set(require_approval_for or [])
        # A1: 自演化 — 跟踪本轮 user 输入起的工具调用，结束后增量 success_count
        self.track_skill_usage = track_skill_usage
        self._turn_start_idx = 0
        # A3: 自演化 — 失败学习（启发式抽取，零 LLM 成本）
        self.track_lessons = track_lessons
        # A2: 自演化 — 自动提炼技能（每次任务结束后判断；要烧 token，默认关）
        self.auto_extract_skills = auto_extract_skills
        # C2: 失败请求结构化日志（jsonl）
        self.track_failure_replays = track_failure_replays
        self.context = ContextManager(max_tokens=context_max_tokens)
        self.context.set_llm(llm)
        self.memory = MemoryStore()  # 保留：作为 session_search FTS5 后端
        self.memory_md = MemoryMD()  # 新：MD 文件式持久记忆（agent 主动管）
        self.skills = SkillManager()
        self.prompt_builder = PromptBuilder()
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # 冻结注入标记：MEMORY/USER 块只在首轮注入一次，保 prefix cache
        self._memory_injected = False

        # 子代理编排器：注入全局，供 delegate_subagents 工具使用
        self.subagent_orchestrator = SubAgentOrchestrator(
            llm=llm,
            registry=registry,
            memory_block=self.memory_md.render_block("memory"),
            max_concurrency=4,
            tool_timeout=tool_timeout,
        )
        set_global_orchestrator(self.subagent_orchestrator)

    def set_messages(self, messages: list[dict]) -> None:
        """用于会话恢复。"""
        self.messages = messages

    async def _build_dynamic_prompt(self, user_input: str) -> str:
        """构建 system prompt：基础人格 + 冻结的 MEMORY/USER 块 + 技能 + 项目上下文。

        冻结注入：本方法仅在会话首次构建时影响 prompt；中途 memory_manage 调用直接写文件，
        不刷新 prompt（保 prefix cache，与 Hermes 一致）。
        """
        # MEMORY.md / USER.md 块（冻结注入）
        memory_block = self.memory_md.render_block("memory")
        user_block = self.memory_md.render_block("user")
        # A3: LESSONS（避坑库），仅在非空时注入
        lessons_block = ""
        if self.memory_md.list_entries("lessons"):
            lessons_block = self.memory_md.render_block("lessons")
        # 获取技能摘要
        skills_text = self.skills.format_for_prompt(limit=5)
        # 加载项目上下文文件
        context_file = PromptBuilder.load_context_file()

        return self.prompt_builder.build(
            memory_block=memory_block,
            user_block=user_block,
            skills_text=skills_text,
            context_file=context_file,
            lessons_block=lessons_block,
        )

    async def run(self, user_input: str) -> str:
        """处理一次用户输入，运行完整的 Agent 循环，返回最终回复。"""
        # 冻结注入：system prompt 只在首轮构建，后续轮不重建（保 prefix cache）
        if not self._memory_injected:
            dynamic_prompt = await self._build_dynamic_prompt(user_input)
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = dynamic_prompt
            else:
                self.messages.insert(0, {"role": "system", "content": dynamic_prompt})
            self._memory_injected = True

        # A1: 标记本轮起点，便于结束后做 skill usage tracking
        self._turn_start_idx = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})

        tools_schema = self.registry.get_tools_schema()
        turn = 0
        final_text = ""

        while True:
            turn += 1

            # 检查是否需要压缩上下文
            if self.context.needs_compression(self.messages):
                self.messages = await self.context.compress(self.messages)

            # 调用 LLM（带指数退避重试）
            if self.verbose:
                token_count = self.context.count_tokens(self.messages)
                log_info(f"Turn {turn} | Tokens: ~{token_count}")

            response = await self._call_llm_with_retry(
                messages=self.messages,
                tools=tools_schema if tools_schema else None,
            )
            if response is None:
                return "LLM 调用失败，请检查 API Key 和网络连接。"

            choice = response.choices[0]
            message = choice.message

            # 将 assistant 消息追加到历史
            assistant_msg = {"role": "assistant", "content": message.content or ""}
            # 保留 reasoning_content（DeepSeek V4 thinking mode 要求回传）
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            self.messages.append(assistant_msg)

            # 如果没有工具调用，说明模型给出了最终回复
            if not message.tool_calls:
                final_text = message.content or ""
                if final_text:
                    log_agent(final_text)
                break

            # 有工具调用，逐个执行
            for tc in message.tool_calls:
                func_name = tc.function.name
                func_args = tc.function.arguments

                # 工具级 ACL 校验（blocklist / allowlist）
                allowed, acl_reason = self._check_tool_acl(func_name)
                if not allowed:
                    result = f"操作被拒绝：{acl_reason}"
                    log_warning(f"工具 ACL 拦截: {acl_reason}")
                    self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    continue

                # 域名白名单校验
                if not self._check_domain_whitelist(func_name, func_args):
                    result = (
                        "操作被拒绝：目标不在允许的域名白名单内。请检查 config.toml 的 allowed_domains 配置。"
                    )
                    log_warning(f"域名白名单拦截: {func_name}")
                    self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    continue

                # 审批机制：approval_mode 或 require_approval_for 列表都触发审批
                risk = TOOL_RISK_LEVELS.get(func_name, "confirm")
                needs_approval = (self.approval_mode and risk != "safe") or self._force_approval(func_name)
                if needs_approval and not await self._ask_approval(func_name, func_args, risk):
                    result = "用户拒绝执行该操作"
                    self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    continue

                # 执行工具（带超时和重试）
                result = await self.registry.execute(
                    func_name,
                    func_args,
                    timeout=self.tool_timeout,
                    max_retries=self.max_retries,
                )

                # 结果追加到消息
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                # issue #3.7：memory_manage 改写 MD 文件后，刷新 system 块
                await self._refresh_memory_block_after_tool(func_name, result)

        # A1: 任务结束 → 增量 success_count
        self._track_skill_usage_after_run(final_text)
        # A3: 失败学习 — 把本轮检测到的失败写入 LESSONS.md
        self._track_lessons_after_run()
        # C2: 结构化失败记录写入 jsonl（默认关）
        self._track_failure_replays_after_run()
        # A2: 自动提炼新技能（fire-and-forget，可能调 LLM）
        self._maybe_extract_skill_after_run(final_text)
        return final_text

    async def run_stream(self, user_input: str, ui=None) -> str:
        """流式版本的 run()：通过 ui 对象实时渲染输出。

        Args:
            user_input: 用户输入
            ui: LiveUI 实例，提供 set_thinking/append_text/add_tool_call 等方法
        """

        # 冻结注入：system prompt 只在首轮构建，后续轮不重建（保 prefix cache）
        if not self._memory_injected:
            dynamic_prompt = await self._build_dynamic_prompt(user_input)
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = dynamic_prompt
            else:
                self.messages.insert(0, {"role": "system", "content": dynamic_prompt})
            self._memory_injected = True

        # A1: 标记本轮起点
        self._turn_start_idx = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})

        tools_schema = self.registry.get_tools_schema()
        turn = 0
        final_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_hit = 0
        total_cache_miss = 0

        while True:
            turn += 1

            # 检查是否需要压缩上下文
            if self.context.needs_compression(self.messages):
                self.messages = await self.context.compress(self.messages)

            if self.verbose:
                token_count = self.context.count_tokens(self.messages)
                if ui:
                    # 流式模式：只写文件日志，不打印到终端（UI 已处理）
                    from utils.logger import file_logger

                    file_logger.write("INFO", f"Turn {turn} | Tokens: ~{token_count}")
                else:
                    log_info(f"Turn {turn} | Tokens: ~{token_count}")

            # 思考动画
            if ui:
                ui.set_thinking()

            # ── 流式调用 LLM ──
            content = ""
            reasoning_content = ""
            tool_calls_list = []
            usage = {}
            stream_ok = False

            for attempt in range(3):
                try:
                    async for event in self.llm.chat_stream_events(
                        messages=self.messages,
                        tools=tools_schema if tools_schema else None,
                    ):
                        if event.type == "text_delta":
                            if ui:
                                ui.append_text(event.text)
                        elif event.type == "reasoning_delta":
                            if ui:
                                ui.append_thinking(event.text)
                        elif event.type == "tool_call_start":
                            pass  # 等 done 事件拿到完整参数再显示
                        elif event.type == "done":
                            content = event.content
                            reasoning_content = event.reasoning_content
                            tool_calls_list = event.tool_calls
                            usage = event.usage

                    stream_ok = True
                    break
                except Exception as e:
                    from agent.errors import (
                        APIAuthError,
                        APIBalanceError,
                        APIRateLimit,
                        classify_llm_error,
                    )

                    err = classify_llm_error(e)

                    if isinstance(err, APIBalanceError):
                        log_error("💰 余额不足！请前往 platform.deepseek.com 充值后重试。")
                        if ui:
                            ui.append_text("❌ API 余额不足，请充值后重试。")
                        return "API 余额不足，请充值后重试。"
                    if isinstance(err, APIAuthError):
                        log_error("🔑 API Key 无效或权限不足。")
                        if ui:
                            ui.append_text("❌ API Key 无效，请检查 config.toml。")
                        return "API Key 无效，请检查配置。"
                    if isinstance(err, APIRateLimit):
                        wait = 2 ** (attempt + 1)  # 429 等更久：4s, 8s, 16s
                        log_warning(f"⏳ 请求限速 (429)，等待 {wait}s 后重试...")
                        await asyncio.sleep(wait)
                        continue

                    wait = 2**attempt
                    log_error(f"LLM 流式调用异常 (第 {attempt + 1} 次): {err}")
                    if attempt < 2:
                        log_info(f"等待 {wait}s 后重试...")
                        await asyncio.sleep(wait)

            if not stream_ok:
                if ui:
                    ui.append_text("LLM 调用失败，请检查 API Key 和网络连接。")
                return "LLM 调用失败，请检查 API Key 和网络连接。"

            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)
            total_cache_hit += usage.get("prompt_cache_hit_tokens", 0)
            total_cache_miss += usage.get("prompt_cache_miss_tokens", 0)

            # 将 assistant 消息追加到历史
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            # 保留 reasoning_content（DeepSeek V4 thinking mode 要求回传）
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
            if tool_calls_list:
                assistant_msg["tool_calls"] = tool_calls_list
            self.messages.append(assistant_msg)

            # 如果没有工具调用，最终回复
            if not tool_calls_list:
                final_text = content
                break

            # ── 执行工具调用 ──
            for tc in tool_calls_list:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                tc_id = tc["id"]

                # 工具级 ACL 校验（blocklist / allowlist）
                allowed, acl_reason = self._check_tool_acl(func_name)
                if not allowed:
                    result = f"操作被拒绝：{acl_reason}"
                    log_warning(f"工具 ACL 拦截: {acl_reason}")
                    self.messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                    if ui:
                        ui.add_tool_call(func_name, func_args)
                        ui.fail_tool_call(func_name, result, elapsed=0)
                    continue

                # 域名白名单校验
                if not self._check_domain_whitelist(func_name, func_args):
                    result = "操作被拒绝：目标不在允许的域名白名单内。"
                    log_warning(f"域名白名单拦截: {func_name}")
                    self.messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                    if ui:
                        ui.add_tool_call(func_name, func_args)
                        ui.fail_tool_call(func_name, result, elapsed=0)
                    continue

                # 审批机制
                risk = TOOL_RISK_LEVELS.get(func_name, "confirm")
                needs_approval = (self.approval_mode and risk != "safe") or self._force_approval(func_name)
                if needs_approval:
                    # 暂停 Live 渲染以显示审批提示
                    if ui and ui._live:
                        ui._live.stop()
                    approved = await self._ask_approval(func_name, func_args, risk)
                    if ui:
                        ui._live = None
                        ui.start()  # 重新开始 Live
                        # 恢复已完成的 sections
                    if not approved:
                        result = "用户拒绝执行该操作"
                        self.messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                        continue

                # UI 显示工具开始
                if ui:
                    ui.add_tool_call(func_name, func_args)

                # 执行工具（silent=True: UI 已处理显示）
                t0 = time.time()
                result = await self.registry.execute(
                    func_name,
                    func_args,
                    timeout=self.tool_timeout,
                    max_retries=self.max_retries,
                    silent=True,
                )
                elapsed = time.time() - t0

                # 结果追加到消息
                self.messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                # issue #3.7：memory_manage 写入后刷新 system 块
                await self._refresh_memory_block_after_tool(func_name, result)

                # UI 显示工具完成
                if ui:
                    # 只有工具执行器返回的错误前缀才标记失败
                    if (
                        (
                            result.startswith("工具")
                            and ("执行失败" in result[:50] or "执行超时" in result[:50])
                        )
                        or result.startswith("保存失败")
                        or result.startswith("读取失败")
                    ):
                        ui.fail_tool_call(func_name, result, elapsed=elapsed)
                    else:
                        ui.finish_tool_call(func_name, result, elapsed=elapsed)

        # UI 完成
        if ui:
            ui.finish(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_hit=total_cache_hit,
                cache_miss=total_cache_miss,
            )

        # A1: 任务结束 → 增量 success_count
        self._track_skill_usage_after_run(final_text)
        # A3: 失败学习
        self._track_lessons_after_run()
        # C2: 结构化失败记录
        self._track_failure_replays_after_run()
        # A2: 自动提炼新技能
        self._maybe_extract_skill_after_run(final_text)
        return final_text

    async def _refresh_memory_block_after_tool(self, func_name: str, result: str) -> None:
        """issue #3.7：memory_manage 写入后，刷新 system prompt 的 MEMORY 块。

        会失效一次 prefix cache，但仅在 LLM 显式调 memory_manage 时触发，频率低。
        失败/拒绝的调用（结果以"失败"/"拒绝"开头）跳过。
        """
        if func_name != "memory_manage":
            return
        if not isinstance(result, str) or result.startswith(("失败", "拒绝", "用户拒绝")):
            return
        if not self.messages or self.messages[0].get("role") != "system":
            return
        try:
            new_prompt = await self._build_dynamic_prompt("")
            self.messages[0]["content"] = new_prompt
        except Exception as e:
            log_warning(f"刷新 MEMORY 块失败: {e}")

    def _maybe_extract_skill_after_run(self, final_text: str) -> None:
        """A2: 任务结束后异步触发 LLM 自动提炼技能。

        fire-and-forget：不等待结果，不阻塞用户回流。
        被 auto_extract_skills 开关控制，默认关闭（要烧 token）。
        """
        if not self.auto_extract_skills:
            return
        try:
            from agent.skill_extractor import extract_skill_async

            turn_messages = self.messages[self._turn_start_idx :]
            task = asyncio.create_task(
                extract_skill_async(
                    llm=self.llm,
                    skills=self.skills,
                    messages=turn_messages,
                    final_text=final_text,
                )
            )
            # 持有引用避免被 GC 提前回收（RUF006）
            self._bg_tasks: set = getattr(self, "_bg_tasks", set())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except Exception as e:
            log_warning(f"auto skill extract 启动失败: {e}")

    def _track_failure_replays_after_run(self) -> int:
        """C2: 把本轮失败请求写入结构化 jsonl（独立于 A3 lessons）。

        被 track_failure_replays 开关控制（默认关）。
        """
        if not self.track_failure_replays:
            return 0
        try:
            from agent.failure_log import extract_and_log_failures

            turn_messages = self.messages[self._turn_start_idx :]
            return extract_and_log_failures(turn_messages)
        except Exception as e:
            log_warning(f"failure_replay 写入失败: {e}")
            return 0

    def _track_lessons_after_run(self) -> list[str]:
        """A3: 启发式扫描本轮 tool 消息，把识别到的失败模式写入 LESSONS.md。

        零 LLM 调用。对同一 (tool, target, label) 三元组在本轮内只产出 1 条。
        被 track_lessons 开关控制，默认开启。

        返回新增的 lesson 文本列表（便于测试/日志）。
        """
        if not self.track_lessons:
            return []
        try:
            from agent.lessons import extract_lessons

            turn_messages = self.messages[self._turn_start_idx :]
            lessons = extract_lessons(turn_messages)
            saved: list[str] = []
            for lesson in lessons:
                res = self.memory_md.append_lesson(lesson)
                if res.get("ok"):
                    saved.append(lesson)
            if saved:
                from utils.logger import file_logger

                file_logger.write("INFO", f"自演化 A3: 新增 {len(saved)} 条 lesson")
            return saved
        except Exception as e:
            log_warning(f"lesson tracking 失败: {e}")
            return []

    def _track_skill_usage_after_run(self, final_text: str) -> list[str]:
        """A1: 任务结束后，扫描本轮 user 起的工具调用序列，与已有技能匹配。

        命中（≥60% 步骤工具重合）则 increment_success。
        被 track_skill_usage 开关控制，默认开启；零 LLM 调用，纯本地匹配。

        返回匹配并已增量的技能名列表（便于测试/日志）。
        """
        if not self.track_skill_usage or not final_text.strip():
            return []
        try:
            turn_messages = self.messages[self._turn_start_idx :]
            executed = self.skills.extract_tool_names(turn_messages)
            if len(executed) < 2:
                return []
            matched = self.skills.match_used_skills(executed, min_overlap=0.6)
            for name in matched:
                self.skills.increment_success(name)
            if matched:
                from utils.logger import file_logger

                file_logger.write("INFO", f"自演化 A1: 复用技能 +1 → {', '.join(matched)}")
            return matched
        except Exception as e:
            log_warning(f"skill usage tracking 失败: {e}")
            return []

    async def _call_llm_with_retry(
        self, messages: list[dict], tools: list[dict] | None, max_attempts: int = 3
    ):
        """调用 LLM，失败时指数退避重试。

        不可恢复错误（余额不足 / API Key 无效）立即终止，不消耗重试预算。
        速率限制和未知错误走指数退避。
        """
        from agent.errors import APIAuthError, APIBalanceError, classify_llm_error

        for attempt in range(max_attempts):
            try:
                response = await self.llm.chat(
                    messages=messages,
                    tools=tools,
                )
                return response
            except Exception as e:
                err = classify_llm_error(e)
                # 不可恢复错误：立即抛出，由外层处理（友好提示用户）
                if isinstance(err, (APIBalanceError, APIAuthError)):
                    log_error(f"LLM {err}")
                    raise err from e

                wait = 2**attempt
                log_error(f"LLM 调用异常 (第 {attempt + 1}/{max_attempts} 次): {err}")
                if attempt < max_attempts - 1:
                    log_info(f"等待 {wait}s 后重试...")
                    await asyncio.sleep(wait)
        return None

    def _check_tool_acl(self, tool_name: str) -> tuple[bool, str]:
        """工具级访问控制：返回 (allowed, reason)。

        优先级：blocklist > allowlist > 默认允许。
        """
        if tool_name in self.tool_blocklist:
            return False, f"工具 {tool_name} 在 tool_blocklist 中被禁用"
        if self.tool_allowlist and tool_name not in self.tool_allowlist:
            return False, f"工具 {tool_name} 不在 tool_allowlist 中（已启用白名单）"
        return True, ""

    def _force_approval(self, tool_name: str) -> bool:
        """检查是否强制要求审批（即使 approval_mode 关闭）。"""
        return tool_name in self.require_approval_for

    def _check_domain_whitelist(self, tool_name: str, args_str: str) -> bool:
        """检查工具参数中的目标域名是否在白名单内。白名单为空时放行。"""
        if not self.allowed_domains:
            return True

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            return True

        targets = []
        for key in ("url", "domain", "target"):
            val = args.get(key, "")
            if val:
                targets.append(val)

        if not targets:
            return True

        for target in targets:
            domain = target
            if "://" in target:
                domain = urlparse(target).netloc
            domain = domain.split(":")[0].lower()

            matched = False
            for allowed in self.allowed_domains:
                allowed = allowed.lower()
                if domain == allowed or domain.endswith(f".{allowed}"):
                    matched = True
                    break
            if not matched:
                return False

        return True

    async def _ask_approval(self, name: str, args: str, risk: str) -> bool:
        """请求用户确认是否执行操作。risk='block' 时显示额外风险提示。"""
        if risk == "block":
            hint = BLOCK_RISK_HINTS.get(name, "此操作可能对目标产生可检测的影响")
            console.print("\n[error][⚠ 高风险操作][/error]")
            console.print(f"    风险: {hint}")
        else:
            console.print("\n[warning][!] 需要确认执行:[/warning]")

        console.print(f"    工具: [bold]{name}[/bold]")
        try:
            parsed = json.loads(args)
            console.print(f"    参数: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
        except Exception:
            console.print(f"    参数: {args}")

        try:
            answer = input("    执行? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes", "")
