# ARCHITECTURE

BioPilot = **ELN + Research Memory + Scientific Analysis + AI Partner**.
작업 규칙은 [CLAUDE.md](CLAUDE.md), 남은 작업은 [TASKS.md](TASKS.md).

## 1. 4레이어 데이터 흐름

```
 연구자 입력                                                         연구자 결정
     │                                                                    ▲
     ▼                                                                    │
┌──────────┐  DTO   ┌────────────┐        ┌──────────────┐  Evidence ┌────┴───────┐
│ L1  ELN  │──────▶│ L2 Memory  │──────▶ │              │─────────▶│ L4 Partner │
│ 원본 기록 │       │ 계보·diff·  │  diff  │              │          │ 비판·가설· │
│ (불변)   │──────────────────────────▶ │ L3 Analysis  │ metrics  │ 제안·결정  │
└──────────┘  CSV   │ 검색·정리본 │        │ 결정론적 계산 │ compare  └────────────┘
     │              └────────────┘        └──────────────┘               │
     │                    │                     │                       │
     ▼                    ▼                     ▼                       ▼
 eln_experiments    memory_digests        analysis_results     partner_critiques / hypotheses
 eln_datasets       (AI 정리본, 불변)      (불변, 입력 지문)     partner_proposals / decisions
     └──────────────────────────── core_audit_events (append-only) ─────────────────┘
```

- 원본(L1)은 한 번 기록되면 바뀌지 않는다. 이후 레이어의 산출물은 **모두 별도 레코드**다.
- 숫자는 L3에서만 만들어진다. L4는 L3 결과를 `Evidence{key, ref_type, ref_id, value, unit}`로 옮겨
  인용만 한다. 프론트는 숫자를 포맷만 한다.
- 모든 쓰기는 같은 트랜잭션에서 `AuditEvent`를 남긴다.
- Memory(L2)는 Analysis·Partner를 import하지 않는다. 결과·QC·결정 같은 상위 레이어 사실은 composition root
  `app/wiring.py`가 Memory의 읽기 전용 포트에 연결한다(§3 memory 아래 문단).

## 2. 모듈 책임

| 모듈 | 소유 테이블 | 책임 | 의존 |
|---|---|---|---|
| `core` | `core_audit_events` | 설정, DB·Alembic(`core/migrations`, 시작 시 `upgrade head`), 감사 로그, 불변성 가드, LLM 게이트웨이, 숫자 근거 검증기(`grounding.py` — Memory·Partner 공용), 요청 상한(`limits.py`), 도메인 에러 | — |
| `eln` | `eln_projects`, `eln_experiments`, `eln_experiment_revisions`, `eln_experiment_addenda`, `eln_attachment_files`, `eln_datasets`, `eln_condition_templates`, `eln_protocol_templates`, `eln_protocol_runs`, `eln_protocol_run_entries` | 원본 기록 생성·조회, CSV 수집 검증(`DATASET_COLUMNS`)·벤더 CSV 변환, 첨부(sha256 블롭), 보충 기록, 메타데이터 개정 이력, 조건 템플릿·키 라벨, 프로토콜(붙여넣기 추출·단계·실행·버전 계보) | core |
| `memory` | `memory_digests`, `memory_knowledge_notes`, `memory_index_state` (+ FTS5 가상 테이블 `memory_search_fts`, 파생) | 실험 계보·지식 그래프(NetworkX), 타임라인, 두 실험 diff(조건·메모·데이터셋·결과·QC·관계), 프로젝트를 가로지르는 검색·회상, 실패 아카이브, 지식 노트, AI 정리본 | core, eln (+ `FactProvider` 포트) |
| `analysis` | `analysis_results`, `analysis_criteria_versions` | 검량선(WLS 1, 1/x, 1/x²), 역산 정확도, 회수율·불확도·Grubbs, IS 응답, 매트릭스 효과(기울기 비), LOD/LOQ, 이온비, Welch t-test + Holm 비교, QC 플래그(SANTE/11312/2021, 프로젝트별 기준 버전), 리포트, 기록 교차(조건값·작업자·기간·프로토콜 버전) | core, eln |
| `partner` | `partner_critiques`, `partner_hypotheses`, `partner_hypothesis_transitions`, `partner_proposals`, `partner_decisions`, `partner_exchanges` | 근거 컨텍스트 구성, 규칙/Claude 비판, 가설 상태 전이, 우선순위가 매겨진 제안 설계, 연구자 결정(accept/modify/reject + rationale)과 그 피드백, 실패 원인 가설·과거 사례, Q&A | core, eln, memory, analysis |
| `wiring.py` | — | composition root(core 소유). Analysis·Partner 서비스를 Memory의 `FactProvider` 포트에 연결한다. `app.<module>.service/schemas`만 import하고, 어떤 기능 모듈도 wiring을 import하지 않는다 | eln, memory, analysis, partner |

