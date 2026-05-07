"""C3 — agentskills.io 兼容（导入/导出）测试。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agent.skill_interop import (
    _argus_to_hyphen,
    _hyphen_to_argus,
    _parse_frontmatter,
    export_skill,
    from_agentskills,
    import_skill,
    to_agentskills,
)


def _sample_skill() -> dict[str, Any]:
    return {
        "name": "recon_pipeline",
        "description": "DNS+WHOIS+安全头一站式基础侦察",
        "steps": [
            {"tool": "dns_lookup", "args_template": {"domain": "example.com"}},
            {"tool": "whois_lookup", "args_template": {"domain": "example.com"}},
        ],
        "content": "# Recon Pipeline\n\n按顺序跑 DNS / WHOIS / 安全头。",
        "success_count": 7,
        "created_at": "2026-05-07T20:00:00",
        "pinned": True,
    }


# ─── 名称归一 ────────────────────────────────────────────────────────────────


class TestNameConversion:
    def test_argus_to_hyphen(self) -> None:
        assert _argus_to_hyphen("recon_pipeline") == "recon-pipeline"
        assert _argus_to_hyphen("ALREADY-OK") == "already-ok"
        assert _argus_to_hyphen("__weird___") == "weird"
        assert _argus_to_hyphen("") == "unnamed-skill"

    def test_hyphen_to_argus(self) -> None:
        assert _hyphen_to_argus("recon-pipeline") == "recon_pipeline"
        assert _hyphen_to_argus("--leading--") == "leading"
        assert _hyphen_to_argus("") == "unnamed_skill"


# ─── frontmatter 解析 ───────────────────────────────────────────────────────


class TestFrontmatter:
    def test_basic_keys(self) -> None:
        text = "---\nname: foo\ndescription: bar\n---\nbody here"
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "foo"
        assert fm["description"] == "bar"
        assert body.strip() == "body here"

    def test_nested_metadata(self) -> None:
        text = '---\nname: foo\nmetadata:\n  author: "alice"\n  version: "1.0"\n---\nbody'
        fm, _body = _parse_frontmatter(text)
        assert fm["metadata"] == {"author": "alice", "version": "1.0"}

    def test_no_frontmatter_returns_full_body(self) -> None:
        text = "just some markdown"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == text


# ─── Round-trip Argus ↔ agentskills ────────────────────────────────────────


class TestExport:
    def test_to_agentskills_includes_required_fields(self) -> None:
        text = to_agentskills(_sample_skill())
        assert "---" in text
        assert "name: recon-pipeline" in text
        assert "description: DNS+WHOIS+" in text
        assert "argus-success-count" in text
        assert "argus-pinned" in text
        # body 包含 content
        assert "Recon Pipeline" in text
        # body 包含 step listing
        assert "1. `dns_lookup`" in text

    def test_export_writes_file(self, tmp_path: Path) -> None:
        path = export_skill(_sample_skill(), str(tmp_path))
        assert path.endswith(os.path.join("recon-pipeline", "SKILL.md"))
        assert os.path.exists(path)
        text = Path(path).read_text(encoding="utf-8")
        assert "name: recon-pipeline" in text


class TestImport:
    def test_from_agentskills_parses(self) -> None:
        text = (
            "---\n"
            "name: pdf-processing\n"
            "description: Extract PDF text and fill forms.\n"
            "metadata:\n"
            '  argus-success-count: "5"\n'
            '  argus-pinned: "true"\n'
            "---\n"
            "# PDF Processing\nDo X.\n"
        )
        skill = from_agentskills(text)
        assert skill["name"] == "pdf_processing"
        assert skill["description"] == "Extract PDF text and fill forms."
        assert skill["success_count"] == 5
        assert skill["pinned"] is True
        assert "PDF Processing" in skill["content"]
        assert skill["imported_from"] == "agentskills.io"

    def test_invalid_name_rejected(self) -> None:
        text = "---\nname: PDF-Processing\ndescription: x\n---\nbody"
        with pytest.raises(ValueError, match="agentskills"):
            from_agentskills(text)

    def test_missing_name_rejected(self) -> None:
        text = "---\ndescription: x\n---\nbody"
        with pytest.raises(ValueError, match="name"):
            from_agentskills(text)

    def test_import_skill_from_directory(self, tmp_path: Path) -> None:
        # 写一个 SKILL.md
        skill_dir = tmp_path / "demo-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: A demo.\n---\nDo demo.",
            encoding="utf-8",
        )
        skill = import_skill(str(skill_dir))
        assert skill["name"] == "demo_skill"
        assert "Do demo" in skill["content"]

    def test_import_skill_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            import_skill(str(tmp_path / "ghost.md"))


# ─── Round-trip ─────────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_export_then_import_preserves_core_fields(self, tmp_path: Path) -> None:
        original = _sample_skill()
        path = export_skill(original, str(tmp_path))
        imported = import_skill(os.path.dirname(path))
        # name 在 hyphen↔underscore 转换后保留
        assert imported["name"] == "recon_pipeline"
        assert imported["description"] == original["description"]
        assert imported["success_count"] == 7
        assert imported.get("pinned") is True
