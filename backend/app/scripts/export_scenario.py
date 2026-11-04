"""Export a seeded scenario as one static JSON file for the backend-less demo frontend.

Usage::

    python -m app.scripts.export_scenario                                  # reference
    python -m app.scripts.export_scenario --profile lab --out ../frontend/public/scenario-lab.json

The script seeds a throw-away SQLite database with the chosen profile (rules mode, no
network), then calls the **real API** through ``TestClient`` for every GET request the UI
makes and stores each JSON response under a canonical request key. Every number in the file
is therefore exactly what the backend computed — the demo frontend only looks responses up
(``frontend/src/api/demo.ts``); it never computes anything.

Partner answers for the panel's suggestion questions are pre-computed on a *copy* of the
database, so the browsable snapshot stays identical to the seed (asking stores exchanges and
may run critiques). Two more stateless answers are recorded so the read-only demo can still
show them: the backend-rendered analysis reports (``text``, Markdown/CSV per experiment) and
the protocol extraction of one example paste (``protocol_example``; extraction saves nothing).

Key format (shared with ``demo.ts``): ``/api/...path?<query>`` with the query parameters
sorted by name, empty values dropped and pagination parameters (``limit``, ``offset``)
removed — the demo adapter re-applies ``limit`` to list responses.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.core.config import SeedProfileName, Settings
from app.core.db import Database
from app.main import create_app

FORMAT = "biopilot-scenario@1"
FRONTEND_PUBLIC = Path(__file__).resolve().parents[3] / "frontend" / "public"
DEFAULT_OUT: dict[str, Path] = {
    "reference": FRONTEND_PUBLIC / "scenario.json",
    "lab": FRONTEND_PUBLIC / "scenario-lab.json",
}
#: Must match ``SUGGESTIONS`` in ``frontend/src/features/partner-panel/PartnerPanel.tsx``.
ASK_SUGGESTIONS: tuple[str, ...] = (
    "회수율이 왜 낮나?",
    "다음 실험은 어떻게 설계할까?",
    "기각된 제안과 사유는?",
)
#: Search/recall terms pre-computed for the Overview search bar (plus codes and analytes).
SEARCH_TERMS: tuple[str, ...] = (
    "GCB",
    "PSA",
    "C18",
    "TPP",
    "IS",
    "회수율",
    "추출 시간",
    "pH",
    "메탄올",
    "매트릭스",
    "억제",
    "기기 점검",
)
#: Values pooled by the Records tab's "값 포함" filter (pre-computed per condition key).
RECORD_CONTAINS: tuple[str, ...] = ("GCB", "PSA", "C18", "메탄올", "TPP")
RECORD_CONTAINS_KEYS: tuple[str, ...] = (
    "cleanup_sorbent",
    "extraction_solvent",
    "internal_standard",
    "column",
)
#: Example paste for the Protocols tab's "예시 원문" button in the demo (extraction is
#: stateless, so its real response is recorded once). A range ("5~10분") is included on
#: purpose: the extractor leaves it empty instead of guessing.
PROTOCOL_EXAMPLE = """잔류농약 QuEChERS SOP (개정 초안)
1. 균질화한 사과 10 g을 50 mL 원심관에 칭량한다.
2. 1% 아세트산 아세토니트릴 10 mL를 넣고 추출 5~10분 진탕한다.
3. 아세테이트 완충염 (AOAC 2007.01) 첨가 후 1분 진탕, 원심분리 4000 rpm 5분.
4. 상등액을 d-SPE 튜브(PSA 50 mg + GCB 7.5 mg + MgSO4 150 mg)로 옮긴다.
5. LC-MS/MS (ESI+, MRM), 컬럼 C18 2.1×100 mm, 1.8 µm, 컬럼 온도 40 °C
6. 내부표준 TPP는 추출 전에 첨가한다.
"""
#: Report formats pre-rendered per experiment (``GET .../report?format=``).
REPORT_FORMATS: tuple[str, ...] = ("markdown", "csv")
PAGINATION = {"limit", "offset"}
#: Projects with at most this many experiments get every ordered compare/diff pair.
ALL_PAIRS_MAX = 12


def request_key(path: str, query: dict[str, Any] | None = None) -> str:
    """Canonical key: path + sorted non-empty, non-pagination query parameters."""
    items = sorted(
        (k, str(v)) for k, v in (query or {}).items() if v not in (None, "") and k not in PAGINATION
    )
    return f"{path}?{urlencode(items)}" if items else path


class Recorder:
    """Calls GET endpoints and keeps every JSON response under its request key.

    200 bodies go to ``responses``; 4xx answers (e.g. an experiment draft for an already
    decided proposal) go to ``errors`` so the demo replays them; 5xx aborts the export.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.responses: dict[str, Any] = {}
        self.errors: dict[str, dict[str, Any]] = {}
        self.texts: dict[str, dict[str, str]] = {}
        self.failures: list[str] = []

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        """GET ``path`` (once per key); returns the JSON body or ``None`` on a non-200."""
        key = request_key(path, query)
        if key in self.responses or key in self.errors:
            return self.responses.get(key)
        params = {k: v for k, v in (query or {}).items() if v not in (None, "")}
        res = self.client.get(path, params=params)
        if 400 <= res.status_code < 500:
            self.errors[key] = {"status": res.status_code, "body": res.json()}
            return None
        if res.status_code != 200:
            self.failures.append(f"{key} → {res.status_code}")
            return None
        body = res.json()
        self.responses[key] = body
        return body

    def get_text(self, path: str, query: dict[str, Any]) -> None:
        """GET a non-JSON download (report) and keep body, media type and filename header."""
        key = request_key(path, query)
        res = self.client.get(path, params=query)
        if res.status_code != 200:
            self.failures.append(f"{key} → {res.status_code}")
            return
        self.texts[key] = {
            "body": res.text,
            "content_type": res.headers.get("content-type", "text/plain"),
            "content_disposition": res.headers.get("content-disposition", ""),
        }


