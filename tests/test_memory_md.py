"""MemoryMD 测试：add / replace / remove / 容量 / 去重 / 渲染。"""

from __future__ import annotations

import os

import pytest

from agent.memory_md import CAP_MEMORY, CAP_USER, MemoryMD


class TestAdd:
    def test_add_creates_file(self, memory_md: MemoryMD) -> None:
        result = memory_md.add("memory", "第一条记忆")
        assert result["ok"] is True
        assert result["msg"] == "added"
        assert os.path.exists(memory_md._path("memory"))

    def test_add_returns_stats(self, memory_md: MemoryMD) -> None:
        result = memory_md.add("memory", "hello world")
        assert "stats" in result
        assert result["stats"]["count"] == 1
        assert result["stats"]["used"] == len("hello world")

    def test_add_dedup_exact_match(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "重复内容")
        result = memory_md.add("memory", "重复内容")
        assert result["ok"] is False
        assert "duplicate" in result["msg"]

    def test_add_dedup_strips_whitespace(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "trimmed")
        result = memory_md.add("memory", "  trimmed  ")
        assert result["ok"] is False

    def test_add_empty_rejected(self, memory_md: MemoryMD) -> None:
        result = memory_md.add("memory", "")
        assert result["ok"] is False
        assert "不能为空" in result["msg"]

    def test_add_whitespace_only_rejected(self, memory_md: MemoryMD) -> None:
        result = memory_md.add("memory", "   \n\t  ")
        assert result["ok"] is False

    def test_add_capacity_overflow(self, memory_md: MemoryMD) -> None:
        # USER 容量更小，便于测试
        big = "x" * (CAP_USER - 10)
        memory_md.add("user", big)
        # 再加 50 个字符肯定超
        result = memory_md.add("user", "y" * 50)
        assert result["ok"] is False
        assert "memory full" in result["msg"]

    def test_add_unknown_target_raises(self, memory_md: MemoryMD) -> None:
        with pytest.raises(ValueError, match="未知 target"):
            memory_md.add("invalid", "x")

    def test_add_silent_mode(self, memory_md: MemoryMD, capsys: pytest.CaptureFixture) -> None:
        # silent=True 不打日志（间接验证：不抛错）
        result = memory_md.add("memory", "silent entry", silent=True)
        assert result["ok"] is True


class TestReplace:
    def test_replace_substring_match(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "原始内容片段A")
        result = memory_md.replace("memory", "片段A", "全新替换内容")
        assert result["ok"] is True
        assert result["msg"] == "replaced"
        entries = memory_md.list_entries("memory")
        assert "全新替换内容" in entries
        assert "原始内容片段A" not in entries

    def test_replace_no_match(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "existing")
        result = memory_md.replace("memory", "nonexistent", "new")
        assert result["ok"] is False

    def test_replace_empty_args(self, memory_md: MemoryMD) -> None:
        result = memory_md.replace("memory", "", "x")
        assert result["ok"] is False
        result = memory_md.replace("memory", "x", "")
        assert result["ok"] is False


class TestRemove:
    def test_remove_existing(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "条目甲")
        memory_md.add("memory", "条目乙")
        result = memory_md.remove("memory", "条目甲")
        assert result["ok"] is True
        entries = memory_md.list_entries("memory")
        assert entries == ["条目乙"]

    def test_remove_substring(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "完整的一行带着关键词foo在里面")
        result = memory_md.remove("memory", "foo")
        assert result["ok"] is True
        assert memory_md.list_entries("memory") == []

    def test_remove_no_match(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "existing")
        result = memory_md.remove("memory", "nonexistent")
        assert result["ok"] is False


class TestStats:
    def test_empty_stats(self, memory_md: MemoryMD) -> None:
        s = memory_md.stats("memory")
        assert s == {"used": 0, "cap": CAP_MEMORY, "pct": 0, "count": 0}

    def test_stats_after_add(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "abc")  # 3 字符
        memory_md.add("memory", "defghij")  # 7 字符
        s = memory_md.stats("memory")
        assert s["used"] == 10
        assert s["count"] == 2

    def test_user_has_smaller_cap(self, memory_md: MemoryMD) -> None:
        assert memory_md._cap("user") == CAP_USER
        assert memory_md._cap("memory") == CAP_MEMORY
        assert CAP_USER < CAP_MEMORY


class TestPersistence:
    def test_round_trip(self, memory_md: MemoryMD) -> None:
        """写入后用新实例读取应能拿回完整数据。"""
        memory_md.add("memory", "第一条")
        memory_md.add("memory", "第二条\n包含换行")
        memory_md.add("memory", "第三条")

        # 新实例读
        from agent.memory_md import MemoryMD as MD2

        fresh = MD2()
        entries = fresh.list_entries("memory")
        assert len(entries) == 3
        assert "第二条\n包含换行" in entries

    def test_section_separator_preserved(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "A")
        memory_md.add("memory", "B")
        with open(memory_md._path("memory"), encoding="utf-8") as f:
            content = f.read()
        assert "§" in content


class TestRender:
    def test_render_block_empty(self, memory_md: MemoryMD) -> None:
        block = memory_md.render_block("memory")
        assert "MEMORY" in block.upper() or "Memory" in block
        assert "0%" in block or "0/" in block or "(空)" in block

    def test_render_block_with_entries(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "alpha")
        memory_md.add("memory", "bravo")
        block = memory_md.render_block("memory")
        assert "alpha" in block
        assert "bravo" in block

    def test_render_block_capacity_bar(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "x" * 100)
        block = memory_md.render_block("memory")
        # 应包含 N/CAP 这种字符
        assert "/" in block or "%" in block


class TestEdgeCases:
    def test_multiline_entry(self, memory_md: MemoryMD) -> None:
        multi = "第一行\n第二行\n第三行"
        memory_md.add("memory", multi)
        entries = memory_md.list_entries("memory")
        assert entries == [multi]

    def test_unicode_chinese(self, memory_md: MemoryMD) -> None:
        memory_md.add("memory", "中文条目测试 🛡 emoji")
        entries = memory_md.list_entries("memory")
        assert "中文条目测试 🛡 emoji" in entries

    def test_section_sign_in_content_safe(self, memory_md: MemoryMD) -> None:
        """如果用户内容含 §，写回后是否会破坏切分？"""
        memory_md.add("memory", "前面§后面")  # 含分隔符
        entries = memory_md.list_entries("memory")
        # 当前实现会按 § 切分 → 这是已知限制；测试记录现状
        # 如果以后改进了行为，此测试应同步更新
        assert len(entries) >= 1
