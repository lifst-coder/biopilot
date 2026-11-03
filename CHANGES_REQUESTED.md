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

## [OPEN] frontend/shell — Overview가 프로젝트 활성 QC 기준을 쓰도록 `useCriteria(projectId)` 호출
- 요청자: integration(병합 세션) · 날짜: 2026-11-03
- 기록: analysis 병합으로 공유 훅 `useCriteria`의 시그니처가 `useCriteria(projectId?: number | null)`로
  바뀌었다(queryKey `["analysis","criteria",projectId??null]`, `staleTime: Infinity` 제거).
  인자 없는 호출은 그대로 기본 기준을 돌려주므로 하위 호환이다.
  `features/overview/OverviewPage.tsx`는 여전히 인자 없이 호출해 **기본 기준**만 표시한다.
- 제안: Overview가 선택된 프로젝트 id를 넘겨 활성 기준을 표시한다(Frontend Shell 담당).
- 완료 기준: 프로젝트 기준 v1 생성 후 Overview의 기준 표시가 v1 값을 따른다.

## [OPEN] core / pyproject — `python-multipart` 의존성 추가 (ELN 업로드를 `UploadFile`로 전환)
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: ELN-1/4/9 multipart 엔드포인트(`/datasets/upload`, `/datasets/import`, `/datasets/validate-upload`,
  `/import/preview`, `/attachment-files`)는 FastAPI `UploadFile`/`Form`에 필요한 `python-multipart`가 없어
  `app/eln/multipart.py`(표준 `email` 파서)로 직접 파싱한다. 크기 제한·스트리밍은 직접 처리 중.
- 제안: `pyproject.toml` dependencies에 `python-multipart>=0.0.9`. 추가되면 ELN이 라우터를 `UploadFile`로 바꾸고
  `multipart.py`를 제거한다(요청 형식은 동일한 multipart/form-data라 계약 변경 없음).
- 완료 기준: 의존성 추가 후 ELN 업로드 테스트 그대로 통과.

## [OPEN] ci / pyproject — ELN 커버리지 측정(pytest-cov)
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: ELN 완료 기준이 "eln 테스트 커버리지 90% 이상". 현재 로컬에서 `pytest-cov`를 따로 설치해 측정
  (`pytest app/eln --cov=app/eln` → 소스 1220문 중 17문 미실행, 98.6%).
- 제안: dev 의존성에 `pytest-cov`, CI에 `pytest app/eln --cov=app/eln --cov-fail-under=90` 단계. `.gitignore`에 `.coverage`.
- 완료 기준: CI에서 ELN 커버리지 게이트 동작.

## [OPEN] tests/test_contract.py — `file_id` 경로 파라미터 + 시드 첨부 파일
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: `test_every_get_endpoint_returns_real_data`가 모든 GET 경로를 고정 파라미터로 호출하므로
  첨부 다운로드 `GET /api/eln/attachment-files/{file_id}/content`는 `include_in_schema=False`로 계약에서 빠져 있다
  (UI는 `AttachmentFileOut.download_url`을 사용).
