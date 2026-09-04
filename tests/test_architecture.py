"""The layering guard.

``structura.core`` must be importable and fully usable with no GUI toolkit present. This is
what keeps the solver testable on its own and what stops Qt objects from creeping into the
numerical code. It runs in a subprocess with PySide6 poisoned so an accidental import fails
loudly rather than succeeding on a developer machine that happens to have Qt installed.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_GUARD = """
import sys

class _Blocked:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in {"PySide6", "PyQt5", "PyQt6", "shiboken6", "tkinter"}:
            raise ImportError(f"GUI toolkit {root!r} must not be imported by structura.core")
        return None

sys.meta_path.insert(0, _Blocked())

import structura.core                      # noqa: F401
import structura.core.units                # noqa: F401
import structura.core.geometry             # noqa: F401
import structura.core.validation           # noqa: F401
import structura.core.examples as examples
import structura.core.io as io

s = examples.t2_triangular_truss()
assert len(s.nodes) == 3 and len(s.members) == 3
assert io.loads(io.dumps(s)).content_hash() == s.content_hash()
print("CORE_OK")
"""


def test_core_imports_without_any_gui_toolkit() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _GUARD],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "structura.core pulled in a GUI toolkit or failed to import:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "CORE_OK" in result.stdout


def test_core_never_imports_a_gui_toolkit_anywhere_in_its_source() -> None:
    """A static backstop for lazy imports inside functions, which the runtime test cannot reach.

    Walks the AST rather than grepping text, so a docstring may state the rule (as
    ``structura/core/__init__.py`` does) without tripping it.
    """
    banned = {"PySide6", "PyQt5", "PyQt6", "shiboken6", "tkinter", "matplotlib"}
    offenders: list[str] = []

    for path in (PROJECT_ROOT / "structura" / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in banned:
                    location = f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
                    offenders.append(f"{location} imports {root}")

    assert not offenders, "GUI/plotting toolkit imported inside structura.core:\n" + "\n".join(
        offenders
    )
