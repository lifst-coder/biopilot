"""Profile selection end-to-end: app auto-seed via env var and the ``python -m app.seed`` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Database
from app.eln import service as eln
from app.main import create_app
from app.seed.__main__ import main as seed_cli
from app.seed.loader import PROFILE_ENV


def test_app_auto_seeds_lab_profile_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "lab")
    app = create_app(Settings(auto_seed=True, anthropic_api_key=None), Database("sqlite://"))
    with TestClient(app) as c:
        projects = c.get("/api/eln/projects").json()
        assert [p["experiment_count"] for p in projects] == [30, 12]
        acids = projects[1]["id"]
        assert len(c.get(f"/api/memory/projects/{acids}/timeline").json()) == 12
        graph = c.get(f"/api/memory/projects/{acids}/graph").json()
        assert len(graph["roots"]) == 1 and len(graph["edges"]) == 11
        trend = c.get(f"/api/analysis/projects/{acids}/trend").json()
        assert all(p["source_result_ids"] for p in trend)
        rejected = c.get(
            "/api/partner/proposals", params={"project_id": acids, "status": "rejected"}
        )
        assert len(rejected.json()) == 5
        assert all(p["decision"]["rationale"].startswith("[") for p in rejected.json())


def test_app_auto_seed_defaults_to_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    app = create_app(Settings(auto_seed=True, anthropic_api_key=None), Database("sqlite://"))
    with TestClient(app) as c:
        assert [p["experiment_count"] for p in c.get("/api/eln/projects").json()] == [7]


def test_cli_seeds_an_empty_database_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'lab.db'}"
    assert seed_cli(["--profile", "lab", "--database-url", url]) == 0
    assert "seeded profile 'lab'" in capsys.readouterr().out
    assert seed_cli(["--profile", "lab", "--database-url", url]) == 0
    assert "nothing seeded" in capsys.readouterr().out


def test_cli_default_profile_matches_the_app(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--profile`` the CLI seeds what the app would: ``reference``."""
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    url = f"sqlite:///{tmp_path / 'default.db'}"
    assert seed_cli(["--database-url", url]) == 0
    assert "seeded profile 'reference'" in capsys.readouterr().out
    db = Database(url)
    with db.session() as s:
        assert [p.experiment_count for p in eln.list_projects(s)] == [7]


def test_settings_seed_profile_selects_lab(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings.seed_profile`` (core) drives the app's auto-seed; env sets it too."""
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    assert Settings().seed_profile == "reference"
    monkeypatch.setenv(PROFILE_ENV, "lab")
    assert Settings().seed_profile == "lab"
    monkeypatch.delenv(PROFILE_ENV)
    settings = Settings(auto_seed=True, anthropic_api_key=None, seed_profile="lab")
    with TestClient(create_app(settings, Database("sqlite://"))) as c:
        assert [p["experiment_count"] for p in c.get("/api/eln/projects").json()] == [30, 12]