- 제안: `PATH_PARAMS`에 `"file_id": "1"` 추가 + 시드에 첨부 바이너리 1개(예: #024 크로마토그램) 저장.
  그 뒤 ELN이 엔드포인트를 스키마에 포함시키고 계약을 재생성한다.
- 완료 기준: 다운로드 엔드포인트가 openapi.json/schema.d.ts에 포함되고 계약 테스트 통과.

## [OPEN] seed — 시드 프로젝트 조건 템플릿·프로토콜 템플릿 명시 저장
- 요청자: eln · 날짜: 2026-11-03
- 필요 이유: ELN-5 "시드 프로젝트 템플릿 포함"은 현재 내장 기본 템플릿(`app/eln/conditions.py: DEFAULT_RULES`,
  version 0, `source="default"`)으로 충족된다. 프로토콜 템플릿 목록은 시드에서 비어 있다.
- 제안: `seed()` 끝에 `eln.create_condition_template(...)`(기본 규칙과 동일, actor=seed)와
  `eln.create_protocol_template(name="AOAC 2007.01 기준 프로토콜", source_experiment_id=#018, actor="seed")`.
  주의: 감사 이벤트가 추가되므로 `test_principles`의 기대 엔티티에 `eln.ConditionTemplate`/`eln.ProtocolTemplate` 추가 가능.
- 완료 기준: 새 DB에서 Notebook "프로토콜 템플릿으로 채우기"에 1개 이상 표시.

## [OPEN] analysis — ELN-7 데이터셋 계약 공지: `ion_ratio@1` 및 버전 레지스트리 (ANA-8 선행 조건 충족)
- 요청자: eln · 날짜: 2026-11-03
- 내용: `app.eln.schemas.DATASET_KIND_REGISTRY`(`kind@version`), `kind_spec()`, `latest_kind_spec()` 공개.
  `DATASET_COLUMNS`는 최신 버전 기준으로 그대로 유지(하위호환). 신규 kind `ion_ratio@1`:
  필수 `injection_id, sample_type(standard|sample), analyte, quantifier_area, qualifier_area`,
  선택 `sample_id, level_ng_ml`. `DatasetOut`에 `schema_version`, `schema_ref`, `source_encoding`,
  `supersedes_dataset_id`, `superseded_by_dataset_id`, `source_attachment_id` 필드 추가(제거 없음).
- 재업로드 의미: 같은 kind의 새 데이터셋이 이전 것을 대체(`supersedes_dataset_id`), 이전 것은 보관.
  Analysis의 "kind별 최신 데이터셋 사용" 규칙과 일치 — 변경 불필요.
- 완료 기준: Analysis가 ANA-8에서 `ion_ratio` 소비.

## [OPEN] analysis (frontend hook) — `useRunAnalysis` 훅
- 요청자: frontend/notebook · 날짜: 2026-11-03
- 필요 이유: Notebook에서 새로 만든 실험은 분석 결과가 없어서 "과거 실험과 비교" 모달의 결과 차이 표가
  비어 있다. 분석 실행 엔드포인트(`POST /api/analysis/experiments/{id}/run`)용 훅이 queries.ts analysis 섹션에 없다.
- 제안: analysis 섹션에 `useRunAnalysis()` 추가(성공 시 `["analysis"]` 무효화). Notebook이 업로드 후 "분석 실행" 버튼으로 사용.
- 완료 기준: 훅 추가 후 Notebook에서 업로드 → 분석 실행 → 비교 모달 결과 표시.

## [OPEN] frontend shell — `api/types.ts` 별칭 추가
- 요청자: frontend/notebook · 날짜: 2026-11-03
- 내용: 현재 Notebook은 `features/notebook/types.ts`에서 `Schemas[...]`로 직접 별칭을 만든다. 공용으로 쓰일 만한
  `DatasetValidation`, `CsvIssue`, `ConditionIssue`, `HistoryEntry`, `ExperimentAddendumOut`, `AttachmentFileOut`,
  `ProtocolTemplateOut`, `ImportPreview`를 `api/types.ts`에 추가해 주면 Notebook 쪽 별칭을 제거한다.

## [OPEN] docs — ARCHITECTURE.md ELN 계약 표 갱신
- 요청자: eln · 날짜: 2026-11-03
- 추가된 ELN 엔드포인트: `GET /dataset-kinds`, `GET /import-formats`, `GET /projects/{id}/experiments`
  (`limit/offset/performed_from/performed_to/author/dataset_kind`, `X-Total-Count`),
  `GET /projects/{id}/experiment-draft?source_experiment_id|protocol_template_id`,
  `GET/POST /projects/{id}/condition-template`, `POST /projects/{id}/condition-check`,
  `GET/POST /projects/{id}/protocol-templates`, `PATCH /experiments/{id}/metadata`(409 on immutable),
  `POST /experiments/{id}/addenda`, `GET /experiments/{id}/history`, `GET /experiments/{id}/audit`,
  `POST /experiments/{id}/datasets/upload|import` (multipart), `POST /datasets/validate`,
  `POST /datasets/validate-upload`, `POST /import/preview`, `POST /experiments/{id}/attachment-files`,
  `GET /attachment-files/{file_id}/content`(스키마 제외, 위 항목 참조).
- 소유 테이블 추가: `eln_experiment_revisions`, `eln_experiment_addenda`, `eln_attachment_files`,
  `eln_condition_templates`, `eln_protocol_templates`. 불변성 표: Experiment에 `cloned_from_experiment_id`,
  `protocol_template_id` 불변 필드 추가, 위 신규 엔티티는 전체 불변.
- 설정: `BIOPILOT_ELN_STORAGE_DIR`(첨부 저장소, 기본 `./eln_storage`, 자동 `.gitignore`).

## [OPEN] core — (Alembic 항목 보충) ELN 스키마 변경으로 기존 로컬 DB 재생성 필요
- 요청자: eln · 날짜: 2026-11-03
- 내용: `eln_experiments`, `eln_datasets`에 컬럼이 추가되었다. `create_all()`은 기존 테이블에 컬럼을 추가하지
  않으므로, Alembic 도입 전까지 기존 `backend/biopilot.db`는 삭제 후 재시드해야 한다. 마이그레이션 도입 시
  `eln_0001_authoring` revision으로 옮길 예정.

## [OPEN] memory — 보충 기록(addenda)을 검색·정리본 입력에 포함 검토
- 요청자: eln · 날짜: 2026-11-03
- 내용: `ExperimentOut.addenda[]`(불변, 원본 메모와 분리)가 추가되었다. Memory `search`와 정리본 프롬프트가
  보충 기록도 참조하면 "나중에 알게 된 사실"이 기억에 반영된다(원본 `raw_note`는 그대로).

## [DONE] core/composition — `app/wiring.py` 검토·소유권 확정
- 요청자: memory (feature/memory) · 날짜: 2026-11-03
- 필요 이유: Memory는 eln에만 의존해야 하지만 diff(결과·QC 차이)·recall·지식 그래프는 Analysis 결과와
  Partner 레코드를 보여줘야 한다. Memory는 `memory.schemas.FactProvider` 포트만 정의하고, 구현체
  (`AnalysisFactProvider`, `PartnerFactProvider`)는 기능 모듈 밖 composition root `app/wiring.py`에 두었다.
  `app/main.py`에는 import 한 줄과 등록 한 줄(`install_memory_fact_providers()`)만 추가했다.
- 제안하는 계약: `memory.service.register_fact_provider(provider)`. 제공자는 각 모듈 service만 읽고 새 숫자를 만들지 않는다.
- 완료 기준: core 담당이 위치(`app/wiring.py`)와 `create_app` 등록 방식을 승인하거나 대안을 제시. Analysis/Partner
  담당은 자기 서비스 시그니처를 바꿀 때 `app/wiring.py`도 함께 고친다.
- **결정(integration, 2026-11-03): 승인.** `app/wiring.py`는 core 소유 composition root다(CLAUDE.md §2·§3 공유 파일 목록에
  추가). `main.py`의 import 1줄 + `install_memory_fact_providers()` 1줄을 승인한다. `tests/test_architecture.py`에
  `test_wiring_imports_only_service_and_schemas`(wiring은 `app.<module>.service/schemas`·`app.core`만 import)와
  `test_feature_modules_do_not_import_wiring`을 추가했다.

## [OPEN] core — 마이그레이션 대상 추가 (Alembic 요청에 병합)
- 요청자: memory · 날짜: 2026-11-03
- 필요 이유: `memory_digests`에 `fallback_reason`, `input_fingerprint` 컬럼 추가. 새 테이블 `memory_knowledge_notes`,
  `memory_index_state`. FTS5 가상 테이블 `memory_search_fts`(검색 시 `CREATE ... IF NOT EXISTS`). Alembic 도입 전까지
  기존 `backend/biopilot.db`는 삭제 후 재시드해야 한다.
- 완료 기준: memory revision 파일로 위 스키마가 생성됨.

## [OPEN] frontend/notebook (ELN) — ~~ExperimentDiffView~~ → **CompareModal**에 결과·QC 차이와 단어 diff 표시
- 요청자: memory · 날짜: 2026-11-03
- **재지정(integration, 2026-11-03):** 대상 파일 `features/notebook/ExperimentDiffView.tsx`는 ELN이 삭제하고
  `CompareModal.tsx`로 대체했다. 이 요청은 CompareModal 대상으로 옮긴다. CompareModal은 지금 결과 차이를
  `analysis.compare`로 그리므로, memory `result_changes`(출처 포함)·`qc_changes`·`qc_info_changes`(info 등급 분리)·
  `note_diff[].segments`를 추가 표시할지, 결과 차이 경로를 하나로 통일할지 Notebook·Memory 담당이 협의한다.
- 필요 이유: `ExperimentDiff`에 필드를 추가했다(제거 없음): `results_available`, `result_changes[]`(value_a/b, delta,
  p_value, sources), `qc_changes[]`(appeared/resolved/persisting, sources), `condition_changes[].sources`,
  `note_diff[].segments[]`.
- 완료 기준: #018 vs #024에서 회수율 Δ와 출처(분석 결과 id), 새로 생긴 QC 플래그, "10"→"5" 단어 강조가 화면에 보임.

## [OPEN] frontend/shell — 전역 검색 바를 헤더로 이동
- 요청자: memory · 날짜: 2026-11-03
- 필요 이유: `features/overview/GlobalSearchBar.tsx`(+ `highlight.tsx`)는 지금 Overview 상단에만 있다. 탭 간 import
  금지 규칙 때문에 헤더(AppShell)에 두려면 `components/`로 옮겨야 한다.
- 제안: 두 파일을 `components/`로 옮겨 AppShell 헤더에 장착하고 Overview에서는 제거.
- 완료 기준: 모든 탭에서 검색 가능, 결과 클릭 시 `/notebook?exp=`.

## [OPEN] frontend/api — `types.ts` 별칭 추가
- 요청자: memory · 날짜: 2026-11-03
- 제안: `KnowledgeGraph`, `KGNode`, `KGEdge`, `SearchHit`, `RecallBundle`, `MemoryAnswer`, `SimilarExperiment`,
  `ConditionMatrix`, `ConditionHistoryEntry`, `KnowledgeNoteOut`. (지금 overview는 `Schemas[...]`를 직접 사용)

## [OPEN] frontend — 새 Memory 계약 공지 (MEM-5 등)
- 요청자: memory · 날짜: 2026-11-03
- 내용: `GET /api/memory/compare-conditions?ids=1,2,7&varying_only=true`(키×실험 행렬),
  `/conditions/{key}/history`, `/experiments/{id}/similar`, `/projects/{id}/recall`, `POST /projects/{id}/ask`,
  `/projects/{id}/knowledge-notes`. `/graph` 기본 응답은 그대로(derived_from 6엣지)이고 `relations=`로 MEM-1 엣지를 고른다.
  `queries.ts` memory 섹션에는 `useKnowledgeGraph`/`useMemorySearch`/`useRecall`만 추가했다.

## [OPEN] partner — Memory recall/근거 조각 활용 검토
- 요청자: memory · 날짜: 2026-11-03
- 내용: `memory.service.recall()` / `ask()`가 출처가 붙은 근거 조각(`EvidenceFragment`)을 반환한다. Partner `/ask`
  컨텍스트 보강에 쓸 수 있다. `ExperimentDiff.result_changes`는 Analysis `compare` 값을 그대로 담는다.

## [OPEN] seed — 지식 노트 예시 1건
- 요청자: memory · 날짜: 2026-11-03
- 내용: `memory.service.create_knowledge_note(..., actor="seed")`로 #024에 연결된 예시 노트 1건을 넣으면 Overview
  그래프에 note 노드가 기본으로 보인다. 선택 사항.

## [DONE] tests — `tests/test_contract.py` 파라미터 표 추가 (공지)
- 요청자: memory · 날짜: 2026-11-03
- 내용: 새 GET 엔드포인트용 `PATH_PARAMS["key"]`와 `QUERY_PARAMS`(recall, compare-conditions) 항목만 추가했다.
  검사 로직은 바꾸지 않았다.