def _pairs(experiments: list[dict[str, Any]]) -> Iterable[tuple[int, int]]:
    ids = [e["id"] for e in experiments]
    if len(ids) <= ALL_PAIRS_MAX:
        yield from ((a, b) for a in ids for b in ids if a != b)
        return
    root = ids[0]
    seen: set[tuple[int, int]] = set()
    for i, e in enumerate(experiments):
        candidates = [(root, e["id"]), (e["id"], root)]
        if e.get("parent_experiment_id"):
            candidates += [
                (e["parent_experiment_id"], e["id"]),
                (e["id"], e["parent_experiment_id"]),
            ]
        if i > 0:
            candidates.append((ids[i - 1], e["id"]))
        for a, b in candidates:
            if a != b and (a, b) not in seen:
                seen.add((a, b))
                yield a, b


def _record_project(rec: Recorder, project: dict[str, Any], codes_elsewhere: list[str]) -> None:
    pid = project["id"]
    rec.get(f"/api/eln/projects/{pid}")
    experiments = rec.get(f"/api/eln/projects/{pid}/experiments") or []
    rec.get("/api/audit", {"project_id": pid, "limit": 100})
    rec.get(f"/api/eln/projects/{pid}/condition-template")
    rec.get(f"/api/eln/projects/{pid}/protocol-templates")
    rec.get(f"/api/eln/projects/{pid}/experiment-draft")
    rec.get(f"/api/eln/projects/{pid}/protocol-runs")
    rec.get(f"/api/eln/projects/{pid}/protocol-runs", {"status": "in_progress"})
    rec.get("/api/analysis/records/protocols", {"project_id": pid})
    templates = rec.get(f"/api/eln/projects/{pid}/protocol-templates", {"all_versions": "true"})
    for template in (templates or {}).get("items", []):
        rec.get(
            f"/api/eln/projects/{pid}/experiment-draft", {"protocol_template_id": template["id"]}
        )
    lineage = rec.get(f"/api/eln/projects/{pid}/protocol-lineage") or {"lineages": []}
    for item in lineage["lineages"]:
        ids = [v["template"]["template_id"] for v in item["versions"]]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                rec.get("/api/eln/protocol-diff", {"a": a, "b": b})
    rec.get(f"/api/memory/projects/{pid}/timeline")
    rec.get(f"/api/memory/projects/{pid}/knowledge-graph")
    rec.get(f"/api/memory/projects/{pid}/graph")
    rec.get(f"/api/analysis/projects/{pid}/trend")
    rec.get(f"/api/analysis/projects/{pid}/criteria")
    rec.get("/api/analysis/criteria", {"project_id": pid})
    for scope in ("project", "experiment", None):
        rec.get(f"/api/partner/projects/{pid}/critiques", {"scope": scope})
    rec.get(f"/api/partner/projects/{pid}/decisions")
    rec.get(f"/api/partner/projects/{pid}/exchanges")
    rec.get("/api/partner/hypotheses", {"project_id": pid})
    rec.get("/api/partner/proposals", {"project_id": pid})
    rec.get("/api/partner/proposals", {"project_id": pid, "sort": "priority"})

    analytes: set[str] = set()
    for exp in experiments:
        eid = exp["id"]
        rec.get(f"/api/eln/experiments/{eid}")
        for ds in rec.get(f"/api/eln/experiments/{eid}/datasets") or []:
            rec.get(f"/api/eln/datasets/{ds['id']}", {"limit": 20})
        rec.get(f"/api/eln/experiments/{eid}/history")
        rec.get(f"/api/eln/experiments/{eid}/audit", {"limit": 200})
        rec.get(f"/api/eln/projects/{pid}/experiment-draft", {"source_experiment_id": eid})
        rec.get(f"/api/memory/experiments/{eid}/digests")
        rec.get(f"/api/memory/experiments/{eid}/lineage")
        metrics = rec.get(f"/api/analysis/experiments/{eid}/metrics") or {}
        analytes |= {a["analyte"] for a in metrics.get("per_analyte_recovery", [])}
        rec.get("/api/analysis/results", {"experiment_id": eid})
        for fmt in REPORT_FORMATS:
            rec.get_text(f"/api/analysis/experiments/{eid}/report", {"format": fmt})
        rec.get(f"/api/partner/experiments/{eid}/critiques")
        rec.get("/api/partner/hypotheses", {"project_id": pid, "experiment_id": eid})
        for sort in (None, "priority"):
            proposals = rec.get(
                "/api/partner/proposals", {"project_id": pid, "experiment_id": eid, "sort": sort}
            )
            for p in proposals or []:
                rec.get(f"/api/partner/proposals/{p['id']}")
                rec.get(f"/api/partner/proposals/{p['id']}/experiment-draft")
        rec.get(f"/api/partner/projects/{pid}/decisions", {"experiment_id": eid})
        rec.get(f"/api/partner/projects/{pid}/exchanges", {"experiment_id": eid})
        rec.get(f"/api/partner/experiments/{eid}/precedents")
    for a, b in _pairs(experiments):
        rec.get("/api/memory/diff", {"a": a, "b": b})
        rec.get("/api/analysis/compare", {"a": a, "b": b})
    terms = [*SEARCH_TERMS, *sorted(analytes), *(e["code"] for e in experiments), *codes_elsewhere]
    for term in terms:
        rec.get(f"/api/memory/projects/{pid}/search", {"q": term, "limit": 20})
        rec.get(f"/api/memory/projects/{pid}/recall", {"q": term})


