"""Pytest fixtures for Argus tests.

关键策略：
- 把 ~/.argus 路径全部重定向到 tmp_path，避免污染真实用户目录
- 提供 mock LLMClient，避免真实 API 调用
- 强制 ANSI 颜色关闭，让断言更稳定
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# 确保项目根目录在 sys.path 中（CI 兼容）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _isolate_argus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """每个测试用例都会自动获得隔离的 ~/.argus 目录。

    通过 monkeypatch 改写 utils.paths 模块下所有路径常量，
    并连带 patch 各使用方的 import-time 引用。
    """
    home = tmp_path / "argus_home"
    home.mkdir()

    sessions_dir = home / "sessions"
    skills_dir = home / "skills"
    memories_dir = home / "memories"
    output_dir = home / "output"
    logs_dir = output_dir / "logs"
    reports_dir = output_dir / "reports"
    screenshots_dir = output_dir / "screenshots"

    for d in (sessions_dir, skills_dir, memories_dir, logs_dir, reports_dir, screenshots_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 改写 utils.paths 自身
    import utils.paths as paths_mod

    monkeypatch.setattr(paths_mod, "SECAGENT_HOME", str(home))
    monkeypatch.setattr(paths_mod, "CONFIG_PATH", str(home / "config.toml"))
    monkeypatch.setattr(paths_mod, "HISTORY_PATH", str(home / "history"))
    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(paths_mod, "DB_PATH", str(sessions_dir / "sessions.db"))
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(paths_mod, "REPORTS_DIR", str(reports_dir))
    monkeypatch.setattr(paths_mod, "SCREENSHOTS_DIR", str(screenshots_dir))
    monkeypatch.setattr(paths_mod, "LOGS_DIR", str(logs_dir))
    monkeypatch.setattr(paths_mod, "SKILLS_DIR", str(skills_dir))
    skills_archive_dir = home / "skills_archive"
    skills_archive_dir.mkdir(parents=True, exist_ok=True)
    curator_reports_dir = home / "curator_reports"
    curator_reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths_mod, "SKILLS_ARCHIVE_DIR", str(skills_archive_dir))
    monkeypatch.setattr(paths_mod, "CURATOR_REPORTS_DIR", str(curator_reports_dir))
    monkeypatch.setattr(paths_mod, "MEMORIES_DIR", str(memories_dir))
    monkeypatch.setattr(paths_mod, "MEMORY_MD_PATH", str(memories_dir / "MEMORY.md"))
    monkeypatch.setattr(paths_mod, "USER_MD_PATH", str(memories_dir / "USER.md"))
    monkeypatch.setattr(paths_mod, "LESSONS_MD_PATH", str(memories_dir / "LESSONS.md"))

    # 同步 patch 已 import 这些常量的模块（import-time 拷贝）
    for mod_name in (
        "agent.memory_md",
        "agent.skills",
        "agent.session",
        "agent.memory",
        "agent.curator",
    ):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            for attr in (
                "MEMORY_MD_PATH",
                "USER_MD_PATH",
                "LESSONS_MD_PATH",
                "MEMORIES_DIR",
                "SKILLS_DIR",
                "SKILLS_ARCHIVE_DIR",
                "CURATOR_REPORTS_DIR",
                "DB_PATH",
                "SESSIONS_DIR",
            ):
                if hasattr(mod, attr):
                    monkeypatch.setattr(mod, attr, getattr(paths_mod, attr))

    yield home


@pytest.fixture
def mock_llm() -> MagicMock:
    """提供一个 mock LLMClient，避免真实 API 调用。"""
    llm = MagicMock()
    llm.model = "mock/model"
    llm.api_keys = {}
    llm.chat = AsyncMock()
    llm.chat_stream = AsyncMock()
    return llm


@pytest.fixture
def memory_md(_isolate_argus_home: Path):
    """干净的 MemoryMD 实例。"""
    from agent.memory_md import MemoryMD

    return MemoryMD()


@pytest.fixture
def skill_manager(_isolate_argus_home: Path):
    """干净的 SkillManager 实例（显式传入 tmp 目录避免默认参数缓存）。"""
    from agent.skills import SkillManager

    return SkillManager(skills_dir=str(_isolate_argus_home / "skills"))


@pytest.fixture
def sample_skill() -> dict[str, Any]:
    """范例技能字典。"""
    return {
        "name": "sample_recon",
        "description": "示例侦察技能",
        "steps": [
            {"tool": "http_get", "args_template": {"url": "https://example.com"}},
            {"tool": "http_post", "args_template": {"url": "https://example.com/api"}},
        ],
        "success_count": 0,
    }


@pytest.fixture
def quiet_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭 console 的 ANSI 颜色，方便断言。"""
    from utils import logger

    monkeypatch.setattr(logger.console, "is_terminal", False)


# ─── 为 pytest-asyncio 启用自动模式（已在 pyproject.toml 配置） ─────────────
