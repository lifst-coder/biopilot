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

> **2026-11-03 병합 정리(integration).** feature/{analysis, eln, memory, partner, seed-expansion}을 main에 병합하면서
> 각 브랜치의 CR을 `feature/review:docs/REVIEW.md` ⑤ "중복·상충 정리" 표대로 합쳤다.
> 중복은 1건으로 묶고 원래 요청자를 모두 적었다. 이미 완료된 항목은 `[DONE]`으로 남기고 근거 커밋/테스트를 적었다.
> 우선순위는 [ISSUES.md](ISSUES.md)에 있다.

---

## 열린 요청 (OPEN)

### 공유 파일 · core

## [OPEN] core — 인증/사용자 식별
- 요청자: skeleton · 날짜: 2026-11-03
- 필요 이유: `Decision.decided_by`, `AuditEvent.actor`가 현재 고정 문자열("researcher", "user").
- 제안: `app/core/auth.py`에 `get_current_user` 의존성, AuditEvent에 `user_id` 컬럼 추가(Alembic revision 필요).
- 완료 기준: 모든 쓰기 엔드포인트가 사용자 id를 감사 이벤트에 남김.
- 비고: README "의도적으로 구현하지 않은 것"(로그인·권한). 데모 범위 밖.

## [OPEN] tests/test_contract.py — `file_id` 경로 파라미터 + 시드 첨부 파일
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: `test_every_get_endpoint_returns_real_data`가 모든 GET 경로를 고정 파라미터로 호출하므로
  첨부 다운로드 `GET /api/eln/attachment-files/{file_id}/content`는 `include_in_schema=False`로 계약에서 빠져 있다
  (UI는 `AttachmentFileOut.download_url`을 사용).