def _record_cross_project(rec: Recorder, projects: list[dict[str, Any]], terms: list[str]) -> None:
    """Cross-project search/recall, the Records tab and the failure archive (per scope)."""
    for term in terms:
        rec.get("/api/memory/search", {"q": term, "limit": 20})
        rec.get("/api/memory/recall", {"q": term})
    fields = rec.responses.get("/api/eln/condition-fields") or []
    keys = sorted({f["key"] for f in fields})
    for scope in [None, *(p["id"] for p in projects)]:
        query = {"project_id": scope}
        rec.get("/api/analysis/records/operators", query)
        rec.get("/api/analysis/records/periods", query)
        rec.get("/api/partner/failure-archive", query)
        rec.get("/api/memory/failures", query)
        for key in keys:
            rec.get("/api/analysis/records/conditions", {**query, "key": key})
            if key not in RECORD_CONTAINS_KEYS:
                continue
            for value in RECORD_CONTAINS:
                rec.get(
                    "/api/analysis/records/conditions", {**query, "key": key, "contains": value}
                )


def _ask_key(project_id: int, experiment_id: int | None, question: str) -> str:
    return f"{project_id}|{experiment_id if experiment_id is not None else ''}|{question.strip()}"


def _record_asks(client: TestClient, projects: list[dict[str, Any]]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for project in projects:
        pid = project["id"]
        experiments = client.get(f"/api/eln/projects/{pid}/experiments").json()
        for exp_id in [None, *(e["id"] for e in experiments)]:
            for question in ASK_SUGGESTIONS:
                body = {"project_id": pid, "experiment_id": exp_id, "question": question}
                res = client.post("/api/partner/ask", json=body)
                if res.status_code == 200:
                    answers[_ask_key(pid, exp_id, question)] = res.json()
    return answers


def build(profile: SeedProfileName) -> dict[str, Any]:
    """Seed ``profile`` in a temporary database and return the scenario document."""
    with tempfile.TemporaryDirectory(prefix="biopilot-scenario-") as tmp:
        root = Path(tmp)
        os.environ["BIOPILOT_ELN_STORAGE_DIR"] = str(root / "eln_storage")
        db_path = root / "seed.db"
        settings = Settings(
            auto_seed=True, seed_profile=profile, anthropic_api_key=None, force_rules_mode=True
        )
        with TestClient(create_app(settings, Database(f"sqlite:///{db_path}"))) as client:
            rec = Recorder(client)
            for path in (
                "/api/health",
                "/api/system/info",
                "/api/eln/projects",
                "/api/eln/condition-fields",
                "/api/eln/dataset-kinds",
                "/api/eln/import-formats",
                "/api/analysis/criteria",
                "/api/analysis/methods",
                "/api/partner/mode",
            ):
                rec.get(path)
            projects: list[dict[str, Any]] = rec.responses["/api/eln/projects"]
            codes = {
                p["id"]: [
                    e["code"] for e in client.get(f"/api/eln/projects/{p['id']}/experiments").json()
                ]
                for p in projects
            }
            for project in projects:
                elsewhere = [c for pid, cs in codes.items() if pid != project["id"] for c in cs]
                _record_project(rec, project, elsewhere)
            _record_cross_project(
                rec, projects, [*SEARCH_TERMS, *(c for cs in codes.values() for c in cs)]
            )
            extraction = client.post(
                "/api/eln/protocol-extractions", json={"text": PROTOCOL_EXAMPLE}
            )
            if extraction.status_code != 200:
                rec.failures.append(f"protocol example extraction → {extraction.status_code}")
        sandbox = root / "ask.db"
        shutil.copyfile(db_path, sandbox)
        with TestClient(create_app(settings, Database(f"sqlite:///{sandbox}"))) as client:
            asks = _record_asks(client, projects)
    if rec.failures:
        raise RuntimeError("scenario export: non-200 responses:\n" + "\n".join(rec.failures))
    return {
        "format": FORMAT,
        "profile": profile,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": (
            "Static snapshot of the BioPilot API for the backend-less demo. Read-only; "
            "Partner answers exist only for the panel's suggestion questions; protocol "
            "extraction only for the example paste."
        ),
        "ask_suggestions": list(ASK_SUGGESTIONS),
        "get": rec.responses,
        "errors": rec.errors,
        "text": rec.texts,
        "ask": asks,
        "protocol_example": {"text": PROTOCOL_EXAMPLE, "extraction": extraction.json()},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.export_scenario", description=__doc__
    )
    parser.add_argument("--profile", choices=("reference", "lab"), default="reference")
    parser.add_argument(
        "--out", type=Path, default=None, help="default: frontend/public/scenario[-lab].json"
    )
    args = parser.parse_args(argv)
    profile: SeedProfileName = args.profile
    out: Path = args.out or DEFAULT_OUT[profile]
    doc = build(profile)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = out.stat().st_size // 1024
    counts = f"{len(doc['get'])} GET responses, {len(doc['ask'])} answers, {size_kb} KB"
    print(f"wrote {out} ({profile}: {counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