서비스 함수는 항상 `Session`을 첫 인자로 받고 Pydantic DTO를 반환한다. 라우터는 얇다(서비스 호출만).

### 불변성 정책

| 엔티티 | 불변 필드 | 변경 가능 |
|---|---|---|
| Experiment | project_id, code, raw_note, condition_block, attachments, performed_on, parent_experiment_id, cloned_from_experiment_id, protocol_template_id, created_at | title, author (오타 수정용; 개정 이력 `eln_experiment_revisions` + 감사, 동시 수정은 409 `revision_conflict`) |
| Dataset, ExperimentRevision, Addendum, AttachmentFile, ConditionTemplate, ProtocolTemplate, ProtocolRunEntry, AnalysisResult, CriteriaVersion, ExperimentDigest, KnowledgeNote, Critique, Decision, HypothesisTransition, Exchange, AuditEvent | 전체 | 없음 |
| Hypothesis, Proposal | status 외 전체 | status (Decision/감사 이벤트로만) |

삭제는 불변 엔티티 모두 금지.

### AI 모드

```
get_gateway() ── ANTHROPIC_API_KEY 없음 ──▶ RulesOnlyGateway  (generate() → None)
              └─ 있음 ───────────────────▶ ClaudeGateway     (JSON schema 구조화 출력)

Partner.run_critique:
  ctx = build_context()                      # Evidence E1..En (출처 레코드 id 포함)
  draft = Claude(ctx)  if mode == claude     # CritiqueDraft
  if draft is None or 근거 키 불일치 or ungrounded_numbers(draft):
      draft = RulesCritiqueEngine(ctx)       # 같은 CritiqueDraft 스키마
      fallback_reason 기록
  저장: Critique(+evidence 스냅샷) → Hypothesis[] → Proposal[]  (+ AuditEvent)
```

모델 기본값 `claude-opus-5-5`(`BIOPILOT_CLAUDE_MODEL`), effort `medium`(`BIOPILOT_CLAUDE_EFFORT`),
서버측 refusal fallback(`fallbacks="default"`) 사용. 실패·거절·스키마 불일치는 모두 규칙 모드로 귀결.

## 3. API 계약 요약

전체 계약: `backend/openapi.json` (생성 파일, CI가 최신 여부 검사). TS 타입: `frontend/src/api/schema.d.ts`.
오류 응답: `{code, message}` — 400 `validation_failed`, 404 `not_found`, 409 `immutable_record`,
409 `revision_conflict`(ELN 동시 수정이 재시도 후에도 충돌), 409 `conflict`(그 밖의 제약 위반 안전망), 413 `payload_too_large`, 500 `internal_error`(내부 정보 없음).
요청 스키마 위반은 FastAPI 기본 422(`detail[].input`은 200자로 잘라 돌려준다).
요청 본문 상한·JSON 깊이·CORS는 `BIOPILOT_MAX_REQUEST_BYTES`, `BIOPILOT_MAX_JSON_BYTES`, `BIOPILOT_MAX_JSON_DEPTH`,
`BIOPILOT_CORS_ORIGINS`로 조정한다([SECURITY_REVIEW.md](SECURITY_REVIEW.md)).

