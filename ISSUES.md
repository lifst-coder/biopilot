# ISSUES — 병합 후 남은 일 (우선순위)

5개 브랜치(analysis → eln → memory → partner → seed-expansion)를 main에 병합한 뒤의 상태다(2026-11-03).
출처: `feature/review:docs/REVIEW.md` ⑤ "병합 후로 미뤄도 되는 항목", 정리된 [CHANGES_REQUESTED.md](CHANGES_REQUESTED.md),
병합 중 새로 발견한 것(★). 모듈 담당 변경은 CHANGES_REQUESTED에 계약이 있다.

## 검증 상태

| 검사 | 결과 |
|---|---|
| backend `ruff check` · `ruff format --check` · `mypy app` (strict) | 통과 |
| backend `pytest` | 360 passed (lab 시드 테스트 포함, xfail 없음) |
| `export_openapi --check` · frontend `check:api` | 통과 |
| frontend `tsc` · `vitest` · `vite build` | 통과 (vitest 56) |
| Playwright E2E (`npm run e2e`, reference 1 + lab 2) | 로컬 통과 |
| `alembic upgrade head && alembic check` | 로컬 통과 |
| GitHub Actions의 새 잡(`e2e`, Alembic 단계)과 Pages 배포 워크플로 | **이 세션에서 실행하지 못했다**(Actions 실행 불가). 로컬에서 같은 명령으로 확인했다. Pages는 저장소 Settings → Pages → Source를 "GitHub Actions"로 켜야 배포된다. |

**실패로 남긴 검사는 없다.** 다만 아래 ★ 항목은 병합 지시서의 전제와 실제 코드가 달라 판단해서 처리한 부분이다.

## ★ 병합 지시와 실제가 달랐던 점

1. **info 등급 플래그 범위.** 지시서는 `loq_above_lowest_level`, `uncertainty_high`, `outlier_suspected`를 info로 봤지만,
   코드에서 info는 `loq_above_lowest_level`뿐이고 나머지 둘은 **warning**이다(`analysis/criteria.py`).
   Memory는 severity 기준으로 분리했다(`qc_changes` = warning/critical, `qc_info_changes` = info). 그래서 #018→#024 diff에는
   Grubbs `outlier_suspected`(warning)가 여전히 resolved로 나온다. memory `test_diff`는 "critical·IS 억제 플래그가
   해소되지 않음"으로 단정을 바꿨다. → **결정 필요(P1, Analysis):** Grubbs 의심·불확도 초과를 info로 내릴지.
2. **calibration_type 미지원 플래그의 `value`.** `QCFlag.value`가 필수 숫자라 "정량하지 않은 회수율 주입 수(저장 CSV 행 수)"를 넣었다.
3. ~~**교차 프로젝트 회상.**~~ 해결: 헤더 프로젝트 전환(`?project=`), 교차 프로젝트 `/api/memory/search`·`/recall`,
   Critic 위 "과거에 같은 증상이 있었다"(#OA06 → 잔류농약 PSA 사용 이력). E2E `lab: #OA06 recalls …`가 UI로 확인한다.

## P1 — 정확성·원칙에 닿는 것 (다음 스프린트)

| # | 항목 | 담당 | 근거 |
|---|---|---|---|
| 1 | ★ Memory 근거 검증기(`memory/grounding.py`)가 부호를 보지 않고(`\d+` 정규식), `"1,000"`을 1.0으로 읽는다. Partner C5와 같은 종류 — 정리본·Q&A의 Claude 모드에서 방향이 틀린 숫자가 통과할 수 있다. Partner `grounding`과 같은 부호 규칙으로 맞추고 회귀 테스트 추가 | memory | REVIEW ⑤ Memory, 병합 중 확인 |
| 2 | Partner `pre_post_spike` 제안의 `calibration_type = "solvent + matrix-matched"`가 확정 도메인 밖 → ELN Literal 필드 도입 시 PAR-2 초안 400. 값 변경은 seed lab 이력 서명 갱신과 함께 | partner + seed → eln | CHANGES_REQUESTED ConditionBlock |
| 3 | 빈 숫자 칸(NaN)이 slope=NaN 결과로 **저장**된다 | analysis (+eln) | CR NaN |
| 4 | Severity 정책 결정(위 ★1) + Overview `TrendPoint.flag_count`가 info 플래그를 합산 | analysis, shell | REVIEW §7-2 |
| 5 | Holm 보정 입력 `p_value or 1.0`이 p=0.0(언더플로)을 1.0으로 바꾼다(`analysis/service.py`) | analysis | REVIEW ⑤ |
| 6 | ELN-3 메타데이터 동시 PATCH에서 revision `count+1` → IntegrityError 500 | eln | REVIEW ⑤ |
| 7 | GET `/search`·`/recall`이 FTS DDL·쓰기·커밋을 한다(GET 부작용) | memory | REVIEW ⑤ |
| 8 | 결정 피드백의 한계: 서명이 값 문자열 정확 일치라 Claude가 바꿔 말하면 통과, 수용·과학적 기각이 대조군을 영구 억제, 사유 분류가 부분 문자열 키워드("배치" → 시료 부담), #OA09 "기기 일정" 기각 후에도 재주입 대안 | partner | REVIEW §12 |
| 9 | 결정 감사 actor가 `user`·시점이 오늘로 고정(lab 시드 결정 14건) | partner (+seed) | CR |
| 10 | 제안→후속 실험 `tests_proposal` 매칭이 설계형 제안에서 거의 생기지 않음(`implementing_changes` 계약) | memory + partner | CR |

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
| 18 | Records 탭의 한계: 작업자 쌍은 조건 블록 **완전 일치**·14일 이내만(부분 일치 비교 없음), 실패 = critical 플래그만(경고 반복은 아카이브에 없음), 원인 가설 메모 규칙은 키워드 부분 문자열("점검 후"도 기기 상태로 잡힘), 결정→후속 실험 연결은 결정 시각 대신 `performed_on`과 조건값 일치로 찾는다(memory `tests_proposal`이 seed 결정 시각 때문에 비어 있음 — P1-10) | analysis, partner, memory |
| 19 | 과거 사례는 저장된 비판에 스냅샷되지 않는다(조회 시점 계산). Claude 모드 비판의 근거(Evidence)로 넣으려면 `partner/context.py`에 연결 필요 | partner |
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
- **core**: 인증/사용자 식별(README "의도적으로 구현하지 않은 것").
