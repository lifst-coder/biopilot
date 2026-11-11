"""QC 검증 도구가 내보낸 CSV를 BioPilot 본편 코드로 검증한다.

1. 본편 ELN의 업로드 검증(``app.eln.service.validate_csv_text``)을 통과하는가.
2. 본편 L3의 Python 계산(``app.analysis.calculations``)이 같은 원자료에서 내는 기울기·절편·R²·회수율이
   QC 검증 도구(JavaScript)의 계산값과 일치하는가.

실행 (저장소 루트에서, backend 가상환경 사용)::

    node qc-validator/scripts/eln-export.mjs qc-validator/data/scenarios/S4_B04-SPIKE.csv B04-SPIKE /tmp/eln
    backend/.venv/bin/python qc-validator/scripts/verify_eln_bridge.py /tmp/eln B04-SPIKE

이 스크립트는 본편 모듈을 읽기만 한다. 본편의 어떤 파일도 바꾸지 않는다.
"""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import pandas as pd  # noqa: E402

from app.analysis.calculations import calibrate, compute_recovery  # noqa: E402
from app.eln.service import validate_csv_text  # noqa: E402

REL_TOL = 1e-9


def main(out_dir: str, batch: str) -> int:
    """Validate the exported pair and compare numbers; return a process exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 코드페이지와 무관하게 한글 출력
    base = Path(out_dir)
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in batch)
    cal_text = (base / f"{safe}_calibration.csv").read_text(encoding="utf-8")
    rec_text = (base / f"{safe}_recovery.csv").read_text(encoding="utf-8")
    reference = json.loads((base / f"{safe}_qc_reference.json").read_text(encoding="utf-8"))
    failures = 0

    for kind, text in (("calibration", cal_text), ("recovery", rec_text)):
        result = validate_csv_text(kind, text, filename=f"{safe}_{kind}.csv")  # type: ignore[arg-type]
        errors = [i for i in result.issues if i.level == "error"]
        print(f"[계약] {kind}: {result.schema_ref}, {result.row_count}행, ok={result.ok}")
        for issue in errors:
            print(f"        오류 {issue.code}: {issue.message}")
        failures += 0 if result.ok else 1

    cal_frame = pd.read_csv(io.StringIO(cal_text))
    fits = calibrate(cal_frame, reference["weighting"], use_is=True)
    for analyte, ref in reference["calibration"].items():
        fit = fits[analyte].fit
        for name, mine, theirs in (
            ("slope", ref["slope"], fit.slope),
            ("intercept", ref["intercept"], fit.intercept),
            ("r_squared", ref["r_squared"], fit.r_squared),
        ):
            ok = math.isclose(mine, theirs, rel_tol=REL_TOL, abs_tol=1e-12)
            failures += 0 if ok else 1
            print(f"[계산] {analyte} {name}: JS {mine:.12g} / Python {theirs:.12g} → {'일치' if ok else '불일치'}")

    rec_frame = pd.read_csv(io.StringIO(rec_text))
    if len(rec_frame):
        # 환산 계수 1(추출 부피 = 시료 질량)로 두면 본편의 ng/g 값이 바이알 내 농도와 같아진다.
        rows, _groups = compute_recovery(rec_frame, fits, extraction_volume_ml=1.0, sample_mass_g=1.0)
        by_key = {(r.analyte, r.sample_id): r.recovery_pct for r in rows}
        for ref in reference["recovery"]:
            theirs = by_key[(ref["analyte"], ref["sample_id"])]
            ok = math.isclose(ref["recovery_pct"], theirs, rel_tol=REL_TOL)
            failures += 0 if ok else 1
            print(
                f"[계산] {ref['analyte']} {ref['sample_id']} 회수율: JS {ref['recovery_pct']:.9f}% / "
                f"Python {theirs:.9f}% → {'일치' if ok else '불일치'}"
            )
    print("결과:", "모두 일치" if failures == 0 else f"불일치 {failures}건")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python verify_eln_bridge.py <eln-export 출력 폴더> <배치 ID>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
