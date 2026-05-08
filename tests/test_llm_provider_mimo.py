"""Xiaomi MiMo provider 接入回归。

确认：
  1. config.toml 的 [api_keys] xiaomi_mimo = "..." 会被 LLMClient 注入到
     XIAOMI_MIMO_API_KEY 环境变量
  2. main.py 的模型选择器列出了 V2.5 系列
  3. LiteLLM 能把 xiaomi_mimo/mimo-v2.5-pro 路由到正确的 provider 和 base_url
"""

from __future__ import annotations

import os

import pytest


def test_llm_client_propagates_xiaomi_mimo_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    LLMClient(model="xiaomi_mimo/mimo-v2.5-pro", api_keys={"xiaomi_mimo": "tp-test-12345"})
    assert os.environ["XIAOMI_MIMO_API_KEY"] == "tp-test-12345"


def test_resolve_api_base_xiaomi_token_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token Plan 独立端点应被 _resolve_api_base 命中。"""
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    client = LLMClient(
        model="xiaomi_mimo/mimo-v2.5-pro",
        api_keys={"xiaomi_mimo": "tp-xxx"},
        api_bases={"xiaomi_mimo": "https://token-plan-sgp.xiaomimimo.com/v1/"},
    )
    # trailing slash 应被剥掉
    assert client._resolve_api_base("xiaomi_mimo/mimo-v2.5-pro") == "https://token-plan-sgp.xiaomimimo.com/v1"
    # 其他 provider 不受影响
    assert client._resolve_api_base("deepseek/deepseek-v4-flash") is None


def test_resolve_api_base_empty_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    client = LLMClient(model="xiaomi_mimo/mimo-v2.5-pro", api_keys={})
    # 未配置 api_bases → 所有模型都返 None
    assert client._resolve_api_base("xiaomi_mimo/mimo-v2.5-pro") is None
    assert client._resolve_api_base("claude-sonnet-4-6") is None


def test_litellm_args_token_plan_openai_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """xiaomi_mimo 配了 Token Plan base → 应重写为 openai/ 路由绕过 tools 不兼容。"""
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    client = LLMClient(
        model="xiaomi_mimo/mimo-v2.5-pro",
        api_keys={"xiaomi_mimo": "tp-abc"},
        api_bases={"xiaomi_mimo": "https://token-plan-sgp.xiaomimimo.com/v1"},
    )
    args = client._resolve_litellm_args("xiaomi_mimo/mimo-v2.5-pro")
    assert args["model"] == "openai/mimo-v2.5-pro"
    assert args["api_base"] == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert args["api_key"] == "tp-abc"


def test_litellm_args_no_rewrite_without_custom_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 api_base 时保持原 model 字符串，让 litellm 默认路由。"""
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    client = LLMClient(model="xiaomi_mimo/mimo-v2.5-pro", api_keys={})
    args = client._resolve_litellm_args("xiaomi_mimo/mimo-v2.5-pro")
    assert args == {"model": "xiaomi_mimo/mimo-v2.5-pro"}


def test_litellm_args_other_provider_only_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 xiaomi_mimo provider 只注入 api_base，不改 model 字符串。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from agent.llm_client import LLMClient

    client = LLMClient(
        model="deepseek/deepseek-v4-pro",
        api_keys={"deepseek": "sk-dummy"},
        api_bases={"deepseek": "https://proxy.example/v1"},
    )
    args = client._resolve_litellm_args("deepseek/deepseek-v4-pro")
    assert args == {"model": "deepseek/deepseek-v4-pro", "api_base": "https://proxy.example/v1"}
    assert "api_key" not in args  # 非 xiaomi_mimo 路径不显式塞 key


def test_llm_client_does_not_overwrite_existing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "from-shell")
    from agent.llm_client import LLMClient

    LLMClient(model="xiaomi_mimo/mimo-v2.5-pro", api_keys={"xiaomi_mimo": "from-config"})
    # 已有 env 优先（避免 CI/secrets 覆盖）
    assert os.environ["XIAOMI_MIMO_API_KEY"] == "from-shell"


def test_main_model_picker_lists_mimo_v2_5() -> None:
    from main import _AVAILABLE_MODELS

    ids = [m[0] for m in _AVAILABLE_MODELS]
    assert "xiaomi_mimo/mimo-v2.5-pro" in ids
    assert "xiaomi_mimo/mimo-v2.5" in ids
    assert "xiaomi_mimo/mimo-v2.5-flash" in ids


def test_litellm_routes_mimo_to_xiaomi_provider() -> None:
    """LiteLLM 必须能识别 xiaomi_mimo/ 前缀并指向官方 base_url。"""
    from litellm import get_llm_provider

    model, provider, _api_key, base_url = get_llm_provider("xiaomi_mimo/mimo-v2.5-pro")
    assert provider == "xiaomi_mimo"
    assert model == "mimo-v2.5-pro"
    assert base_url and "xiaomimimo.com" in base_url
