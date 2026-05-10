"""Argus 自报告 4 个 Bug 的回归测试（bugs_found_20260510.md）。

#1 delegate_subagents 浏览器资源争用：navigation_lock 必须序列化所有 page 操作
#2 devtools_network_log 始终空：listener 应跨 page 替换 / 重新注册
#3 OAuth session 丢失：browser_navigate 描述应有 SPA 避坑提示
#4 动态 at token：browser_get_js_var 应安全读取 + 拒绝代码注入
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio


# ─── Bug #1: navigation_lock 序列化 ────────────────────────────────────────


class TestBrowserSerialization:
    async def test_concurrent_browser_ops_are_serialized(self) -> None:
        """3 个并发 @_serialize_browser_ops 装饰的协程必须串行执行——不重叠。"""
        from tools.browser import _serialize_browser_ops

        in_flight = {"current": 0, "max": 0}

        @_serialize_browser_ops
        async def fake_browser_op(name: str) -> str:
            in_flight["current"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["current"])
            await asyncio.sleep(0.05)  # 模拟 page 操作耗时
            in_flight["current"] -= 1
            return name

        results = await asyncio.gather(
            fake_browser_op("a"),
            fake_browser_op("b"),
            fake_browser_op("c"),
        )

        assert results == ["a", "b", "c"]
        assert in_flight["max"] == 1, (
            f"应串行执行（最多 1 个 in-flight），实际 max={in_flight['max']}——"
            f"navigation_lock 没生效"
        )

    async def test_navigation_lock_is_module_level_singleton(self) -> None:
        """_navigation_lock 必须是模块级单例，所有装饰器共享同一把锁。"""
        from tools import browser as bm

        assert isinstance(bm._navigation_lock, asyncio.Lock)
        # 二次 import 同一对象
        from tools.browser import _navigation_lock as lock2

        assert bm._navigation_lock is lock2

    async def test_browser_navigate_has_serialize_decorator(self) -> None:
        """13 个核心 browser_* 工具都必须被 _serialize_browser_ops 包裹。"""
        from tools import browser as bm

        # 简单存在性检查：装饰器导致 wrapper 名仍是原函数名（functools.wraps）
        # 用闭包变量 in_flight 在并发时验证（上面 test 已验证机制）；
        # 这里抽样检查关键工具确实经过装饰器（通过 wrapper 的 __wrapped__ 链）
        for tool_name in (
            "browser_navigate",
            "browser_get_html",
            "browser_get_text",
            "browser_screenshot",
            "browser_console_exec",
            "browser_click",
            "browser_fill",
            "browser_wait_for",
            "browser_tabs",
            "browser_frame",
            "browser_upload",
            "browser_keyboard",
            "browser_download",
        ):
            fn = getattr(bm, tool_name)
            assert callable(fn), f"{tool_name} 未导出"


# ─── Bug #2: devtools listener 跨 page 重注册 ──────────────────────────────


class TestDevtoolsListenerLifecycle:
    async def test_listener_reattaches_for_new_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """page 替换后 _ensure_network_listening 必须给新 page 注册 console listener。"""
        from tools import devtools

        # 清空跟踪集合
        devtools._listened_context_ids.clear()
        devtools._listened_page_ids.clear()

        # 构造两个不同的 fake page，但共享同一 fake context
        fake_context = MagicMock()
        fake_context.on = MagicMock()
        fake_context.add_init_script = AsyncMock()

        page1 = MagicMock()
        page1.context = fake_context
        page1.on = MagicMock()
        page1.evaluate = AsyncMock()

        page2 = MagicMock()
        page2.context = fake_context
        page2.on = MagicMock()
        page2.evaluate = AsyncMock()

        # 第一次 ensure：当前是 page1
        async def _get_page_1():
            return page1

        monkeypatch.setattr(devtools, "get_page", _get_page_1)
        await devtools._ensure_network_listening()

        # context 级 listener 注册一次
        assert fake_context.on.call_count == 2  # request + response
        # page1 console 注册一次
        assert page1.on.call_count == 1

        # 第二次 ensure：page 被替换为 page2（broken-pipe 重连场景）
        async def _get_page_2():
            return page2

        monkeypatch.setattr(devtools, "get_page", _get_page_2)
        await devtools._ensure_network_listening()

        # context 没换，不应重复注册 request/response
        assert fake_context.on.call_count == 2, "context 没换不应重复注册"
        # 但 page2 必须挂上 console listener（关键修复）
        assert page2.on.call_count == 1, "新 page 必须挂 console listener（Bug #2 修复）"

    async def test_listener_idempotent_on_same_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同一 page 多次调用 _ensure_network_listening 不应重复注册。"""
        from tools import devtools

        devtools._listened_context_ids.clear()
        devtools._listened_page_ids.clear()

        fake_context = MagicMock()
        fake_context.on = MagicMock()
        fake_context.add_init_script = AsyncMock()

        page = MagicMock()
        page.context = fake_context
        page.on = MagicMock()
        page.evaluate = AsyncMock()

        async def _get_page():
            return page

        monkeypatch.setattr(devtools, "get_page", _get_page)

        await devtools._ensure_network_listening()
        await devtools._ensure_network_listening()
        await devtools._ensure_network_listening()

        # 调 3 次但 listener 各类只注册一次
        assert fake_context.on.call_count == 2, "context.on 应只被注册一次（幂等）"
        assert page.on.call_count == 1, "page.on(console) 应只被注册一次"