- 제안: `PATH_PARAMS`에 `"file_id": "1"` 추가 + 시드에 첨부 바이너리 1개(예: #024 크로마토그램). 그 뒤 ELN이
  엔드포인트를 스키마에 포함시키고 계약을 재생성한다. 시드 첨부는 아래 "시드 데이터 추가" 1건에 묶었다.
- 완료 기준: 다운로드 엔드포인트가 openapi.json/schema.d.ts에 포함되고 계약 테스트 통과.

## [OPEN] ci / pyproject — ELN 커버리지 측정(pytest-cov)
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: ELN 완료 기준 "eln 테스트 커버리지 90% 이상". 로컬 측정 98.6%(`pytest app/eln --cov=app/eln`).
- 제안: dev 의존성 `pytest-cov`, CI `pytest app/eln --cov=app/eln --cov-fail-under=90`, `.gitignore`에 `.coverage`.
- 완료 기준: CI에서 ELN 커버리지 게이트 동작. (TASKS에 근거가 없는 선택 항목 — REVIEW §ELN-5)

### 계약 문서

## [OPEN] docs — ARCHITECTURE.md 갱신 (3건 → 1건)
- 요청자: analysis, eln, seed (+ memory·partner가 직접 수정한 부분의 정합성 확인) · 날짜: 2026-11-03
- 반영할 내용:
  - **analysis**: §3 표에 `GET /api/analysis/methods`, `GET/POST /api/analysis/projects/{project_id}/criteria`,
    `GET /api/analysis/experiments/{experiment_id}/report?format=markdown|csv`, `GET /api/analysis/criteria?project_id`.
    결과 종류 `limits`, `ion_ratio`. §2 테이블 `analysis_criteria_versions`. 플래그 `calibration_type_unsupported`.
  - **eln**: `GET /dataset-kinds`, `GET /import-formats`, 목록 필터·`X-Total-Count`, `experiment-draft`,
    `condition-template`·`condition-check`, `protocol-templates`, `PATCH /experiments/{id}/metadata`(409),
    `addenda`, `history`, `audit`, multipart `datasets/upload|import`, `datasets/validate(-upload)`,
    `import/preview`, `attachment-files`. 소유 테이블 5개 추가, 불변 필드 `cloned_from_experiment_id`·
    `protocol_template_id`, 설정 `BIOPILOT_ELN_STORAGE_DIR`(기본 `./eln_storage`).
  - **seed**: §5에 `reference`/`lab` 프로파일 표, `backend/app/seed/SCENARIO.md` 링크, 원본 위치 `data/residue.json` 등.
  - **integration 결정**: `app/wiring.py`(core 소유 composition root), Alembic(`app/core/migrations`, baseline 0001),
    `Settings.seed_profile`, `calibration_type` 도메인, memory diff `qc_info_changes`, `ClaudeGateway.stream_text`.
  - memory·partner가 직접 추가한 API 표·원칙 문단은 위 내용과 대조해 표현을 통일한다.
- 완료 기준: §2·§3·§5가 `backend/openapi.json`의 경로 목록과 일치.

### ELN

## [OPEN] eln — ConditionBlock 정식 필드 + 조건 키 라벨 (도메인 결정 반영, 4건 → 1건)
- 요청자: analysis(`calibration_type` 2값), partner(`calibration_type` 3값 + `spike_stage` + `is_addition_stage`),
  seed(라벨), integration(도메인 결정) · 날짜: 2026-11-03
- **도메인 결정(integration):** `calibration_type ∈ {solvent, matrix-matched, standard-addition}`, 미기록 = `solvent`.
  계약 상수 `app.analysis.schemas.CalibrationTypeValue` / `CALIBRATION_TYPE_VALUES`.
  - Analysis(완료): `solvent`·`matrix-matched`만 정량. `standard-addition`·도메인 밖 값은 조용히 `solvent`로
    처리하지 않고 critical 플래그 `calibration_type_unsupported`(context: declared, supported)를 붙이며 회수율·IS 결과를
    만들지 않는다(`skipped`에 사유). `calibration@4`, `recovery@3`. 테스트
    `test_unsupported_calibration_type_is_flagged_not_silently_solvent`.
  - Partner: `knowledge.MATRIX_MATCHED_VALUES`는 standard-addition을 매트릭스 보정으로 본다(화학적으로 맞다).
    Analysis가 정량하지 못하므로 그 실험에는 회수율 근거가 없다.
- 요청(ELN):
  - `ConditionBlock.calibration_type: Literal["solvent","matrix-matched","standard-addition"] | None`
  - `spike_stage: str | None`, `is_addition_stage: Literal["pre-extraction","post-extraction"] | None`
  - `CONDITION_FIELD_LABELS`: `calibration_type: 검량 방식`, `spike_stage: 첨가 시점`, `is_addition_stage: IS 첨가 시점`,
    `mobile_phase: 이동상`, `injection_volume_ul: 주입량 (µL)`, `injection_dilution: 주입 희석`
  - `calibration` CSV 선택 컬럼 `curve`(`solvent`|`matrix`)를 `DATASET_COLUMNS` 주석에 명시(현재 Analysis 동작).
  - 기존 extra 값 하위호환(대소문자·`_`/공백 별칭은 Analysis가 이미 정규화한다).
- ~~남은 상충(Partner)~~ **해결(2026-11-03, ISSUES P1-2):** `pre_post_spike`는 `calibration_type = matrix-matched` +
  `curves_compared = "solvent + matrix-matched"`를 낸다. `partner.knowledge.out_of_domain_changes()`가 Claude 초안·수정
  결정의 도메인 밖 값을 막는다. lab 결정 이력은 `pre_post_spike`를 가리키지 않아 서명 갱신이 필요 없었다.
  ELN이 Literal 필드를 도입해도 Partner 초안은 도메인 안 값만 낸다.
- 완료 기준: `/api/eln/condition-fields`에 6개 키 포함, `test_matrix_matched_calibration_selects_matrix_curve` 통과,
  Partner 초안이 400 없이 생성.

## [OPEN] frontend/notebook (ELN) — CompareModal에 Memory 결과·QC 차이와 단어 diff 표시 (ExperimentDiffView에서 재지정)
- 요청자: memory · 날짜: 2026-11-03
- **재지정(integration):** 원래 대상 `features/notebook/ExperimentDiffView.tsx`는 ELN이 삭제하고 `CompareModal.tsx`로
  대체했다(Memory와 협의 기록 없음 — CLAUDE.md §3, REVIEW §7-5). 결과 차이를 그리는 경로가 둘이다:
  memory `ExperimentDiff.result_changes`(출처 포함)와 analysis `compare`. CompareModal은 analysis `compare`를 쓰고,
  병합 중 "분석 실행" 버튼(`useRunAnalysis`)과 info 플래그 제외 QC 개수만 추가했다.
- 요청: Notebook·Memory 담당이 경로 하나로 통일할지 정하고, CompareModal에 memory `qc_changes`
  (appeared/resolved/persisting), `qc_info_changes`(info 등급, 별도 표기), `note_diff[].segments` 단어 강조,
  `result_changes[].sources`(분석 결과 id)를 표시한다.
- 완료 기준: #018 vs #024에서 회수율 Δ와 출처, 새로 생긴 QC 플래그, "10"→"5" 단어 강조가 화면에 보임.

### Memory

## [OPEN] memory — 연구자 결정 사유를 Research Memory 검색에 반영 (wiring pull로 통일)
- 요청자: partner(push 안: `create_knowledge_note(source_ref)`), memory(wiring pull) · 날짜: 2026-11-03
- **결정(integration): wiring pull로 통일한다.** partner가 memory를 호출하는 push 안은 채택하지 않는다(아래 REJECTED).
  근거: `app/wiring.py PartnerFactProvider`가 이미 결정(`action: rationale`)을 지식 그래프 노드로 읽어 온다
  (`describe`, `texts={"rationale": ...}`). Partner `decide()`에 Memory 쓰기를 추가하면 같은 사실이 두 경로로 생긴다.
- 요청(memory): FTS 검색 인덱스(`search_index.py`)가 fact port의 결정 텍스트(`rationale`)도 색인한다.
  `memory.schemas.FactProvider`에 필요한 메서드가 있으면 추가하고 `app/wiring.py`의 구현을 함께 고친다.
- 완료 기준: 기각 사유 텍스트가 `/api/memory/projects/{id}/search` 결과에 나타나고 출처가 `partner.Decision:<id>`.

## [DONE] memory + partner — 제안 → 후속 실험(`tests_proposal`) 매칭 계약
- 요청자: integration(REVIEW §7-3), seed(정답 데이터 공지) · 날짜: 2026-11-03
- 필요 이유: `memory/conditions.py proposal_tests`는 제안 `changes`의 모든 키가 자식 실험 조건 블록에 같은 값으로
  있어야 연결한다. Partner 설계형 제안(`design: factorial 2x2`, `factor_<key>: a | b`, `"solvent + matrix-matched"`)은
  조건 블록에 존재할 수 없어 MEM-1 엣지가 거의 생기지 않는다.
- 제안: `ProposalOut.implementing_changes`(조건 블록 단위 변경 목록, 추가 필드)를 Partner가 채우고 Memory가 그것으로 매칭.
- 정답 데이터(seed): `load_seed_spec("lab").history.decisions[*].followed_by` — 수락/수정 결정 7건의 후속 실험
  (#007 #017 #025 #026 #028 #OA07 #OA11). 결정은 `decision.proposal.template_id/signature`로 제안을 지정한다.
- 완료 기준: lab 시드에서 7개 `tests_proposal` 엣지 확인.
- **완료(2026-11-03, ISSUES P1-10):** `ProposalOut.implementing_changes`(partner) → `ProposalFact.changes/status/decided_on`
  (wiring) → `memory.conditions.proposal_tests`(결정일 이후, 부모 대비 실제 변경, 계보 무관, 기각 제외).
  `tests/test_accumulation_lab.py::test_tests_proposal_edges_are_the_seven_follow_ups`.

## [OPEN] memory — 보충 기록(addenda)을 검색·정리본 입력에 포함 검토
- 요청자: eln · 날짜: 2026-11-03
- 내용: `ExperimentOut.addenda[]`(불변, 원본 메모와 분리). Memory `search`와 정리본 프롬프트가 보충 기록도 참조하면
  "나중에 알게 된 사실"이 기억에 반영된다(원본 `raw_note`는 그대로).

### Analysis

## [DONE] analysis (+ eln) — 숫자 칸 결측(NaN) 처리
- 요청자: seed · 날짜: 2026-11-03
- 필요 이유: ELN `_validate_csv`는 빈 숫자 칸을 통과시키고 `calibrate`/`fit_line`이 NaN을 받아 slope=NaN 결과를
  **저장**한다(재현: 검량선 CSV 한 행의 analyte_area를 비우고 run).
- 제안: Analysis가 NaN 행을 제외하고 `excluded_rows`를 기록(+ 플래그 `missing_values`, `METHOD_VERSIONS` 올림),
  또는 ELN이 빈 숫자 칸을 400으로 거부 — 둘 중 하나는 필요.
- 완료 기준: 빈 칸 CSV로 NaN이 저장되지 않는 테스트.
- **완료(2026-11-03, ISSUES P1-3):** 둘 다 했다. ELN은 빈 칸(`blank_value`, 기존)과 `inf`(`not_finite`, 신규)를 거부하고,
  Analysis는 비유한 입력을 `skipped`로 보고하며 비유한 출력은 저장하지 않는다. 출력 형태 변화가 없어 METHOD_VERSIONS 유지.
  `test_missing_or_non_finite_numbers_are_never_stored`, `test_non_finite_output_is_not_stored`.

## [OPEN] analysis — 전·후 첨가 비교(`spike_recovery`) 결과 종류
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: Designer 최우선 제안(추출 전·후 첨가)의 RE = pre/post, ME = post/용매, PE = pre/용매 계산이 필요하다.
  Partner는 숫자를 계산하지 않는다.
- 제안: ELN dataset kind `spike_recovery`(injection_id, analyte, spike_stage(pre|post|solvent), level_ng_ml,
  analyte_area, is_area) + result kind `spike_recovery`(분석물별 RE·ME·PE, QC 플래그).
- 완료 기준: `ExperimentMetrics`에 분석물별 RE/ME 필드(추가만).

## [OPEN] analysis — IS 이탈 주입별 회수율 층화 + 요인 실험 분산분석
- 요청자: partner · 날짜: 2026-11-03
- 제안: `RecoveryOutput.by_is_flag: {flagged, normal, welch_p}`(추가 필드), result kind `factorial`
  (조건 블록 `design = factorial 2x2`, `factor_<key>`).
- 완료 기준: 시드 #024에서 by_is_flag 생성, 요인 실험 단위 테스트.

### Partner

## [DONE] partner — 결정 기록의 actor·시점
- 요청자: seed · 날짜: 2026-11-03
- 필요 이유: `decide()`는 감사 actor를 `"user"`로 고정하고 `created_at`은 현재 시각뿐이다. lab 시드의 과거 결정 14건이
  사용자 행위·시드 실행일로 기록된다(다른 시드 레코드는 actor=`seed`).
- 제안: `decide(..., *, actor: Actor = "user")`, `DecisionCreate.decided_on: date | None`(필드 추가만).
- 완료 기준: 시드 결정의 감사 actor가 `seed`, `decided_on`이 실험 날짜 이후. (시드는 `loader._replay_history`에서 인자만 넘긴다.)
- **완료(2026-11-03, ISSUES P1-9):** 제안대로 + `partner_decisions.decided_on` 컬럼(Alembic `0002_decision_decided_on`),
  감사 payload `decided_by`·`decided_on`. `tests/test_seed_lab.py::test_decisions_are_seed_actions_dated_on_their_experiment`.

## [OPEN] partner — Memory recall/근거 조각 활용 검토
- 요청자: memory · 날짜: 2026-11-03
- 내용: `memory.service.recall()` / `ask()`가 출처가 붙은 `EvidenceFragment`를 반환한다. Partner `/ask` 컨텍스트 보강에 쓸 수 있다.

### Seed

## [OPEN] seed — 시드 데이터 추가 (3건 → 1건)
- 요청자: eln(조건·프로토콜 템플릿, 첨부 파일), memory(지식 노트 예시) · 날짜: 2026-11-03
- 제안:
  - `eln.create_condition_template(...)`(기본 규칙과 동일, actor=seed),
    `eln.create_protocol_template(name="AOAC 2007.01 기준 프로토콜", source_experiment_id=#018, actor="seed")`
  - #024 첨부 바이너리 1개(위 `test_contract` `file_id` 요청의 선행 조건)
  - `memory.create_knowledge_note(..., actor="seed")` #024 연결 예시 1건
  - `test_principles`의 기대 엔티티 목록에 새 엔티티 추가.
- 완료 기준: 새 DB에서 Notebook "프로토콜 템플릿으로 채우기"에 1개 이상, Overview 그래프에 note 노드 표시.

## [OPEN] eln/memory/analysis/partner 테스트 — 시드 모양 하드코딩 제거
- 요청자: seed · 날짜: 2026-11-03
- 필요 이유: 모듈 테스트가 reference 시드 모양(id 1/7 = #018/#024, 타임라인 7건, `"7건"` 문구 등)에 묶여 있다.
- 제안: id 대신 `seeded["#024"]`, 개수는 시드 대비 상대 검증. 각 모듈 담당이 자기 테스트를 고친다.
- **완료 기준 정정(REVIEW §11-4):** `BIOPILOT_SEED_PROFILE=lab pytest`는 `client` 픽스처에만 적용되고 `seeded`
  픽스처(`backend/conftest.py`)는 reference로 고정이다. 기준은 "lab 프로파일 픽스처를 추가하고 그 위에서 모듈
  테스트가 통과"로 바꾼다. 기본 시드는 reference로 유지한다(integration 결정).

### Frontend Shell

## [OPEN] frontend/shell — `api/types.ts` 별칭 추가 (3건 → 1건)
- 요청자: eln(notebook), memory, partner · 날짜: 2026-11-03
- 별칭: `DatasetValidation`, `CsvIssue`, `ConditionIssue`, `HistoryEntry`, `ExperimentAddendumOut`, `AttachmentFileOut`,
  `ProtocolTemplateOut`, `ImportPreview` (eln) · `KnowledgeGraph`, `KGNode`, `KGEdge`, `SearchHit`, `RecallBundle`,
  `MemoryAnswer`, `SimilarExperiment`, `ConditionMatrix`, `ConditionHistoryEntry`, `KnowledgeNoteOut` (memory) ·
  `CriticAssessment`, `ExperimentDesign`, `DecisionHistoryEntry`, `AnswerStatement` (partner).
- 완료 기준: 공용 별칭 추가 후 각 화면이 로컬 `Schemas[...]` 별칭을 제거(각 담당 후속).

## [OPEN] frontend/shell — 프로젝트 선택
- 요청자: seed · 날짜: 2026-11-03
- 필요 이유: `lib/selection.ts useActiveProject()`가 첫 프로젝트만 쓴다. lab 시드에는 프로젝트가 2개(유기산 #OA01–#OA12).
- 제안: 헤더 프로젝트 전환 + URL `?project=<id>`, 전환 시 `?exp=` 초기화.
- 완료 기준: lab 시드에서 두 프로젝트의 4탭이 모두 렌더.

## [OPEN] frontend/shell — Overview가 프로젝트 활성 QC 기준을 쓰도록 `useCriteria(projectId)` 호출
- 요청자: integration · 날짜: 2026-11-03
- 기록: analysis 병합으로 공유 훅 `useCriteria`가 `useCriteria(projectId?: number | null)`로 바뀌었다(queryKey
  `["analysis","criteria",projectId??null]`, `staleTime: Infinity` 제거). 인자 없는 호출은 기본 기준을 돌려주므로
  하위 호환이다. `features/overview/OverviewPage.tsx`는 인자 없이 호출해 **기본 기준**만 표시한다.
- 완료 기준: 프로젝트 기준 v1 생성 후 Overview의 기준 표시가 v1 값을 따른다.

## [OPEN] frontend/shell — 전역 검색 바를 헤더로 이동
- 요청자: memory · 날짜: 2026-11-03
- 제안: `features/overview/GlobalSearchBar.tsx`(+ `highlight.tsx`)를 `components/`로 옮겨 AppShell 헤더에 장착.
  (memory가 Frontend Shell 영역 `features/overview/**`를 직접 수정한 것은 REVIEW §Memory-4 경계 위반으로 기록)
- 완료 기준: 모든 탭에서 검색 가능, 결과 클릭 시 `/notebook?exp=`.

---

## 완료·종결 (DONE / REJECTED)

## [DONE] core — Alembic 마이그레이션 도입 (3건 → 1건)
- 요청자: skeleton, eln("기존 로컬 DB 재생성 필요"), memory("마이그레이션 대상 추가") · 날짜: 2026-11-03
- 처리(integration): `app/core/migrate.py` + `app/core/migrations/`(env.py `render_as_batch=True`, FTS5
  `memory_search_fts*`는 autogenerate 제외 — Memory가 검색 인덱스 동기화 때 생성), 병합된 전체 스키마를 baseline
  revision `0001_baseline` 하나로. `create_app`은 `Database.prepare_schema()`(빈 DB → create_all + stamp,
  관리 DB → upgrade head, Alembic 이전 DB → `LegacyDatabaseError`). CI `alembic upgrade head && alembic check`.
  기존 `biopilot.db`·`./eln_storage` 재생성 절차는 README. 테스트 `tests/test_migrations.py`.

## [DONE] core / pyproject — `python-multipart` 의존성 (ELN 업로드)
- 요청자: eln · 처리: feature/eln 4e7d365 — `python-multipart>=0.0.18` 선언, Starlette `MultiPartParser` 기반으로 교체
  (닫는 경계 없는 본문·CTE·헤더 공백 400, 테스트 `app/eln/tests/test_upload_integrity.py`). REVIEW C3·C4 해소.

## [DONE] core/composition — `app/wiring.py` 소유권
- 요청자: memory · 결정(integration): **승인.** core 소유 composition root(CLAUDE.md §2·§3 공유 파일). `main.py` import 1줄 +
  `install_memory_fact_providers()` 1줄 승인. `tests/test_architecture.py`: `test_wiring_imports_only_service_and_schemas`,
  `test_feature_modules_do_not_import_wiring`. Analysis/Partner는 서비스 시그니처를 바꿀 때 wiring도 함께 고친다.

## [DONE] core — LLM 게이트웨이 텍스트 스트리밍 (`stream_text`)
- 요청자: partner · 처리(integration): `core/llm.py` `StreamingLLMGateway`·`LLMStreamError`·`ClaudeGateway.stream_text`
  (`client.beta.messages.stream`, effort, server-side fallback, refusal·API 오류 시 예외). 테스트 `tests/test_llm_stream.py`
  (스텁 클라이언트, 거절·연결 오류, 스트리밍 미지원 게이트웨이의 비스트리밍 경로).

## [DONE] core — 시드 프로파일 설정
- 요청자: seed · 처리(integration): `Settings.seed_profile`(`BIOPILOT_SEED_PROFILE`, 기본 `reference`), `main.py`가
  `seed_if_empty(session, settings.seed_profile)`, `.env.example`. 테스트 `test_settings_seed_profile_selects_lab`.

## [DONE] partner — 프로젝트별 기준 사용
- 요청자: analysis · 처리(integration): `partner/context.py` 두 곳과 `partner/service.py:_pool_index`가
  `get_project_criteria(...).active.criteria`. 테스트 `app/partner/tests/test_project_criteria.py`.
  신규 지표(`qc_verdicts`, `p_holm`, `hedges_g` …) 활용은 ISSUES.md.

## [DONE] analysis (frontend hook) — `useRunAnalysis` 훅
- 요청자: frontend/notebook · 처리: analysis 브랜치가 이미 구현(중복 요청). 병합 중 Notebook CompareModal이 사용:
  "현재/기준 실험 미분석" 표시 + "분석 실행" 버튼(`NotebookViews.test.tsx`).

## [DONE] eln ↔ analysis — ELN-7 `ion_ratio@1` 계약 (양방향 충족)
- 요청자: analysis(요청), eln(공지) · 처리: ELN `DATASET_KIND_REGISTRY` `ion_ratio@1`, Analysis는 병합 후 `kind == "ion_ratio"`만
  읽는다(`other` 경유 임시 경로 제거). 통합 테스트 `test_eln_ion_ratio_upload_feeds_analysis_run`.

## [DONE] partner — 기각된 제안 반복 금지 (결정 이력 인지 비판)
- 요청자: seed · 처리: feature/partner `app/partner/feedback.py`(서명 제외·자원 제약·`supersedes_proposal_ids`).
  seed lab 프로브에서 재등장 0건, `test_seed_lab.py`의 xfail 제거. 반복 요청 금지.

## [DONE] tests — `tests/test_contract.py` 파라미터 표 추가 (memory 공지)
- 요청자: memory · 내용: 새 GET 엔드포인트용 `PATH_PARAMS["key"]`와 `QUERY_PARAMS`만 추가(검사 로직 불변).
  자기 승인([DONE] 표기)은 순서가 뒤바뀐 것이어서 integration이 사후 확인했다.

## [DONE] frontend — Memory 계약 공지 (MEM-5 등)
- 요청자: memory · 내용: `compare-conditions`, `/conditions/{key}/history`, `/experiments/{id}/similar`, `/projects/{id}/recall`,
  `POST /projects/{id}/ask`, `/projects/{id}/knowledge-notes`, `/graph?relations=`. 공지만이며 계약은 openapi.json에 있다.

## [REJECTED] memory — `create_knowledge_note(source_ref)`로 Partner가 결정을 push
- 요청자: partner · 사유: 위 "결정 사유를 Research Memory 검색에 반영"에서 wiring pull로 통일.