### system
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/health` | `HealthOut` |
| GET | `/api/system/info` | `SystemInfo` (ai_mode) |
| GET | `/api/audit?project_id&entity_type&entity_id&limit` | `AuditEventOut[]` |

### eln
| Method | Path | 응답 |
|---|---|---|
| GET/POST | `/api/eln/projects` | `ProjectOut[]` / `ProjectOut` |
| GET | `/api/eln/projects/{project_id}` | `ProjectOut` |
| GET/POST | `/api/eln/projects/{project_id}/experiments` | `ExperimentSummary[]` / `ExperimentOut` |
| GET | `/api/eln/experiments/{experiment_id}` | `ExperimentOut` (raw_note, condition_block, attachments) |
| GET/POST | `/api/eln/experiments/{experiment_id}/datasets` | `DatasetOut[]` / `DatasetOut` (CSV 텍스트 업로드, 컬럼 검증) |
| GET | `/api/eln/datasets/{dataset_id}?limit` | `DatasetPreview` |
| GET | `/api/eln/datasets/{dataset_id}/content` | `text/csv` 원문 |
| GET | `/api/eln/condition-fields` | `ConditionField[]` (조건 키 라벨) |
| GET | `/api/eln/dataset-kinds` · `/api/eln/import-formats` | `DatasetKindSpec[]` · `ImportFormat[]` (CSV 계약, 벤더 내보내기 변환기 2종) |
| POST | `/api/eln/datasets/validate` · `/api/eln/datasets/validate-upload` · `/api/eln/import/preview` | `DatasetValidation` · `ImportPreview` (저장하지 않는 사전 검사) |
| POST | `/api/eln/experiments/{experiment_id}/datasets/upload` · `…/datasets/import` | `DatasetOut` (multipart CSV · 벤더 형식 변환) |
| POST | `/api/eln/experiments/{experiment_id}/attachment-files` | `AttachmentFileOut` (원본 파일 블롭, `download_url`) |
| POST | `/api/eln/experiments/{experiment_id}/addenda` | `ExperimentAddendumOut` (보충 기록 — 원본을 고치지 않는 정정) |
| PATCH | `/api/eln/experiments/{experiment_id}/metadata` | `ExperimentOut` (title·author만, 개정 번호 + 감사, 충돌 시 409) |
| GET | `/api/eln/experiments/{experiment_id}/history` · `…/audit?limit` | `ExperimentHistory` · `AuditEventOut[]` |
| GET | `/api/eln/projects/{project_id}/experiment-draft?source_experiment_id&protocol_template_id` | `ExperimentDraft` (복제·프로토콜 시작용 초안, 저장하지 않음) |
| GET/POST | `/api/eln/projects/{project_id}/condition-template` · POST `…/condition-check` | `ConditionTemplateOut` · `ConditionCheck` (조건 블록 규칙 검사) |
| POST | `/api/eln/protocol-extractions` | `ProtocolExtraction` (붙여넣은 텍스트·표 → 조건 후보 + 근거 줄, **저장하지 않음**; 규칙 기본, Claude는 근거 검증 후 사용) |
| GET/POST | `/api/eln/projects/{project_id}/protocol-templates?all_versions` | `ProtocolTemplateList` / `ProtocolTemplateOut` (`version_label`, `steps`, 원문 `source_text`, 검토 결과 `extraction`) |
| GET | `/api/eln/projects/{project_id}/protocol-lineage` | `ProtocolLineage` (버전별 이전 대비 조건 변경, 그 버전으로 기록된 실험과 이탈 조건, 사용 기간) |
| GET | `/api/eln/protocol-diff?a&b` | `ProtocolDiff` (두 버전의 조건값 단위 차이) |
| POST | `/api/eln/protocol-templates/{template_id}/runs` | `ProtocolRunOut` (실행 시작) |
| GET | `/api/eln/projects/{project_id}/protocol-runs?status` · `/api/eln/protocol-runs/{run_id}` | `ProtocolRunList` · `ProtocolRunOut` (append-only 기록을 접은 현재 상태, `deviations`) |
| POST | `/api/eln/protocol-runs/{run_id}/entries` | `ProtocolRunOut` (`check`/`uncheck`/`actual`/`note`, 각 1건 불변 + 감사) |
| POST | `/api/eln/protocol-runs/{run_id}/complete` | `ProtocolRunCompletion` (실제 값 조건 블록 + "프로토콜과 다른 점" 메모로 실험 생성, `dry_run` 미리보기) |

프로토콜 추출 원칙(`eln/protocols.py`): 원문에 적힌 값만 후보가 된다 — 범위·서로 다른 값·단위 불일치는 비워 두고
(`ambiguous`/`unrecognized`) 이유를 단다. Claude 출력은 값마다 원문 줄 인용이 필요하고, 인용이 원문에 없거나
값의 숫자가 인용에 없으면 규칙 결과로 대체(`fallback_reason`). 후보는 연구자가 확인·수정한 뒤에만 저장된다.

CSV 계약(`eln/schemas.py: DATASET_COLUMNS`):
- `calibration`: injection_id, level_ng_ml, analyte, analyte_area, is_area
- `recovery`: injection_id, sample_id, analyte, spike_ng_g, analyte_area, is_area
- `matrix_effect`: injection_id, curve(solvent|matrix), level_ng_ml, analyte, analyte_area

### memory
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/memory/projects/{project_id}/timeline` | `TimelineEntry[]` (부모 대비 변경 키) |
| GET | `/api/memory/projects/{project_id}/graph?relations` | `ResearchGraph` (기본 `derived_from`만; `shares_conditions`·`tests_proposal` 선택) |
| GET | `/api/memory/projects/{project_id}/knowledge-graph?types&focus&radius` | `KnowledgeGraph` (Experiment↔Condition↔Analyte/Sample↔Result↔Critique↔Hypothesis↔Proposal↔Decision, `refresh`=full/incremental/cached) |
| GET | `/api/memory/projects/{project_id}/search?q&limit` | `SearchHit[]` (FTS5 trigram, `score`, `highlights`, `source`) |
| GET | `/api/memory/projects/{project_id}/recall?q&limit` | `RecallBundle` (terms[facet], experiments, protocols, results) |
| GET | `/api/memory/search?q&limit&project_id*` | `SearchHit[]` 교차 프로젝트(기본 전체, `project_id` 반복으로 제한) — 각 hit에 `project_id` |
| GET | `/api/memory/recall?q&limit&project_id*` | `RecallBundle` 교차 프로젝트(점수 순 병합, `project_ids`) |
| GET | `/api/memory/failures?project_id*` | `FailureArchive` (실패 = 저장된 QC의 critical 플래그 · 유형 · 반복 패턴[retry/same_condition] · 벗어난 실험) |
| POST | `/api/memory/projects/{project_id}/ask` | `MemoryAnswer` (규칙: 근거 조각 / Claude: 근거 검증된 요약, `fallback_reason`) |
| GET | `/api/memory/projects/{project_id}/conditions/{key}/history` | `ConditionHistoryEntry[]` |
| GET | `/api/memory/compare-conditions?ids=1,2,7&varying_only` | `ConditionMatrix` |
| GET/POST | `/api/memory/projects/{project_id}/knowledge-notes` | `KnowledgeNoteList` / `KnowledgeNoteOut` (불변 + 감사) |
| GET | `/api/memory/experiments/{experiment_id}/lineage` | `ExperimentSummary[]` (root → self) |
| GET | `/api/memory/experiments/{experiment_id}/similar?limit` | `SimilarExperiment[]` (조건 벡터 유사도) |
| GET | `/api/memory/diff?a&b` | `ExperimentDiff` (relation, condition_changes[sources], result_changes, qc_changes, note_diff[segments], datasets) |
| GET/POST | `/api/memory/experiments/{experiment_id}/digests` | `DigestOut[]` / `DigestOut` (`stale`, `fallback_reason`) |