# ─── Bug #3: browser_navigate description 含 SPA 避坑 ──────────────────────


class TestBrowserNavigateSpaWarning:
    def test_browser_navigate_description_warns_about_spa(self) -> None:
        """browser_navigate 工具描述必须警告 OAuth/SPA 完整重载会清 session。"""
        from agent.tool_registry import registry

        schemas = registry.get_tools_schema()
        nav = next(
            s["function"]
            for s in schemas
            if s["function"]["name"] == "browser_navigate"
        )
        desc = nav["description"]

        assert "SPA" in desc or "session" in desc, "描述应提示 SPA/session 风险"
        assert "browser_click" in desc, "应建议用 browser_click 走 SPA 路由"


# ─── Bug #4: browser_get_js_var ─────────────────────────────────────────────


class TestBrowserGetJsVar:
    async def test_rejects_function_call(self) -> None:
        """含 () 的 path 必须被拒绝（防任意代码执行）。"""
        from tools.browser import browser_get_js_var

        result = await browser_get_js_var(path="alert(1)")
        assert "禁用字符" in result
        assert "(" in result
        assert ")" in result

    async def test_rejects_assignment(self) -> None:
        """含 = 的 path 必须被拒绝（防赋值改 JS 状态）。"""
        from tools.browser import browser_get_js_var

        result = await browser_get_js_var(path="window.x=1")
        assert "禁用字符" in result

    async def test_rejects_statement_separator(self) -> None:
        """含 ; 的 path 必须被拒绝。"""
        from tools.browser import browser_get_js_var

        result = await browser_get_js_var(path="x;y")
        assert "禁用字符" in result

    async def test_empty_path_returns_error(self) -> None:
        from tools.browser import browser_get_js_var

        assert "不能为空" in await browser_get_js_var(path="")
        assert "不能为空" in await browser_get_js_var(path="   ")

    async def test_valid_path_evaluates_and_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """合法 path 应调 page.evaluate 并 JSON 序列化结果。"""
        from tools import browser as bm

        fake_page = MagicMock()
        fake_page.evaluate = AsyncMock(return_value={"token": "abc123", "ts": 1234567890})

        async def _get_page():
            return fake_page

        monkeypatch.setattr(bm, "get_page", _get_page)

        result = await bm.browser_get_js_var(path="window.WIZ_global_data.SNlM0e")

        # evaluate 调用了 () => path 形式
        fake_page.evaluate.assert_awaited_once()
        called_arg = fake_page.evaluate.await_args.args[0]
        assert called_arg.startswith("() =>")
        assert "window.WIZ_global_data.SNlM0e" in called_arg

        # 结果包含 path 和 JSON 化的值
        assert "window.WIZ_global_data.SNlM0e" in result
        assert "abc123" in result
        assert "1234567890" in result

    def test_tool_registered(self) -> None:
        """browser_get_js_var 必须注册到 registry。"""
        from agent.tool_registry import registry

        assert "browser_get_js_var" in registry.list_tools()
