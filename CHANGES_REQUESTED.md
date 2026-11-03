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

## [OPEN] core/composition — `app/wiring.py` 검토·소유권 확정
- 요청자: memory (feature/memory) · 날짜: 2026-11-03
- 필요 이유: Memory는 eln에만 의존해야 하지만 diff(결과·QC 차이)·recall·지식 그래프는 Analysis 결과와
  Partner 레코드를 보여줘야 한다. Memory는 `memory.schemas.FactProvider` 포트만 정의하고, 구현체
  (`AnalysisFactProvider`, `PartnerFactProvider`)는 기능 모듈 밖 composition root `app/wiring.py`에 두었다.
  `app/main.py`에는 import 한 줄과 등록 한 줄(`install_memory_fact_providers()`)만 추가했다.
- 제안하는 계약: `memory.service.register_fact_provider(provider)`. 제공자는 각 모듈 service만 읽고 새 숫자를 만들지 않는다.
- 완료 기준: core 담당이 위치(`app/wiring.py`)와 `create_app` 등록 방식을 승인하거나 대안을 제시. Analysis/Partner
  담당은 자기 서비스 시그니처를 바꿀 때 `app/wiring.py`도 함께 고친다.

## [OPEN] core — 마이그레이션 대상 추가 (Alembic 요청에 병합)
- 요청자: memory · 날짜: 2026-11-03
- 필요 이유: `memory_digests`에 `fallback_reason`, `input_fingerprint` 컬럼 추가. 새 테이블 `memory_knowledge_notes`,
  `memory_index_state`. FTS5 가상 테이블 `memory_search_fts`(검색 시 `CREATE ... IF NOT EXISTS`). Alembic 도입 전까지
  기존 `backend/biopilot.db`는 삭제 후 재시드해야 한다.
- 완료 기준: memory revision 파일로 위 스키마가 생성됨.

## [OPEN] frontend/notebook (ELN) — ExperimentDiffView에 결과·QC 차이와 단어 diff 표시
- 요청자: memory · 날짜: 2026-11-03
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