Memory는 eln에만 의존한다. Analysis 결과·QC 플래그·Partner 레코드는 `memory.schemas.FactProvider`
포트로 들어오고, 구현체는 composition root `app/wiring.py`가 `create_app()`에서 등록한다
(값·Δ·p는 Analysis가 계산한 그대로 복사). 지식 그래프와 검색 인덱스는 `core_audit_events`를
변경 피드로 삼아 워터마크 이후 이벤트만 증분 반영한다. 검색 인덱스는 **쓰기 경로**(감사 이벤트를 남긴 트랜잭션의
커밋 직전, 같은 트랜잭션)·앱 시작 시·`POST /api/memory/search-index/sync`에서만 갱신되고, `GET` 검색·회상은 DDL·쓰기를 하지 않는다
(아직 색인되지 않은 이벤트는 읽기 시 스캔으로 보충).

### analysis
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/analysis/criteria?project_id` | `AcceptanceCriteria` (프로젝트 활성 기준, 없으면 기본) |
| GET/POST | `/api/analysis/projects/{project_id}/criteria` | `ProjectCriteria` / `CriteriaVersionOut` (기준 버전 — 이전 결과는 그대로, 새 결과에 버전 기록) |
| GET | `/api/analysis/methods` | `MethodDoc[]` (방법·가정·버전) |
| GET | `/api/analysis/experiments/{experiment_id}/report?format=markdown\|csv` | `text/markdown` · `text/csv` (저장된 결과만 렌더링) |
| POST | `/api/analysis/experiments/{experiment_id}/run` | `RunResponse` (동일 입력이면 재사용: idempotent) |
| GET | `/api/analysis/experiments/{experiment_id}/metrics` | `ExperimentMetrics` (+ `source_result_ids`) |
| GET | `/api/analysis/results?experiment_id&kind` | `AnalysisResultOut[]` |
| GET | `/api/analysis/results/{result_id}` | `AnalysisResultOut` (`output`은 `kind` 판별 유니온) |
| GET | `/api/analysis/compare?a&b` | `MetricsComparison` (Δ회수율, 분석물별 Δ, Welch t-test) |
| GET | `/api/analysis/projects/{project_id}/trend` | `TrendPoint[]` |
| GET | `/api/analysis/records/conditions?key&contains&project_id*` | `ConditionRecords` (조건값별 묶음: 저장 회수율 최소/중앙/최대, QC 불합격 비율, 근거 실험) |
| GET | `/api/analysis/records/operators?window_days&project_id*` | `OperatorRecords` (작업자별 묶음 + 조건 블록 동일·기간 내 작업자 쌍의 `compare` 결과) |
| GET | `/api/analysis/records/periods?gap_days&project_id*` | `PeriodRecords` (월별 묶음 + 실험 없는 공백) |
| GET | `/api/analysis/records/protocols?project_id*` | `ProtocolRecords` (프로토콜 버전별 묶음: 저장된 QC 통과 수 `pass_count`/`pass_ratio`, 통과율 높은 순) |

결과 종류(`kind`): `calibration`(slope, intercept, weighted R², back_calc, points, fit_line,
weighting_comparison) · `recovery`(groups, rows) · `is_response`(injections, flagged_count) · `matrix_effect` ·
`limits`(LOD/LOQ) · `ion_ratio`.

### partner
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/partner/mode` | `PartnerMode` |
| GET/POST | `/api/partner/experiments/{experiment_id}/critiques` | `CritiqueOut[]` / `CritiqueOut` |
| GET | `/api/partner/critiques/{critique_id}` | `CritiqueOut` (summary, findings[evidence_keys], evidence[], hypothesis_ids, proposal_ids, engine, fallback_reason) |
| GET/POST | `/api/partner/hypotheses?project_id&experiment_id` | `HypothesisOut[]` / `HypothesisOut` |
| GET | `/api/partner/proposals?project_id&experiment_id&status` | `ProposalOut[]` |
| GET | `/api/partner/proposals/{proposal_id}` | `ProposalOut` (+ decision) |
| POST | `/api/partner/proposals/{proposal_id}/decision` | `ProposalOut` (`DecisionCreate{action, rationale, modifications}`; 제안당 1회) |
| POST | `/api/partner/ask` | `AskResponse` (answer, engine, evidence[], topics, intent, statements[사실/판단/추정], sources, critique_id, exchange_id) |
| POST | `/api/partner/ask/stream` | SSE `start → delta* → replace? → final(AskResponse)` |
| GET | `/api/partner/projects/{project_id}/exchanges?experiment_id` | `ExchangeHistory` (저장된 Q&A) |
| GET/POST | `/api/partner/projects/{project_id}/critiques?scope` | `CritiqueOut[]` / `CritiqueOut` (프로젝트 수준 비판) |
| GET | `/api/partner/projects/{project_id}/decisions?experiment_id` | `DecisionHistory` (결정 + 반영된 비판 id) |
| POST | `/api/partner/hypotheses/{hypothesis_id}/status` | `HypothesisOut` (proposed→open→supported/refuted) |
| GET | `/api/partner/proposals/{proposal_id}/experiment-draft` | `ExperimentDraftOut` (저장하지 않는 ExperimentCreate 초안) |
| GET | `/api/partner/failure-archive?project_id*` | `FailureArchiveOut` (Memory 실패 아카이브 + 규칙 기반 원인 가설[근거 실험] + 그 뒤 결정·후속 실험) |
| GET | `/api/partner/experiments/{experiment_id}/precedents` | `PrecedentsOut` (이 실험보다 먼저 같은 증상으로 실패한 사례[모든 프로젝트]와 그때 결론, 다른 프로젝트의 같은 조건값 사용 이력) |

