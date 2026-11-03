# Memory: 지식 그래프 · 출처 포함 diff · 검색/회상 · 유사 실험 (MEM-1–8)

## 요약
TASKS.md의 Memory 항목 MEM-1–8을 모두 구현했고, 아래 기능을 추가했다.
수정 범위는 `backend/app/memory/**`와 Overview 탭의 그래프·검색 영역이다. 공유 파일 변경은 최소한으로 하고 모두 아래에 적었다.

| 영역 | 내용 |
|---|---|
| 지식 그래프 | `GET /api/memory/projects/{id}/knowledge-graph`. 노드 유형: Experiment, Condition, Analyte, Sample, Strain, Result, Critique, Hypothesis, Proposal, Decision, Note. SQLite에서 NetworkX `MultiDiGraph`로 만든다. `core_audit_events`를 변경 피드로 써서 워터마크 이후 이벤트만 **증분 반영**하고(`refresh.mode` = full/incremental/cached), 롤백되면 전체 재구성한다. |
| 결정론적 diff | `GET /api/memory/diff`에 필드를 추가했다(기존 필드는 그대로). `condition_changes[].sources`, `result_changes[]`(값·Δ·p는 Analysis `compare` 값을 그대로 사용), `qc_changes[]`(appeared/resolved/persisting), `note_diff[].segments[]`(단어 단위). 모든 항목에 출처(ref_type·ref_id·field·experiment_id)가 붙는다. |
| 검색 | SQLite FTS5 `trigram` 인덱스를 쓴다(한국어 부분 일치, 2글자 검색어는 LIKE로 처리). bm25 `score`, `highlights`, `source`를 반환한다. 인덱스 워터마크는 인덱스 행과 같은 트랜잭션에 저장한다. |
| 회상 · Q&A | `GET /recall`은 검색어를 균주·시료·조건·분석물 facet으로 분류하고 관련 실험, 프로토콜 변형, 저장된 결과를 묶어 반환한다. `POST /ask`는 규칙 모드(기본)에서 근거 조각을 그대로 반환하고, Claude 모드에서는 요약을 만든다. Claude 답이 근거 키 불일치이거나 근거 없는 숫자를 담으면 규칙 모드로 대체하고 `fallback_reason`을 남긴다. |
| 유사 실험 | `GET /experiments/{id}/similar`. 조건 벡터 유사도를 쓴다(숫자 키는 1−\|Δ\|/범위, 범주 키는 일치 여부, 키 합집합 평균). |
| MEM-1 | `/graph?relations=shares_conditions,tests_proposal`. 기본 응답은 기존과 같다(derived_from 6엣지). |
| MEM-2 · MEM-5 | `/projects/{id}/conditions/{key}/history`, `/compare-conditions?ids=1,2,7&varying_only=true` |
| MEM-6 · MEM-8 | 정리본 숫자 근거 검증과 `DigestOut.fallback_reason`, 입력 지문 기반 `stale` |
| MEM-7 | `/projects/{id}/knowledge-notes` (생성·조회만 지원, 불변 + 감사, 검색과 그래프에 포함) |
| 프론트 (Overview) | 지식 그래프 시각화(유형 필터, 이웃 강조, 키보드 포커스, **실험 노드 클릭 시 `/notebook?exp=`**). 전역 검색 바는 facet 칩, 관련 실험, 하이라이트된 본문 일치를 보여준다. |

## 완료 기준 확인
- **#018 vs #024 diff**: 추출 시간(10→5)과 흡착제(C18→GCB) 차이를 두 실험의 `condition_block.*` 출처와 함께 반환한다. 평균 회수율 차이(Δ≈−27 %p, Welch p<0.05)는 두 recovery `AnalysisResult` id를 출처로 단다. 분석물별 Δ도 반환한다. carbendazim·thiabendazole 기준 미달과 IS 억제 3건은 `appeared` QC 변화로 나온다(`test_diff.py`).
- **테스트 커버리지**: `app/memory` + `app/wiring.py` 커버리지 99%(statements). 백엔드 112 passed, 프론트 17 passed.
- ruff · ruff format · mypy(strict) · pytest · export_openapi --check · check:api · typecheck · vitest · build 모두 통과.

## 설계 메모: 계층 규칙을 지키는 방법
Memory는 eln에만 의존할 수 있다(`test_architecture.py`, 약화하지 않음). 그래서 Analysis 결과와 Partner 레코드는
`memory.schemas.FactProvider` **포트**로 받는다. 구현체는 기능 모듈 밖의 composition root `app/wiring.py`에 두고
`create_app()`에서 등록한다. 제공자는 각 모듈 service를 읽기만 하고 숫자를 새로 만들지 않는다.
제공자가 없어도 Memory는 ELN과 감사 로그 payload만으로 동작한다(테스트로 확인).

## 공유 파일 변경 (CHANGES_REQUESTED.md에 기록)
- `backend/app/wiring.py` (신규, composition root), `backend/app/main.py` (import 1줄 + 등록 1줄) → core 검토 요청
- `backend/tests/test_contract.py`: 새 GET 엔드포인트용 파라미터 표 항목만 추가(검사 로직은 그대로)
- `frontend/src/api/queries.ts`: memory 섹션 끝에 훅 3개 추가(허용 범위)
- 생성 파일 `openapi.json`, `schema.d.ts` 재생성

## 후속 요청 (CHANGES_REQUESTED.md)
core 마이그레이션(새 컬럼·테이블. **기존 `biopilot.db`는 삭제 후 재시드 필요**), Notebook diff 화면에 결과·QC·단어 diff 표시,
검색 바를 헤더(AppShell)로 이동, `types.ts` 별칭 추가, Partner의 recall 근거 활용, seed 예시 지식 노트.

## 테스트 방법
```bash
cd backend && pytest app/memory && python -m app.scripts.export_openapi --check
cd frontend && npm run check:api && npm run typecheck && npm test && npm run build
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012wEvKgJDtRr2KoSMUq4aG7
