# ISSUES — 병합 후 남은 일 (우선순위)

5개 브랜치(analysis → eln → memory → partner → seed-expansion)를 main에 병합한 뒤의 상태다(2026-11-03).
출처: `feature/review:docs/REVIEW.md` ⑤ "병합 후로 미뤄도 되는 항목", 정리된 [CHANGES_REQUESTED.md](CHANGES_REQUESTED.md),
병합 중 새로 발견한 것(★). 모듈 담당 변경은 CHANGES_REQUESTED에 계약이 있다.

## 검증 상태

| 검사 | 결과 |
|---|---|
| backend `ruff check` · `ruff format --check` · `mypy app` (strict) | 통과 |
| backend `pytest` | 408 passed (lab 시드 테스트 포함, xfail 없음) — P1 스프린트 후 |
| `export_openapi --check` · frontend `check:api` | 통과 |
| frontend `tsc` · `vitest` · `vite build` | 통과 (vitest 80) |
| Playwright E2E (`npm run e2e`, reference 1 + lab 4) | 로컬 통과 |
| `alembic upgrade head && alembic check` | 로컬 통과 |
| GitHub Actions의 새 잡(`e2e`, Alembic 단계)과 Pages 배포 워크플로 | **이 세션에서 실행하지 못했다**(Actions 실행 불가). 로컬에서 같은 명령으로 확인했다. Pages는 저장소 Settings → Pages → Source를 "GitHub Actions"로 켜야 배포된다. |

**실패로 남긴 검사는 없다.** 다만 아래 ★ 항목은 병합 지시서의 전제와 실제 코드가 달라 판단해서 처리한 부분이다.

## ★ 병합 지시와 실제가 달랐던 점

1. **info 등급 플래그 범위.** 지시서는 `loq_above_lowest_level`, `uncertainty_high`, `outlier_suspected`를 info로 봤지만,
   코드에서 info는 `loq_above_lowest_level`뿐이고 나머지 둘은 **warning**이다(`analysis/criteria.py`). → P1-4에서 warning 유지로 결정.
   Memory는 severity 기준으로 분리했다(`qc_changes` = warning/critical, `qc_info_changes` = info). 그래서 #018→#024 diff에는
   Grubbs `outlier_suspected`(warning)가 여전히 resolved로 나온다. memory `test_diff`는 "critical·IS 억제 플래그가
   해소되지 않음"으로 단정을 바꿨다. → **결정 필요(P1, Analysis):** Grubbs 의심·불확도 초과를 info로 내릴지.