Partner 출력 구조: `CritiqueOut.assessments[]`(Research Critic: 지지/반대 근거, 누락 대조군, 대안 설명,
확정 불가 이유, verdict) · `ProposalOut.design`(변수·대조군·반복 수·측정·예상 판별력·근거 실험) ·
`priority`/`priority_factors` · `decision_feedback[]`(이전 결정이 어떻게 반영됐는지).
결정 사유는 다음 비판의 근거(`partner.Decision` evidence)가 되고, 결정된 제안과 같은 변경(signature)은 다시 제안하지 않는다.

축적 기록 질의의 역할 분담: **Memory**가 실패 목록·유형·반복 패턴(기록 구조, 숫자 계산 없음)을, **Analysis**가
조건값·작업자·기간 묶음의 통계(개수·최소/중앙/최대·불합격 비율, 작업자 쌍은 기존 Welch `compare`)를, **Partner**가
원인 가설(규칙)·결정 연결·과거 사례(precedents)를 맡는다. 과거 사례는 저장된 비판을 바꾸지 않고 조회 시점에 기록에서 찾는다.

## 4. 프론트엔드

```
frontend/src/
  api/            client.ts (openapi-fetch), schema.d.ts (생성), types.ts (별칭), queries.ts (React Query 훅),
                  demo.ts (VITE_DEMO 빌드: 모든 /api 요청을 내보낸 시나리오 JSON에서 응답 — 아래)
  layout/         AppShell (헤더 + 6개 탭 + 우측 Research Partner 패널), GuideBar (첫 방문 안내 ①→④), tabs.ts,
                  ContextBar (화면 상단 맥락 줄 + "← 이전 화면"), Shortcuts (키보드, "?" 목록)
  components/     Card, Badge(Severity/Engine/Original), StatTile, DataTable, QueryState,
                  ExperimentPicker, ConditionTable, EvidenceChip, ExperimentChip,
                  CodeText (문장 속 실험 코드 → 그 실험 링크, 원문은 그대로)
  lib/            format.ts (포맷 전용), selection.ts (?exp= URL 상태), chartColors.ts,
                  experimentIndex.ts (모든 프로젝트의 코드 → 실험), trail.ts (기록 위치별 화면 이름 = 돌아가기)
  styles/         tokens.css (디자인 토큰 = CSS 변수) → tailwind.config.js 가 참조
  features/
    overview/     프로젝트 KPI, 회수율 추이, 타임라인, 감사 로그
    notebook/     원본 메모·조건 블록·CSV 미리보기·AI 정리본·Memory diff
    protocols/    Protocols 탭: 버전 계보(QC 통과) · 붙여넣기→조건 추출→확인→저장 · 단계별 실행(390px 우선)
    analysis/     검량선/회수율/IS/ME 패널, QC 플래그, 수치 비교
    research-ai/  비판(근거 칩), 가설, 제안 + 결정 폼
    partner-panel/ 우측 패널: 모드, 최근 비판, 질문
    records/      Records 탭: 기록 가로지르기(조건값·작업자·기간) · 실패 아카이브 (모든 프로젝트)
```

