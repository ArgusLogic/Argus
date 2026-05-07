"""B5 项目状态存储测试。"""

from __future__ import annotations

import json
import os

import pytest

import tools.project_store as ps
from tools.project_store import (
    project_delete,
    project_list,
    project_load,
    project_save,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_projects(tmp_path, monkeypatch):
    """每个测试用 tmp 项目目录。"""
    p = tmp_path / "projects"
    p.mkdir()
    monkeypatch.setattr(ps, "PROJECTS_DIR", str(p))
    yield p


class TestSaveLoad:
    async def test_save_creates_file(self, _isolate_projects) -> None:
        result = await project_save(
            "chaoxing",
            json.dumps({"target": "chaoxing.com", "endpoints": ["/login"]}),
        )
        assert "项目已保存" in result
        assert (_isolate_projects / "chaoxing.json").exists()

    async def test_load_round_trip(self) -> None:
        await project_save("p1", json.dumps({"target": "x.com"}))
        loaded = await project_load("p1")
        data = json.loads(loaded)
        assert data["target"] == "x.com"
        assert "created_at" in data
        assert "updated_at" in data
        assert data["_project_name"] == "p1"

    async def test_save_invalid_json(self) -> None:
        result = await project_save("p", "not json")
        assert "JSON 解析失败" in result

    async def test_save_array_rejected(self) -> None:
        result = await project_save("p", "[1,2,3]")
        assert "必须是 JSON 对象" in result

    async def test_load_missing(self) -> None:
        result = await project_load("ghost")
        assert "不存在" in result

    async def test_save_preserves_created_at(self) -> None:
        await project_save("p", json.dumps({"v": 1}))
        first = json.loads(await project_load("p"))
        # 第二次 save：created_at 应保持
        await project_save("p", json.dumps({"v": 2}))
        second = json.loads(await project_load("p"))
        assert second["created_at"] == first["created_at"]
        assert second["v"] == 2

    async def test_filename_sanitized(self, _isolate_projects) -> None:
        """路径穿越的项目名会被剥离到 basename。"""
        await project_save("../../etc/evil", json.dumps({"v": 1}))
        # 应只在 PROJECTS_DIR 下创建 evil.json
        files = os.listdir(_isolate_projects)
        assert "evil.json" in files


class TestList:
    async def test_empty(self) -> None:
        result = await project_list()
        assert "暂无项目" in result

    async def test_list_after_save(self) -> None:
        await project_save("alpha", json.dumps({"target": "a.com"}))
        await project_save("beta", json.dumps({"target": "b.com"}))
        result = await project_list()
        assert "alpha" in result
        assert "beta" in result


class TestDelete:
    async def test_delete_existing(self, _isolate_projects) -> None:
        await project_save("doomed", json.dumps({"v": 1}))
        result = await project_delete("doomed")
        assert "已删除" in result
        assert not (_isolate_projects / "doomed.json").exists()

    async def test_delete_missing(self) -> None:
        result = await project_delete("ghost")
        assert "不存在" in result