2. **calibration_type 미지원 플래그의 `value`.** `QCFlag.value`가 필수 숫자라 "정량하지 않은 회수율 주입 수(저장 CSV 행 수)"를 넣었다.
3. ~~**교차 프로젝트 회상.**~~ 해결: 헤더 프로젝트 전환(`?project=`), 교차 프로젝트 `/api/memory/search`·`/recall`,
   Critic 위 "과거에 같은 증상이 있었다"(#OA06 → 잔류농약 PSA 사용 이력). E2E `lab: #OA06 recalls …`가 UI로 확인한다.

## P1 — 정확성·원칙에 닿는 것 — **전부 해결 (2026-11-03, P1 스프린트)**

| # | 항목 | 해결 | 커밋 접두사 |
|---|---|---|---|
| 1 | Memory 근거 검증기가 부호를 무시하고 `"1,000"`을 1.0으로 읽음 | 두 검증기를 `app/core/grounding.py` 하나로 합쳤다(Partner 구현을 core로 이동, `add_quantities`·`ungrounded_numbers` 추가). Memory 정리본·Q&A도 Partner와 같은 부호·단위·천 단위·반올림 규칙. `memory/grounding.py`·`partner/grounding.py` 삭제, 테스트 `tests/test_grounding.py` + Memory 회귀 테스트 | core, partner, memory |
| 2 | `pre_post_spike`의 `calibration_type = "solvent + matrix-matched"` | `calibration_type = matrix-matched` + 별도 키 `curves_compared`. `knowledge.out_of_domain_changes()`가 Claude 초안(→ 규칙 대체)과 수정 결정(→ 400)을 막는다. **lab 이력 서명 변경 없음**: 14개 결정 중 `pre_post_spike`를 가리키는 것이 없다(D07·D08의 `matrix-matched`는 이미 도메인 안) | partner |
| 3 | 빈 숫자 칸(NaN)이 slope=NaN으로 저장 | Analysis `_frame()`이 계약 숫자 컬럼의 빈 칸·NaN·inf를 행 번호와 함께 `skipped`로 보고, 저장 단계가 출력·플래그의 비유한 값을 최종 거부. ELN은 `inf`/`Infinity`를 `not_finite` 오류로 거부(빈 칸은 이미 `blank_value`) | analysis, eln |
| 4 | Severity 정책 + `flag_count`의 info 합산 | **결정: Grubbs 의심·불확도 초과는 warning 유지**(정책은 `analysis/criteria.py` 상단). `TrendPoint.flag_count` = warning+critical, 새 필드 `info_flag_count` | analysis |
| 5 | Holm 입력 `p_value or 1.0` | `None`일 때만 1.0, p=0.0은 그대로 | analysis |
| 6 | ELN-3 동시 PATCH → 500 | 충돌(`uq_experiment_rev`) 시 트랜잭션 롤백 → 다시 읽어 번호·before/after 재계산 → 재시도(최대 5회), 끝내 지면 409 `revision_conflict`. 처음 넣은 SAVEPOINT는 pysqlite에서 RELEASE가 곧 커밋이라 롤백된 요청의 수정이 감사 이벤트 없이 남아 제거([SECURITY_REVIEW](SECURITY_REVIEW.md) §7) | eln |
| 7 | GET `/search`·`/recall`의 DDL·쓰기 | GET은 읽기 전용: 워터마크까지 FTS + 이후 감사 이벤트는 Python 스캔. 인덱스 동기화는 감사 이벤트를 남긴 트랜잭션의 커밋 직전(같은 트랜잭션), 시작 시(`main.py` lifespan), `POST /api/memory/search-index/sync`에서만([SECURITY_REVIEW](SECURITY_REVIEW.md) §6) | memory |
| 8 | 결정 피드백의 한계 | (a) `proposal_intent()` — 표기만 바꾼 재제안도 반복으로 판정(저장 서명은 그대로) (b) 채택·수정·과학적 기각·보류는 **그 실험에만** 적용, 기각된 변경 조합과 자원 제약은 프로젝트 전체 (c) 사유 키워드를 구(句)로 — "배치"·"부담" 단독 제거, "기기 일정"·"재주입 슬롯" → 주입 제약, "이미 시도"·"재고" 추가 (d) #OA09 "기기 일정" 기각이 이제 `extra_injections`로 분류되어 추가 주입이 필요한 대안이 나오지 않는다 | partner |
| 9 | 결정 감사 actor `user`·시점 오늘 고정 | `decide(..., actor=)`, `DecisionCreate/Out.decided_on`(실험일 이후·미래 불가, 컬럼 + Alembic `0002_decision_decided_on`), 감사 payload에 `decided_by`·`decided_on`. 시드는 `actor="seed"`, `decided_on` = 결정한 실험의 날짜 | partner, seed |
| 10 | `tests_proposal` 매칭이 거의 안 생김 | Partner `ProposalOut.implementing_changes`(수정 결정은 modifications, 설계 서술 키·미정 값 제외) → Memory가 그것과 결정일로 매칭, 부모 대비 실제로 바꾼 실험만, 계보 위치 무관, 기각 제안 제외. **lab에서 정답 7개 엣지와 정확히 일치**(`test_accumulation_lab`) | partner, memory |

P1 처리 중 새로 정한 것:
- 수정(modify) 결정의 modifications는 Memory 매칭에서 **제안 변경을 대체**한다(시드 7건과 `test_follow_up_experiments_implement_the_decision`의 의미와 같음). PAR-2 실험 초안은 여전히 "제안 변경 + modifications 우선 병합"이라 두 의미가 다르다 → P2-20.
- Memory 검색 점수: 인덱스 이후 기록(Python 스캔, 출현 횟수)과 FTS 기록(bm25)이 한 목록에 섞일 때 점수 척도가 다르다. 커밋 시 색인되므로 커밋 전 같은 트랜잭션·색인 실패 때만 생기는 일시 상태라 그대로 둔다.

## 보안·성능 점검 (2026-11-03)

[SECURITY_REVIEW.md](SECURITY_REVIEW.md) — CORS·의존성·업로드 상한·FTS 바인딩·오류 응답·GET 읽기 전용·revision 경쟁(P1-6·7 보강).
[PERFORMANCE.md](PERFORMANCE.md) — 1000 실험 성능 수정(2026-11-04): Records 1.3–1.9 s, 전체 관계 그래프 1.6 s, recall 0.26 s,
색인 재구축 1.1 s(전후 응답 동일). 남은 것: 지식 그래프 첫 구성 3.4 s(응답 크기 — `shares_conditions` 선택 관계화 등 결정 필요),
실패 아카이브 2.0 s(지표 요약 저장 — analysis 결정). 인증·rate limit은 범위 밖.

## P2 — 기능 완성

| # | 항목 | 담당 |
|---|---|---|
| 1 | ~~프로젝트 전환 UI(`?project=`)~~ — 완료 (헤더 전환, `?exp=`만 있으면 그 실험의 프로젝트) | shell |
| 2 | CompareModal에 memory `qc_changes`·`qc_info_changes`·단어 diff·결과 출처 표시, 결과 차이 경로 통일 | eln + memory |
| 3 | Overview가 프로젝트 활성 기준(`useCriteria(projectId)`) 표시 | shell |
| 4 | 결정 사유를 Memory 검색에 색인(wiring pull) | memory |
| 5 | `api/types.ts` 공용 별칭(eln·memory·partner), 전역 검색 바 헤더 이동 | shell |
| 6 | ARCHITECTURE.md 갱신 1건(analysis·eln·seed + 병합 결정 + memory/partner 직접 수정분 정합) | docs |
| 7 | ConditionBlock 정식 필드·라벨(`calibration_type` 3값, `spike_stage`, `is_addition_stage`, 라벨 6개) | eln |
| 8 | 시드 데이터 추가(템플릿·첨부·지식 노트) + `test_contract` `file_id` + 첨부 다운로드를 계약에 포함 | seed, eln |
| 9 | Analysis `spike_recovery`, IS 층화 `by_is_flag`, 요인 실험 결과 종류 | analysis |
| 10 | 결과에 기록된 `criteria_version`으로 기준을 조회하는 API(분석 패널이 현재 활성 기준과 비교하는 문제) | analysis |
| 11 | Partner가 신규 지표(`qc_verdicts`, `p_holm`, `hedges_g`, `expanded_uncertainty_pct`)와 Memory recall 근거 조각 활용 | partner |
| 12 | PAR-4 패널 이력이 실험별이 아니라 프로젝트 전체 | partner |
| 13 | ELN 실험 작성 폼이 Partner 제안 초안(PAR-2)을 초기값으로 받는 경로 | eln |
| 14 | lab 프로파일 픽스처 위에서 모듈 테스트 통과(시드 모양 하드코딩 제거) | 각 모듈 |
| 15 | 보충 기록(addenda)을 검색·정리본 입력에 포함 | memory |
| 16 | ~~두 프로젝트를 가로지르는 검색/회상 API~~ — 완료 (`/api/memory/search`, `/recall`) | memory |
| 18 | Records 탭의 한계: 작업자 쌍은 조건 블록 **완전 일치**·14일 이내만(부분 일치 비교 없음), 실패 = critical 플래그만(경고 반복은 아카이브에 없음), 원인 가설 메모 규칙은 키워드 부분 문자열("점검 후"도 기기 상태로 잡힘), 결정→후속 실험 연결은 결정 시각 대신 `performed_on`과 조건값 일치로 찾는다(P1-10으로 memory `tests_proposal`이 lab에서 정답 7건을 내므로 Records가 그 엣지를 쓰도록 바꾸는 일이 남음) | analysis, partner, memory |
| 19 | 과거 사례는 저장된 비판에 스냅샷되지 않는다(조회 시점 계산). Claude 모드 비판의 근거(Evidence)로 넣으려면 `partner/context.py`에 연결 필요 | partner |
| 20 | 수정 결정의 의미 통일: PAR-2 초안은 modifications를 제안 변경 위에 병합, `implementing_changes`·시드는 대체로 본다(위 P1 참고) | partner |
| 17 | 데모 모드: 미리 계산하지 않은 검색어·비교 쌍은 "시나리오에 없음"으로 표시된다(lab은 부모·루트·직전 실험 쌍만) | shell |

## P3 — 정리·품질

- **Analysis**: LOD 기본 `k=3.0`(TASKS는 3.3σ/S; 기준 `lod_k`로만 변경 가능), F-검정은 1/x와 1/x²를 구분하지 못함,
  `methods.py` 가정 문장과 `CalibrationPanel` "이분산 → 가중 필요" 배지는 해석에 가깝다, ANA-1 #023 테스트에 수치 범위 단정 없음,
  `test_calculations.py`의 Σ|%RE| 순환 단정 1곳.
- **ELN**: 모델 docstring "Corrections never edit an original"과 title/author in-place 수정의 표현 불일치,
  첨부 다운로드 `include_in_schema=False`, 블롭을 트랜잭션 전에 써서 롤백 시 고아 블롭, UI의 "5 MB/20 MB" 하드코딩,
  `CompareModal`의 `?? 0`(값이 없을 때 0 표시), ELN 커버리지 게이트(pytest-cov, 선택).
- **Memory**: trigram 토크나이저 SQLite ≥ 3.34 런타임 확인 없음, MEM-3에서 조건 키 이름 매칭 제거·다중 단어 AND,
  테스트의 시드 수치 하드코딩(`test_diff.py`, `test_knowledge_graph.py`), main 시절 diff 단정(`relation`, `unchanged_keys`, `datasets.both`) 삭제.
- **Partner**: `ctx.trend` 조회 후 미사용, 증거 라벨에서 분석물명을 `split(" ")`로 역파싱, Partner 내부 산술 잔재
  (`rules.py` 상대 개선율, `context.py` `min(g.n)` — 표시값은 아님).
- **경계 기록**: memory가 Frontend Shell 영역(`features/overview/**`)·`ARCHITECTURE.md`·`tests/test_contract.py`를 직접 수정했고
  커밋 하나에 여러 모듈을 섞었다(REVIEW §Memory-4). partner도 `queries.ts` 헤더·SSE 코드·`ARCHITECTURE.md`를 직접 수정했다.
  병합 세션이 사후 승인·정리했으며 재발 방지는 CLAUDE.md §3 규칙으로 충분하다고 본다.
- **core**: 인증/사용자 식별(README "무엇을 의도적으로 만들지 않았나").