- 탭은 6개: Overview · Notebook · Protocols · Analysis · Research AI · Records. 탭마다 그 화면이 답하는 질문 하나를
  제목 아래에 둔다(`layout/tabs.ts`). 1024px 미만에서는 패널이 본문 아래로 내려가고 탭 줄은 가로로 스크롤된다.
- 활성 프로젝트는 URL `?project=<id>`(헤더 전환). 없으면 `?exp=`의 프로젝트, 그것도 없으면 첫 프로젝트.
- 선택된 실험은 URL `?exp=<id>`로 탭/패널 간 공유된다.
- 화면 사이 이동: 실험 코드는 어디에 보이든(칩·문장·원본 메모·결정 사유) `CodeText`/`ExperimentLink`로 그 실험을
  **그 실험의 프로젝트**(`?project=&exp=`)에서 연다. 모든 화면 위 `ContextBar`가 "프로젝트 · 코드 · 날짜 · 프로토콜 버전 · QC"를
  각각 해당 화면 링크로 보여 주고, 브라우저 기록 한 칸 뒤가 다른 화면이면 "← <그 화면>"(= 뒤로)을 단다.
  키보드: `1`–`6` 탭, `[` `]` 이전/다음 실험, `/` 검색, `?` 목록. 막힘 지점 목록과 전후 비교는
  [docs/screenshots/navigation](docs/screenshots/navigation/README.md).
