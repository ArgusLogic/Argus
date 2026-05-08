"""回归：main.py 不应再有重复的 `import contextlib`。

历史 bug：函数体内重复 `import contextlib` 让 contextlib 变 local 名，触发
UnboundLocalError: cannot access local variable 'contextlib'。
顶部 module-level 已 import 一次，所有函数体内不该再 import。
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_contextlib_imported_only_at_module_level() -> None:
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    module_level_count = 0
    inside_function_count = 0

    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name == "contextlib" for a in node.names):
            module_level_count += 1

    # 函数体里的 contextlib import（任何深度）
    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0
            self.found = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.depth += 1
            for child in ast.walk(node):
                if isinstance(child, ast.Import) and any(a.name == "contextlib" for a in child.names):
                    self.found += 1
            self.depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.depth += 1
            for child in ast.walk(node):
                if isinstance(child, ast.Import) and any(a.name == "contextlib" for a in child.names):
                    self.found += 1
            self.depth -= 1

    v = _Visitor()
    v.visit(tree)
    inside_function_count = v.found

    assert module_level_count == 1, (
        f"main.py 应该只在 module level import contextlib 一次，找到 {module_level_count}"
    )
    assert inside_function_count == 0, (
        f"main.py 函数体内不应再 import contextlib（会触发 UnboundLocalError），"
        f"找到 {inside_function_count} 处"
    )
