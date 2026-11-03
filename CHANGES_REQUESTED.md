# CHANGES_REQUESTED

다른 모듈(또는 공유 파일)에 필요한 변경을 여기에 적는다. 담당 세션이 처리 후 상태를 바꾼다.
규칙: [CLAUDE.md §3](CLAUDE.md#3-병렬-작업-규칙).

형식:

```
## [OPEN|DONE|REJECTED] <대상 모듈/파일> — <한 줄 요약>
- 요청자: <모듈/세션>  · 날짜: YYYY-MM-DD
- 필요 이유:
- 제안하는 계약 (엔드포인트/필드/함수 시그니처):
- 완료 기준:
```

---

## [OPEN] core — Alembic 마이그레이션 도입
- 요청자: skeleton · 날짜: 2026-11-03
- 필요 이유: 현재 `Base.metadata.create_all()`로 스키마를 만든다. 여러 모듈이 병렬로 컬럼을 추가하면
  기존 DB가 깨진다.
- 제안: `backend/migrations/` (Alembic), 모듈별 revision 파일명 접두사(`eln_`, `analysis_` …)로 충돌 감소.
  `create_app` 시작 시 `alembic upgrade head`.
- 완료 기준: 빈 DB/기존 DB 모두 `upgrade head` 성공, CI에서 `alembic check` 통과.

## [OPEN] core — 인증/사용자 식별
- 요청자: skeleton · 날짜: 2026-11-03
- 필요 이유: `Decision.decided_by`, `AuditEvent.actor`가 현재 고정 문자열("researcher", "user").
- 제안: `app/core/auth.py`에 `get_current_user` 의존성, AuditEvent에 `user_id` 컬럼 추가.
- 완료 기준: 모든 쓰기 엔드포인트가 사용자 id를 감사 이벤트에 남김.

## [OPEN] eln — `calibration_type` 조건 키 + 검량 CSV 선택 컬럼 `curve` (ANA-2)
- 요청자: analysis · 날짜: 2026-11-03
- 필요 이유: Analysis는 조건 블록의 `calibration_type`(`solvent` | `matrix-matched`)에 따라 검량 곡선을
  고른다. 현재는 `ConditionBlock(extra="allow")`의 extra 키로 읽고 있어 타입·라벨이 없다.
- 제안하는 계약:
  - `ConditionBlock.calibration_type: Literal["solvent", "matrix-matched"] | None = None`
  - `CONDITION_FIELD_LABELS["calibration_type"] = "검량 방식"`
  - `calibration` CSV에 **선택** 컬럼 `curve`(`solvent`|`matrix`) 허용을 계약 문서(`DATASET_COLUMNS` 주석)에 명시.
    컬럼이 없으면 데이터셋 전체를 선언된 방식의 곡선으로 본다(현재 Analysis 동작).
- 완료 기준: 필드 추가 후 Analysis 테스트(`test_matrix_matched_calibration_selects_matrix_curve`) 그대로 통과.

## [OPEN] eln — ELN-7 `ion_ratio` 데이터셋 계약 (ANA-8 소비 측 공지)
- 요청자: analysis · 날짜: 2026-11-03
- 필요 이유: Analysis `ion_ratio@1`은 구현 완료. 현재는 kind `ion_ratio` **또는** 아래 컬럼을 모두 가진
  `other` 데이터셋을 소비한다(ELN-7 전까지의 임시 경로).
- 제안하는 계약: `DATASET_COLUMNS["ion_ratio"] = ("injection_id", "sample_type", "analyte",
  "quantifier_area", "qualifier_area")`, `sample_type ∈ {standard, sample}`,
  `DATASET_NUMERIC_COLUMNS`에 `quantifier_area`, `qualifier_area` 추가, `DatasetKind`에 `"ion_ratio"` 추가.
- 완료 기준: kind `ion_ratio` 업로드 시 `POST /api/analysis/experiments/{id}/run`이 `ion_ratio` 결과 생성
  (Analysis 쪽은 추가 변경 불필요).

## [OPEN] partner — 프로젝트별 기준·신규 지표 사용
- 요청자: analysis · 날짜: 2026-11-03
- 필요 이유: 기준이 프로젝트별 버전(ANA-6)이 되었다. `partner/context.py`는 아직 `analysis.get_criteria()`
  (기본값)를 쓰므로 프로젝트 기준을 바꾸면 비판 문구의 기준과 플래그 기준이 어긋날 수 있다.
- 제안: `analysis.get_project_criteria(session, project_id).active.criteria` 사용.
  새로 쓸 수 있는 근거 값: `ExperimentMetrics.qc_verdicts / limits / expanded_uncertainty_pct / outlier_count`,
  `MetricsComparison.per_analyte[].p_holm / hedges_g / ci_low / ci_high`, `significant_analytes`.
- 완료 기준: 기준 v1 생성 후 비판의 기준 Evidence가 v1 값을 인용.

## [OPEN] docs — ARCHITECTURE.md Analysis 계약 갱신
- 요청자: analysis · 날짜: 2026-11-03
- 내용: §3 analysis 표에 `GET /api/analysis/methods`, `GET/POST /api/analysis/projects/{project_id}/criteria`,
  `GET /api/analysis/experiments/{experiment_id}/report?format=markdown|csv`, `GET /api/analysis/criteria?project_id`
  추가. 결과 종류에 `limits`, `ion_ratio` 추가. §2 analysis 테이블에 `analysis_criteria_versions` 추가.
- 참고: Overview의 `TrendPoint.flag_count`에는 새 플래그(정보 수준 `loq_above_lowest_level` 포함)가 합산된다.
