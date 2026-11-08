# SPDX-License-Identifier: GPL-3.0-or-later
"""Enforce the package dependency rules (docs/decisions/0002).

- core never imports cli or studio (anywhere, including inside functions).
- cli and studio never import each other.
- PySide6 is only imported in studio.
- Heavy dependencies are never imported at module level in core or cli.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src" / "openpitch"

HEAVY = {"torch", "torchvision", "ultralytics", "onnxruntime", "tensorrt", "cv2", "PySide6"}

FORBIDDEN = {
    "core": {"openpitch.cli", "openpitch.studio", "PySide6"},
    "cli": {"openpitch.studio", "PySide6"},
    "studio": {"openpitch.cli"},
}


def _imports(path: Path, *, top_level_only: bool = False):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = tree.body if top_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module
        elif isinstance(node, ast.ImportFrom) and node.level > 1:
            # Relative imports reaching outside the subpackage are not allowed.
            yield node.lineno, "<relative import outside subpackage>"


def _matches(name: str, prefixes: set[str]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


@pytest.mark.parametrize("subpkg", sorted(FORBIDDEN))
def test_forbidden_imports(subpkg):
    forbidden = FORBIDDEN[subpkg] | {"<relative import outside subpackage>"}
    violations = [
        f"{path.relative_to(PKG.parent)}:{lineno}: {name}"
        for path in sorted((PKG / subpkg).rglob("*.py"))
        for lineno, name in _imports(path)
        if _matches(name, forbidden)
    ]
    assert not violations, "forbidden imports:\n" + "\n".join(violations)


@pytest.mark.parametrize("subpkg", ["core", "cli"])
def test_heavy_imports_are_lazy(subpkg):
    violations = [
        f"{path.relative_to(PKG.parent)}:{lineno}: {name}"
        for path in sorted((PKG / subpkg).rglob("*.py"))
        for lineno, name in _imports(path, top_level_only=True)
        if _matches(name, HEAVY)
    ]
    assert not violations, "heavy module-level imports:\n" + "\n".join(violations)


def test_import_core_and_cli_loads_no_heavy_modules():
    code = (
        "import sys, openpitch.core, openpitch.cli, openpitch.studio\n"
        f"heavy = {sorted(HEAVY)!r}\n"
        "print(','.join(m for m in heavy if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    assert out.stdout.strip() == "", f"heavy modules loaded on import: {out.stdout.strip()}"
