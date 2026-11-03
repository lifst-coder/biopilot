"""ELN test fixtures: isolate the attachment blob store per test."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def eln_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the content-addressed store at a temp dir for every ELN test."""
    root = tmp_path / "eln_storage"
    monkeypatch.setenv("BIOPILOT_ELN_STORAGE_DIR", str(root))
    return root
