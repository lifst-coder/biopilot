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

## [OPEN] analysis (+ eln) — 숫자 칸 결측(NaN) 처리
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: ELN `_validate_csv`는 빈 숫자 칸을 통과시킨다(pandas float NaN). 그런데 `calibrate`/`fit_line`이
  NaN을 그대로 받아 slope=NaN 결과를 **저장**한다(재현: 검량선 CSV 한 행의 analyte_area를 비우고 run).
  실제 장비 내보내기에는 빈 칸이 흔해서 시드는 결측을 "행 미보고"로만 표현했다.
- 제안: Analysis가 NaN 행을 계산에서 제외하고 `excluded_rows: [{injection_id, analyte, column}]`을 결과에 기록
  (+ QC 플래그 `missing_values`, `METHOD_VERSIONS` 올림). 또는 ELN이 빈 숫자 칸을 400으로 거부 — 둘 중 하나는 필요.
- 완료 기준: 빈 칸 CSV로 NaN이 저장되지 않는 테스트. 처리 후 시드에 빈 칸 결측을 추가할 수 있다.

## [DONE] partner — 기각된 제안 반복 금지 (결정 이력 인지 비판)
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: Critic이 같은 프로젝트에서 이미 기각된 제안을 다시 낸다.
- 처리: feature/partner의 Decision History 피드백(`app/partner/feedback.py`, 설계 템플릿 선택 시 결정된
  `proposal_signature` 제외·자원 제약·`supersedes_proposal_ids`).
- 확인 (2026-11-03, seed-expansion + feature/partner 병합 상태): `load_seed_spec("lab").history.repeat_probes`
  (8개 프로브, 기각 7건 전부)에서 다시 비판해도 기각된 서명이 나오지 않음. `tests/test_seed_lab.py::
  test_critic_does_not_repeat_rejected_proposals`의 xfail 제거 — strict=False라 픽스처 오류까지 XFAIL로 가리고
  있었다. 저장된 이력 자체도 검사(`test_later_critiques_never_reoffer_a_decided_proposal`).

## [OPEN] partner — 결정 기록의 actor·시점
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03 (feature/partner 기준으로 재확인 2026-11-03)
- 필요 이유: `decide()`는 감사 actor를 `"user"`로 고정하고(`decision.*`, `status.change` 이벤트 둘 다)
  `created_at`은 현재 시각뿐이다. 시드가 넣는 과거 결정 14건이 사용자 행위·시드 실행일로 기록된다(다른 시드
  레코드는 actor=`seed`). 시드는 이제 결정을 각 비판 직후에 기록하므로 순서는 맞지만(감사 id 순서로 검증)
  날짜는 여전히 오늘이다.
- 제안: `decide(..., *, actor: Actor = "user")` 키워드 인자, `DecisionCreate.decided_on: date | None`(과거 결정 이관용, 필드 추가만).
- 완료 기준: 시드 결정의 감사 actor가 `seed`, `decided_on`이 실험 날짜 이후로 기록. (시드 쪽은 `loader._replay_history`
  에서 인자만 넘기면 된다.)

## [OPEN] core — 시드 프로파일 설정
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: auto-seed 프로파일을 지금은 `app.seed.loader`가 환경변수 `BIOPILOT_SEED_PROFILE`로 직접 읽는다
  (`.env` 파일은 반영 안 됨).
- 제안: `Settings.seed_profile: Literal["reference", "lab"] = "reference"`, `main.py`에서
  `seed_if_empty(session, settings.seed_profile)`로 전달, `.env.example`에 항목 추가.
- 완료 기준: `.env`의 `BIOPILOT_SEED_PROFILE=lab`로 lab 시드.

## [OPEN] eln/memory/analysis/partner 테스트 — 시드 모양 하드코딩 제거 (lab을 기본 시드로 전환하기 위한 선행)
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: 모듈 테스트가 reference 시드 모양에 묶여 있다 — 실험 id 1/7 = #018/#024(`test_memory_api`,
  `test_partner_api`), 타임라인 7건·엣지 6개·루트 #018, `"7건"` 문구, pending 제안 = #024 비판 제안 전부 등.
  그래서 기본 auto-seed를 lab으로 바꿀 수 없다.
- 제안: id 대신 `seeded["#024"]`(코드 조회), 개수는 `len(seeded) - 1` 등 시드 대비 상대 검증. 각 모듈 담당이 자기 테스트 수정.
- 완료 기준: `BIOPILOT_SEED_PROFILE=lab pytest` 전체 통과 → 그 다음 core 요청으로 기본값을 lab으로.

## [OPEN] frontend/shell — 프로젝트 선택
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: `lib/selection.ts useActiveProject()`가 첫 프로젝트만 쓴다. lab 시드에는 프로젝트가 2개(유기산 #OA01–#OA12).
- 제안: 헤더 프로젝트 전환 + URL `?project=<id>` (기존 `?exp=`와 같은 방식), 프로젝트 전환 시 `?exp=` 초기화.
- 완료 기준: lab 시드에서 두 프로젝트의 4탭이 모두 렌더.

## [OPEN] eln — 조건 키 라벨 추가
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: lab 시드가 쓰는 조건 키 `mobile_phase`, `injection_volume_ul`(+ Partner 제안 키 `injection_dilution`,
  `calibration_type`)에 라벨이 없어 diff·타임라인에 키 이름이 그대로 노출된다.
- 제안: `CONDITION_FIELD_LABELS`에 `mobile_phase: 이동상`, `injection_volume_ul: 주입량 (µL)`,
  `injection_dilution: 주입 희석`, `calibration_type: 검량선 종류` 추가.
- 완료 기준: `/api/eln/condition-fields`에 포함.

## [OPEN] docs — ARCHITECTURE §5 시드 시나리오 갱신
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: §5는 7개 실험 시나리오만 설명한다. 시드는 이제 `reference`/`lab` 프로파일을 가진다.
- 제안: §5에 프로파일 표와 `backend/app/seed/SCENARIO.md` 링크 추가, 원본 위치를 `data/residue.json` 등으로 정정.
- 완료 기준: 문서 갱신.

## [OPEN] memory — 제안→후속 실험 엣지용 정답 데이터 제공 (MEM-1 참고)
- 요청자: seed (seed-expansion) · 날짜: 2026-11-03
- 필요 이유: TASKS MEM-1 `tests_proposal` 엣지를 만들 때 검증할 정답이 필요하다.
- 제공: `load_seed_spec("lab").history.decisions[*].followed_by` — 수락/수정 결정 7건의 후속 실험 코드
  (`SeedResult.decided_proposal_ids`로 제안 id 조회). 시드 쪽 변경은 필요 없음, 공지용.
  (2026-11-03 갱신: 결정 id가 시간순 D01–D14로 바뀜 — feature/partner 엔진에 맞춰 이력을 다시 씀. 후속 실험 7건과
  그 코드(#007 #017 #025 #026 #028 #OA07 #OA11)는 그대로. 결정은 `decision.proposal.template_id/signature`로 제안을 지정.)
- 완료 기준: MEM-1 테스트가 lab 시드의 7개 엣지를 확인.
