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

## 2. 모듈 책임

| 모듈 | 소유 테이블 | 책임 | 의존 |
|---|---|---|---|
| `core` | `core_audit_events` | 설정, DB, 감사 로그, 불변성 가드, LLM 게이트웨이, 도메인 에러 | — |
| `eln` | `eln_projects`, `eln_experiments`, `eln_datasets` | 원본 기록 생성·조회, CSV 수집 검증(`DATASET_COLUMNS`), 조건 키 라벨 | core |
| `memory` | `memory_digests` | 실험 계보 그래프(NetworkX, `parent_experiment_id`), 타임라인, 두 실험 diff(조건·메모·데이터셋·관계), 검색, AI 정리본 | core, eln |
| `analysis` | `analysis_results` | 검량선(WLS 1, 1/x, 1/x²), 역산 정확도, 회수율, IS 응답, 매트릭스 효과(기울기 비), Welch t-test 비교, QC 플래그(SANTE/11312/2021) | core, eln |
| `partner` | `partner_critiques`, `partner_hypotheses`, `partner_proposals`, `partner_decisions` | 근거 컨텍스트 구성, 규칙/Claude 비판, 가설·제안 저장, 연구자 결정(accept/modify/reject + rationale), Q&A | core, eln, memory, analysis |

서비스 함수는 항상 `Session`을 첫 인자로 받고 Pydantic DTO를 반환한다. 라우터는 얇다(서비스 호출만).

### 불변성 정책

| 엔티티 | 불변 필드 | 변경 가능 |
|---|---|---|
| Experiment | project_id, code, raw_note, condition_block, attachments, performed_on, parent_experiment_id, created_at | title, author (오타 수정용; 감사 대상 — TASKS ELN-3) |
| Dataset, AnalysisResult, ExperimentDigest, Critique, Decision, AuditEvent | 전체 | 없음 |
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
오류 응답: `{code, message}` — 400 `validation_failed`, 404 `not_found`, 409 `immutable_record`.
요청 스키마 위반은 FastAPI 기본 422.

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

CSV 계약(`eln/schemas.py: DATASET_COLUMNS`):
- `calibration`: injection_id, level_ng_ml, analyte, analyte_area, is_area
- `recovery`: injection_id, sample_id, analyte, spike_ng_g, analyte_area, is_area
- `matrix_effect`: injection_id, curve(solvent|matrix), level_ng_ml, analyte, analyte_area

### memory
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/memory/projects/{project_id}/timeline` | `TimelineEntry[]` (부모 대비 변경 키) |
| GET | `/api/memory/projects/{project_id}/graph` | `ResearchGraph` (nodes, derived_from edges, roots) |
| GET | `/api/memory/projects/{project_id}/search?q` | `SearchHit[]` |
| GET | `/api/memory/experiments/{experiment_id}/lineage` | `ExperimentSummary[]` (root → self) |
| GET | `/api/memory/diff?a&b` | `ExperimentDiff` (relation, common_ancestor_id, condition_changes, note_diff, datasets) |
| GET/POST | `/api/memory/experiments/{experiment_id}/digests` | `DigestOut[]` / `DigestOut` |

### analysis
| Method | Path | 응답 |
|---|---|---|
| GET | `/api/analysis/criteria` | `AcceptanceCriteria` |
| POST | `/api/analysis/experiments/{experiment_id}/run` | `RunResponse` (동일 입력이면 재사용: idempotent) |
| GET | `/api/analysis/experiments/{experiment_id}/metrics` | `ExperimentMetrics` (+ `source_result_ids`) |
| GET | `/api/analysis/results?experiment_id&kind` | `AnalysisResultOut[]` |
| GET | `/api/analysis/results/{result_id}` | `AnalysisResultOut` (`output`은 `kind` 판별 유니온) |
| GET | `/api/analysis/compare?a&b` | `MetricsComparison` (Δ회수율, 분석물별 Δ, Welch t-test) |
| GET | `/api/analysis/projects/{project_id}/trend` | `TrendPoint[]` |

결과 종류(`kind`): `calibration`(slope, intercept, weighted R², back_calc, points, fit_line,
weighting_comparison) · `recovery`(groups, rows) · `is_response`(injections, flagged_count) · `matrix_effect`.

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
| POST | `/api/partner/ask` | `AskResponse` (answer, engine, evidence[], topics) |

## 4. 프론트엔드

```
frontend/src/
  api/            client.ts (openapi-fetch), schema.d.ts (생성), types.ts (별칭), queries.ts (React Query 훅)
  layout/         AppShell (헤더 + 탭 + 우측 고정 Research Partner 패널), tabs.ts
  components/     Card, Badge(Severity/Engine/Original), StatTile, DataTable, QueryState,
                  ExperimentPicker, ConditionTable, EvidenceChip
  lib/            format.ts (포맷 전용), selection.ts (?exp= URL 상태), chartColors.ts
  styles/         tokens.css (디자인 토큰 = CSS 변수) → tailwind.config.js 가 참조
  features/
    overview/     프로젝트 KPI, 회수율 추이, 타임라인, 감사 로그
    notebook/     원본 메모·조건 블록·CSV 미리보기·AI 정리본·Memory diff
    analysis/     검량선/회수율/IS/ME 패널, QC 플래그, 수치 비교
    research-ai/  비판(근거 칩), 가설, 제안 + 결정 폼
    partner-panel/ 우측 패널: 모드, 최근 비판, 질문
```

- 선택된 실험은 URL `?exp=<id>`로 탭/패널 간 공유된다.
- 각 탭은 lazy chunk. 탭 간 import 금지(공통은 `components/`·`lib/`로).
- 색은 `tokens.css` 변수만 사용(Tailwind `bg-surface`, `text-ink-muted`, `bg-crit-soft` …).

## 5. 시드 시나리오

프로젝트 "잔류농약 QuEChERS·LC-MS/MS 회수율 최적화" — 사과 매트릭스, 5종 농약, IS = TPP.
원본은 `backend/app/seed/data/seed.json`(메모·조건 블록) + CSV 12개. CSV는 `app/seed/generate.py`
(고정 시드)로 재현 가능하며 `tests/test_seed.py`가 일치 여부를 검사한다. 아래 수치는 **분석 코드가
CSV에서 계산한 값**이다(설계 목표).

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
