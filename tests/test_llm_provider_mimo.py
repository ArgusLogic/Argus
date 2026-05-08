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
