"""Loads the seed project into an empty database through the public module services.

Seeding goes through the same service interfaces a user would hit (so every record
is audited with actor ``seed``) and then runs the deterministic analyses, rules-mode
digests and a rules-mode critique of #024 so every screen has data on first start.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.core.llm import RulesOnlyGateway
from app.eln import service as eln
from app.eln.models import Project
from app.eln.schemas import (
    Attachment,
    ConditionBlock,
    DatasetCreate,
    ExperimentCreate,
    ProjectCreate,
)
from app.memory import service as memory
from app.partner import service as partner

DATA_DIR = Path(__file__).parent / "data"


def load_seed_spec() -> dict[str, Any]:
    """Parsed ``seed.json`` (project + experiment originals)."""
    return dict(json.loads((DATA_DIR / "seed.json").read_text(encoding="utf-8")))


def seed(session: Session) -> int:
    """Insert the seed project and derived records. Returns the project id."""
    spec = load_seed_spec()
    project = eln.create_project(session, ProjectCreate(**spec["project"]), actor="seed")
    ids_by_code: dict[str, int] = {}
    for item in spec["experiments"]:
        parent = item["parent_code"]
        exp = eln.create_experiment(
            session,
            project.id,
            ExperimentCreate(
                code=item["code"],
                title=item["title"],
                author=item["author"],
                performed_on=date.fromisoformat(item["performed_on"]),
                parent_experiment_id=ids_by_code[parent] if parent else None,
                raw_note=item["raw_note"],
                condition_block=ConditionBlock.model_validate(item["condition_block"]),
                attachments=[Attachment.model_validate(a) for a in item["attachments"]],
            ),
            actor="seed",
        )
        ids_by_code[item["code"]] = exp.id
        for ds in item["datasets"]:
            eln.create_dataset(
                session,
                exp.id,
                DatasetCreate(
                    kind=ds["kind"],
                    filename=ds["file"],
                    content=(DATA_DIR / ds["file"]).read_text(encoding="utf-8"),
                ),
                actor="seed",
            )
    rules = RulesOnlyGateway()
    for exp_id in ids_by_code.values():
        analysis.run_experiment(session, exp_id, actor="seed")
        memory.create_digest(session, exp_id, gateway=rules)
    partner.run_critique(session, ids_by_code["#024"], gateway=rules)
    return project.id


def seed_if_empty(session: Session) -> int | None:
    """Seed only when no project exists. Returns the new project id or ``None``."""
    if session.scalar(select(Project.id).limit(1)) is not None:
        return None
    return seed(session)
