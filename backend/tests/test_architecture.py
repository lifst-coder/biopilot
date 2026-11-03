"""Enforces module boundaries (CLAUDE.md §모듈 경계) by static import analysis.

* Layer order ELN → Memory → Analysis → Partner: a module may only depend on the
  modules listed in ``ALLOWED`` (lower layers).
* Cross-module imports must target ``app.<module>.service`` or ``app.<module>.schemas``.
* ``app.core`` must not import feature modules (``app.models_registry`` is the
  composition root and is exempt).
* ``app/wiring.py`` is the core-owned composition root that connects higher-layer
  services to lower-layer ports (e.g. Memory's fact providers). It may import feature
  modules only through ``app.<module>.service`` / ``app.<module>.schemas`` (plus
  ``app.core``), and no feature module may import it (only ``app.main`` does).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
MODULES = ("eln", "memory", "analysis", "partner")
ALLOWED: dict[str, set[str]] = {
    "eln": set(),
    "memory": {"eln"},
    "analysis": {"eln"},
    "partner": {"eln", "memory", "analysis"},
}
PUBLIC = {"service", "schemas"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in {f"app.{m}" for m in MODULES}:
                names += [f"{node.module}.{a.name}" for a in node.names]
            else:
                names.append(node.module)
    return [n for n in names if n.startswith("app.")]


def _sources(module: str) -> list[Path]:
    return [p for p in (APP / module).rglob("*.py") if "tests" not in p.parts]


@pytest.mark.parametrize("module", MODULES)
def test_module_dependencies_follow_layers(module: str) -> None:
    violations: list[str] = []
    for path in _sources(module):
        for name in _imports(path):
            parts = name.split(".")
            target = parts[1]
            if target not in MODULES or target == module:
                continue
            if target not in ALLOWED[module]:
                violations.append(f"{path.relative_to(APP)} imports {name} (layer violation)")
            elif len(parts) < 3 or parts[2] not in PUBLIC:
                violations.append(f"{path.relative_to(APP)} imports {name} (not service/schemas)")
    assert violations == []


def test_core_does_not_import_feature_modules() -> None:
    violations = [
        f"{p.relative_to(APP)} imports {name}"
        for p in (APP / "core").rglob("*.py")
        for name in _imports(p)
        if name.split(".")[1] in MODULES
    ]
    assert violations == []


def test_every_module_has_required_files() -> None:
    for module in MODULES:
        for name in ("__init__.py", "models.py", "schemas.py", "service.py", "router.py"):
            assert (APP / module / name).exists(), f"{module}/{name} missing"
        assert list((APP / module / "tests").glob("test_*.py")), f"{module} has no tests"


def test_tables_are_prefixed_by_owning_module() -> None:
    from app.core.db import Base
    from app.main import create_app  # noqa: F401  (registers models)

    for table in Base.metadata.tables:
        assert table.split("_")[0] in {*MODULES, "core"}, table


WIRING = APP / "wiring.py"


def test_wiring_imports_only_service_and_schemas() -> None:
    """The composition root reaches feature modules only through their public API."""
    violations: list[str] = []
    for name in _imports(WIRING):
        parts = name.split(".")
        if parts[1] == "core":
            continue
        if parts[1] not in MODULES or len(parts) < 3 or parts[2] not in PUBLIC:
            violations.append(f"wiring.py imports {name} (only app.<module>.service/schemas)")
    assert violations == []


def test_feature_modules_do_not_import_wiring() -> None:
    """Wiring is installed by ``app.main``; feature code must not depend on it."""
    violations = [
        f"{p.relative_to(APP)} imports app.wiring"
        for module in MODULES
        for p in _sources(module)
        if any(n == "app.wiring" or n.startswith("app.wiring.") for n in _imports(p))
    ]
    assert violations == []
