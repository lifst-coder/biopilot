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
