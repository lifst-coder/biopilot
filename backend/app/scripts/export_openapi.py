"""Write the OpenAPI schema to ``backend/openapi.json`` (consumed by the frontend codegen).

Usage: ``python -m app.scripts.export_openapi [--check]``. ``--check`` exits 1 when the
committed file is stale (used by CI and the contract test).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.core.db import Database
from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def render() -> str:
    """Deterministic, pretty-printed OpenAPI JSON."""
    app = create_app(Settings(auto_seed=False), Database("sqlite://"))
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else ""
        if current != text:
            print("openapi.json is stale — run: python -m app.scripts.export_openapi")
            return 1
        print("openapi.json is up to date")
        return 0
    OPENAPI_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
