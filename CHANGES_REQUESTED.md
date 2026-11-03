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

## [OPEN] core — LLM 게이트웨이 텍스트 스트리밍 (`stream_text`)
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: PAR-9 `/api/partner/ask/stream`은 게이트웨이가 `stream_text`를 제공할 때만 Claude 토큰을
  임시(provisional) delta로 흘린다. 현재 `ClaudeGateway`에는 없어서 Claude 모드에서도 검증 후 한 번에 전달된다.
- 제안하는 계약: `LLMGateway`에 선택 메서드 `stream_text(*, system: str, prompt: str) -> Iterator[str]`
  (Messages API streaming, 실패 시 예외). Partner는 `app.partner.service.StreamingGateway`
  (runtime_checkable Protocol)로 감지하므로 추가만 하면 된다. `RulesOnlyGateway`는 구현하지 않는다.
- 완료 기준: FakeGateway 대역으로 delta 순서 테스트, 네트워크 없는 테스트 유지.

## [OPEN] memory — 연구자 결정(Decision) 피드백을 Research Memory에 반영
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: 기각·수정 사유는 지금 `partner_decisions`에 저장되고 Partner가 이후 비판·제안에 반영한다
  (`GET /api/partner/projects/{id}/decisions`). Memory는 Partner를 import할 수 없으므로(의존 방향),
  Memory 검색·타임라인에서 결정 사유가 보이려면 Partner가 Memory로 밀어 넣는 API가 필요하다.
- 제안하는 계약: MEM-7 `KnowledgeNote`에 출처 필드 추가 후
  `memory.service.create_knowledge_note(session, project_id, *, statement, linked_experiment_ids,
  author, source_ref: str | None = None) -> KnowledgeNoteOut` (불변 + 감사). Partner `decide()`가
  `source_ref="partner.Decision:<id>"`로 호출한다(Partner 쪽 한 줄 추가는 MEM-7 완료 후 진행).
- 완료 기준: 기각 사유 텍스트가 `/api/memory/projects/{id}/search` 결과에 나타남.

## [OPEN] analysis — 전·후 첨가 비교(`spike_recovery`) 결과 종류
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: Designer의 최우선 제안(추출 전·후 첨가 비교)은 RE = pre/post, ME = post/용매, PE = pre/용매
  계산이 필요하다. Partner는 숫자를 계산하지 않으므로 Analysis 결과로 받아야 Critic이 판정을
  `indeterminate` → `supported/refuted`로 바꿀 수 있다.
- 제안하는 계약: ELN dataset kind(예: `spike_recovery`: injection_id, analyte, spike_stage(pre|post|solvent),
  level_ng_ml, analyte_area, is_area) + result kind `spike_recovery`(분석물별 RE·ME·PE, QC 플래그).
  조건 블록 `spike_stage`를 쓰면 Partner의 `post_spike_recorded`가 이미 이를 인식한다.
- 완료 기준: 결과가 생기면 `ExperimentMetrics`에 분석물별 RE/ME 필드(추가만).

## [OPEN] analysis — IS 이탈 주입별 회수율 층화 + 요인 실험 분산분석
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: (1) Critic의 "IS 보정 왜곡" 대안 설명을 판정하려면 IS 이탈 주입과 정상 주입의 회수율 비교가
  필요하다(현재는 "Analysis 결과 없음"을 확정 불가 이유로 표시). (2) Designer의 2×2 요인 실험 결과 판독에
  주효과·교호작용 검정이 필요하다.
- 제안하는 계약: `RecoveryOutput.by_is_flag: {flagged: group, normal: group, welch_p}`(추가 필드),
  result kind `factorial`(조건 블록 `design = factorial 2x2`, `factor_<key>` 값 사용).
- 완료 기준: 시드 #024에서 by_is_flag 생성, 요인 실험 단위 테스트.

## [OPEN] eln — 조건 블록 키 `calibration_type`·`spike_stage`·`is_addition_stage` 정식 필드화
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: Critic이 매트릭스 매칭 검량선 사용 여부·전/후 첨가 기록·IS 첨가 시점을 이 키로 판단한다.
  지금은 `ConditionBlock` extra 키라서 라벨·검증이 없다. 시드 실험에는 기록이 없어 "미기록"으로 판정된다.
- 제안하는 계약: `ConditionBlock`에 `calibration_type: Literal["solvent","matrix-matched","standard-addition"] | None`,
  `spike_stage: str | None`, `is_addition_stage: Literal["pre-extraction","post-extraction"] | None` +
  `CONDITION_FIELD_LABELS` 라벨. ELN-8 실험 생성 폼은 `GET /api/partner/proposals/{id}/experiment-draft`의
  `draft`(ExperimentCreate)를 초기값으로 쓸 수 있다.
- 완료 기준: 기존 extra 값 하위호환, 라벨 노출.

## [OPEN] frontend shell — Partner 신규 스키마 별칭을 `api/types.ts`에
- 요청자: partner · 날짜: 2026-11-03
- 필요 이유: `CriticAssessment`, `ExperimentDesign`, `DecisionHistoryEntry`, `AnswerStatement` 등을 지금은
  `features/research-ai/types.ts`·`partner-panel/AnswerView.tsx`에서 `Schemas[...]`로 로컬 선언한다.
- 완료 기준: 공용 별칭 추가 후 Partner 화면은 로컬 별칭을 제거(Partner 담당이 후속 처리).
