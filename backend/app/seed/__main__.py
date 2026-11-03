"""CLI: seed a database with a chosen profile.

Usage::

    python -m app.seed --profile lab                       # ./biopilot.db (BIOPILOT_DATABASE_URL)
    python -m app.seed --profile lab --database-url sqlite:///./lab.db

Only an empty database is seeded (existing projects are never touched).
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.db import Database
from app.seed.loader import seed_if_empty
from app.seed.spec import SEED_PROFILES


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, seed if empty, print a one-line summary. Returns the exit code."""
    parser = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__)
    parser.add_argument("--profile", choices=SEED_PROFILES, default="lab")
    parser.add_argument("--database-url", default=None, help="default: BIOPILOT_DATABASE_URL")
    args = parser.parse_args(argv)
    db = Database(args.database_url or get_settings().database_url)
    db.create_all()
    with db.session() as session:
        project_id = seed_if_empty(session, args.profile)
        session.commit()
    if project_id is None:
        print("database already has projects — nothing seeded")
    else:
        print(f"seeded profile {args.profile!r} (primary project id {project_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