- 각 탭은 lazy chunk. 탭 간 import 금지(공통은 `components/`·`lib/`로).
- 색은 `tokens.css` 변수만 사용(Tailwind `bg-surface`, `text-ink-muted`, `bg-crit-soft` …).

### 백엔드 없는 데모 (GitHub Pages)

`python -m app.scripts.export_scenario --profile reference|lab`이 시드한 임시 DB에 **실제 API**를 호출해 GET 응답을
요청 키(경로 + 정렬된 쿼리)별로 `frontend/public/scenario[-lab].json`에 저장한다. 함께 저장하는 것: 4xx 응답(그대로 재생),
분석 리포트 다운로드(본문·헤더), Research Partner 추천 질문 3개의 답(DB 사본에서 계산), 프로토콜 예시 원문 1건의 추출 결과.
`VITE_DEMO=true` 빌드의 `api/demo.ts`는 이 파일에서 찾아 응답할 뿐 아무것도 계산하지 않는다. 그 밖의 쓰기는
`403 demo_read_only`, 저장되지 않은 조합은 `404 not_in_scenario`이고, `ErrorState`가 둘을 오류가 아닌
"데모 · 읽기 전용" 안내로 보여준다. 배포는 `.github/workflows/pages.yml`.

## 5. 시드 시나리오

| 프로파일(`BIOPILOT_SEED_PROFILE`) | 내용 | 사용처 |
|---|---|---|
| `reference` (기본) | 잔류농약 #018–#024 7개, #024 규칙 비판 1건 | 테스트 픽스처(`seeded`/`client`), 기본 auto-seed, 데모 reference |
| `lab` | 프로젝트 2개(잔류농약 30 + 발효식품 유기산 12) · 실험 42개 · 비판 9건 · 결정 14건 · 프로토콜 SOP v1→v1.1→v1.2→v2 | 데모 lab, E2E, `tests/test_seed_lab.py` |

원본은 `backend/app/seed/data/residue.json`·`organic_acids.json`(메모·조건 블록·CSV 배정), `history.json`(비판·결정 이력),
`protocols.json`(프로토콜 템플릿). CSV는 `app/seed/generate.py`(고정 시드)로 재현 가능하며 `tests/test_seed.py`가
일치 여부를 검사한다. 6개월의 이야기는 [backend/app/seed/SCENARIO.md](backend/app/seed/SCENARIO.md).

아래는 `reference` 프로파일(프로젝트 "잔류농약 QuEChERS·LC-MS/MS 회수율 최적화" — 사과 매트릭스, 5종 농약, IS = TPP)이다.
수치는 **분석 코드가 CSV에서 계산한 값**이다(설계 목표).

| 실험 | 부모 | 변경 | 데이터 | 계산 결과(목표) |
|---|---|---|---|---|
| #018 기준 | — | — | cal + rec | 평균 회수율 ≈ 89% |
| #019 | #018 | pH 5→6.5, 완충염 제거 | cal + rec | ≈ 86% (벤즈이미다졸계 저하) |
| #020 | #018 | 컬럼 Phenyl-Hexyl, 30 °C | cal + rec | ≈ 89% |
| #021 | #018 | — (매트릭스 효과 평가) | matrix_effect | imidacloprid ME ≈ −29% (유의) |
| #022 | #018 | — (반복성 n=6) | cal + rec | ≈ 89%, 낮은 RSD |
| #023 | #018 | — (검량선 1–200 ng/mL ×3) | cal | 1/x가 무가중 대비 Σ\|%RE\| 대폭 감소 |
| #024 | #018 | 추출 10→5분, C18→GCB | cal + rec | ≈ 62%, IS 억제 3/10 주입, carbendazim·thiabendazole 기준 미달 |

시드 로더는 서비스 인터페이스를 통해 원본을 넣고(actor=`seed`), 전 실험 분석 실행, 규칙 모드 정리본,
#024 규칙 모드 비판까지 생성한다.
