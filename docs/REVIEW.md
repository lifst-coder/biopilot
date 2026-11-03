# BioPilot 병렬 브랜치 통합 검토 (REVIEW)

- 검토 기준: `main`(8a504c4)의 CLAUDE.md · ARCHITECTURE.md · TASKS.md
- 검토일: 2026-11-03 · 이 세션은 검토 전용이다. 저장소의 브랜치·파일은 수정하거나 커밋하지 않았다.
  병합 시뮬레이션은 scratch 클론에서만 했다.
- 대상 브랜치:

| 모듈 | 브랜치 | HEAD |
|---|---|---|
| ELN | **`feature/eln` 브랜치가 원격에 없다.** ELN-1..9 커밋이 있는 유일한 브랜치는 `claude/loving-lamport-80sjhe`(PR #3)이므로 이것을 ELN 브랜치로 검토했다. | b984cf8 |
| Memory | `feature/memory` | b532a8d |
| Analysis | `feature/analysis` | 0a6ca87 |
| Partner | `feature/partner` | 360b033 |
| Seed | `feature/seed-expansion` | 6d51806 |

  나머지 `claude/*` 브랜치는 위 feature 브랜치와 같은 SHA이므로 무시했다.
- 직접 실행한 검증:
  - 브랜치마다 `pytest`, `ruff check`, `ruff format --check`, `mypy app`, `export_openapi --check`,
    프론트 `tsc -b --noEmit`, `vitest run`, `check:api`(openapi → schema.d.ts 재생성 후 diff).
  - scratch 클론에서 단독 병합 4종(seed+X), 쌍 병합 6종, 전체 병합을 만들고 pytest·tsc·vitest를 돌렸다.
  - lab 프로파일 + Partner 엔진 재현 스크립트(§12), multipart 결함 재현(§13),
    ELN 헤더 공백 회귀 재현(§2-ELN).
- 표기: 경로는 해당 브랜치 기준이다. `파일:라인`은 그 브랜치의 라인이다.
  "병합 상태"는 5개 브랜치를 seed → eln → memory → analysis → partner 순으로 병합한 scratch 결과를 뜻한다.

---

## ① 브랜치별 한 줄 판정

| 브랜치 | 판정 | 근거 요약 |
|---|---|---|
| **analysis** | **병합 가능** (경미한 후속 있음) | ANA-1..7·9 구현, ANA-8 부분 구현(△). 손계산 테스트는 독립 유도값이고 직접 재계산해 모두 일치했다. 불변·감사 위반 없음. 단독 테스트 전부 통과(pytest 116, vitest 22). 결함은 `queries.ts`에서 기존 `useCriteria`를 수정한 것, LOD 기본 k=3.0, Holm의 `or 1.0` 정도로 경미하다. |
| **eln** | **조건부** | ELN-1..9 중 8개 O, ELN-5 △. 감사·불변은 견고하다. 다만 ⑴ 헤더 공백 CSV가 업로드는 201로 통과하는데 이후 analysis run이 500이 되는 회귀(main은 400) ⑵ 자체 multipart 파서가 **잘린 업로드를 불변 원본으로 저장** ⑶ Partner와 `useExperimentDraft` 훅 이름이 충돌한다. ⑴⑵는 병합 전 수정이 필요하다. |
| **memory** | **조건부** | MEM-1..8 중 7개 O, MEM-3 △. 경계 위반: `app/wiring.py` 신설, `main.py` 2줄 수정, Frontend Shell 영역(`features/overview/**`) 수정. analysis·partner와 병합하면 자기 테스트 3개가 실패한다. GET `/search`·`/recall`이 DB에 쓰기를 한다. |
| **partner** | **조건부** | PAR-1·2·3·5·6·7·8 O, PAR-4·9 △. "기각 제안 미반복"은 실제로 동작함을 확인했다(§12). 다만 PAR-9 Claude 스트리밍은 core에 `stream_text`가 없어 조용히 비스트리밍으로 동작한다. 근거 검증기가 부호를 무시한다(`abs`). `queries.ts` 헤더를 수정했고 훅 이름이 충돌한다. 병합하면 seed의 lab 프로파일이 로드 자체를 못 한다(원인은 seed 쪽 결합). |
| **seed-expansion** | **재작업 필요** (lab 부분) | reference 프로파일은 main과 바이트 단위로 동일하다(CSV 12개 cmp 일치). 그러나 lab 결정 이력이 main 규칙 엔진의 **출력**에 결합되어 있어 partner와 병합하면 `SeedError`로 로드가 실패한다. `load_seed_spec()`의 반환형 변경으로 ELN 테스트가 깨진다. CLI 기본값은 lab, 앱 기본값은 reference로 서로 다르다. `xfail(strict=False)`가 setup 오류까지 가린다. |

---

## ② 치명적 문제

### C1. 5개 브랜치를 그대로 병합하면 백엔드 테스트 24개가 실패·오류(생성 파일을 재생성하지 않으면 +1), 프론트 타입체크가 실패한다

병합 상태에서 실측한 결과다.

**백엔드:** FAILED 6 + ERROR 18(lab fixture). openapi를 재생성하지 않으면 계약 테스트 1개가 추가로 실패한다.

| 원인 쌍 | 실패 테스트 | 원인 |
|---|---|---|
| seed + partner | `tests/test_seed_lab.py` 전부 ERROR(18개), `tests/test_seed_profiles.py::test_app_auto_seeds_lab_profile_from_env`, `::test_cli_seeds_an_empty_database_once` | `SeedError: D02: expected one proposal changing ['extraction_solvent'] in critique 2, found 0`. 발생 위치는 `backend/app/seed/loader.py:135`(`find_decided_proposal`). C2 참조 |
| seed + eln | `app/eln/tests/test_ingest_units.py::test_default_rules_accept_every_seed_condition_block` | seed가 `load_seed_spec()` 반환형을 dict에서 `SeedSpec`으로 바꿨다(`app/seed/spec.py`). ELN 테스트는 `load_seed_spec()["experiments"]`를 쓴다 |
| memory + analysis | `app/memory/tests/test_diff.py::test_018_vs_024_conditions_results_and_qc_with_sources`, `::test_reverse_diff_marks_flags_resolved` | analysis가 추가한 info 등급 플래그 `loq_above_lowest_level`이 `qc_changes`에 `resolved`/`persisting`으로 섞여 들어간다. memory 테스트는 `test_diff.py:54`의 `not [... "resolved"]`와 `:59`의 `== {"resolved"}`를 단정한다 |
| memory + partner | `app/memory/tests/test_knowledge_graph.py::test_decision_status_and_tests_proposal_are_tracked` | 테스트가 `p.id == 3`(`:106`)을 "추출 시간 단일 변수 제안"으로 가정한다. partner 설계기는 다른 제안을 만들고, 그 제안은 `tests_proposal`로 매칭되지 않는다(§7-3) |
| 모든 쌍 | `tests/test_contract.py::test_committed_openapi_is_up_to_date` | 생성 파일 충돌. 재생성하면 해결된다 |

**프론트:** 병합된 `queries.ts`가 `tsc`에서 실패한다.

- `useExperimentDraft`가 두 번 선언된다(TS2451). ELN은 `(projectId, source, active)`로
  `/api/eln/projects/{project_id}/experiment-draft`를 호출하고, Partner는 `(proposalId)`로
  `/api/partner/proposals/{proposal_id}/experiment-draft`를 호출한다.
  `research-ai/ProposalCard.tsx:13`에서 TS2554·TS2339 오류가 연쇄로 난다.
- 헤더 import를 단순 합집합으로 합치면 `Schemas`·`api`·`unwrap`·`DecisionCreate`가 중복 import된다.
- scratch에서 Partner 훅을 `useProposalExperimentDraft`로 바꾸고 import를 정리하면 `tsc` 통과,
  vitest 10 files / 50 tests 통과.

### C2. seed lab 프로파일의 결정 이력이 Partner 규칙 엔진의 "파생 출력"에 결합되어 있다

- `seed/loader.py:124-138`의 `find_decided_proposal`은 critique가 만든 제안 중 **변경 키 집합이 같은
  제안이 정확히 1개**여야 결정을 적용한다.
- 제안은 원본이 아니라 엔진이 만드는 파생물이다. partner 브랜치 엔진으로 lab 7개 critique를 돌렸을 때
  history.json 결정 12개 중 매칭되는 것은 **3개(D01·D07·D10)뿐**이었다.
  - 실측 스크립트: `scratchpad/probe/item12.py`
  - 예: #011 critique는 제안 0개, #009는 `spike_stage` 대조군과 `factorial 2x2` 제안을 낸다.
- 결과: 규칙 엔진을 바꿀 때마다 시드가 깨진다. 실제로 partner 병합 즉시 lab 시드 전체가 로드되지 않는다.
- `xfail(strict=False)`(`tests/test_seed_lab.py:336-340`)이 이 setup 오류를 "XFAIL"로 표시한다.
  병합 상태 pytest 출력에서 실패가 가려지는 것을 확인했다:
  `XFAIL at setup of tests/test_seed_lab.py::test_critic_does_not_repeat_rejected_proposals`.

### C3. ELN 원본 무결성 결함: 잘리거나 변형된 업로드가 "불변 원본"으로 저장된다

`backend/app/eln/multipart.py`(ELN 브랜치)에 대해 직접 재현했다.

- 닫는 경계(`--XyZ--`)가 없는 잘린 본문을 받아들인다.
  `parse_multipart` 결과는 `b'injection_id,level\r\nC1,1\r\nC2,'`이고 오류가 없다.
- 바이너리 안의 단독 CR 뒤에 경계가 오면 거기서 잘린다. `b"bin\r--XyZ\rmore"`가 `b"bin"`이 된다.
  `email` 파서가 RFC 2046과 달리 bare CR/LF를 줄바꿈으로 취급하기 때문이다.
- `Content-Transfer-Encoding: base64` 파트를 디코딩해서 저장한다(`:70` `get_payload(decode=True)`).
  `YSxi`가 `a,b`로 저장되므로 송신 바이트와 저장 원본이 다르다.
- 원본은 수정·삭제가 금지(CLAUDE.md §1)라 잘못 들어온 원본은 고칠 수 없고 `supersedes`로만 대체된다.
  따라서 수집 단계의 결함은 일반 버그보다 무겁다.

### C4. ELN 검증 회귀: main이 400으로 거부하던 CSV를 201로 받고, 이후 analysis run이 500

- 같은 요청(헤더 `"injection_id, level_ng_ml, ..."`)을 직접 재현했다.
  main에서는 업로드가 400이다. ELN 브랜치에서는 업로드가 201이고, 이어서
  `POST /api/analysis/experiments/7/run`이 500이 된다.
- 원인: `csv_ingest.py:53,58`이 `skipinitialspace`와 컬럼명 strip으로 **검증은 정규화된 컬럼명**으로
  통과시킨다. 그런데 저장되는 `content`는 원문이고, analysis는 원문을 다시 파싱한다.

### C5. 근거 검증기가 부호를 무시한다 (Partner, Claude 모드 원칙 위반 위험)

- `partner/grounding.py:143,165`가 `abs()`로 비교한다.
  실제 변화가 −27.1%p인데 Claude가 "+27.1%p 증가"라고 써도 `ungrounded_numbers == []`로 통과한다.
- CLAUDE.md §1 "근거 없는 숫자면 규칙 모드 대체"의 취지(방향이 틀린 숫자 차단)를 우회한다.
  규칙 모드에서는 문제가 없고 Claude 모드에서만 위험하다.

---

## ③ 병합 시 주의할 충돌 지점

### 6. 같은 파일을 여러 브랜치가 수정한 지점

`git merge-tree`로 쌍별 실측했다.

| 파일 | 수정 브랜치 | 텍스트 충돌 쌍 | 해결 방법 |
|---|---|---|---|
| `CHANGES_REQUESTED.md` | 5개 전부 | 모든 쌍(10/10) | 합집합 후 §5 표대로 중복 정리 |
| `backend/openapi.json` | eln·memory·analysis·partner | 4개 브랜치 간 6쌍 전부 | 양쪽을 버리고 `python -m app.scripts.export_openapi`로 재생성 (CLAUDE.md §3) |
| `frontend/src/api/schema.d.ts` | 위와 같음 | 위와 같음 | `npm run gen:api`로 재생성 |
| `frontend/src/api/queries.ts` | eln·memory·analysis·partner | eln+analysis, eln+partner, analysis+partner (memory는 자기 섹션 끝에만 추가해 충돌 없음) | 헤더 import 수동 병합, `useExperimentDraft` 이름 변경 (C1) |
| `TASKS.md` | 4개(seed 제외) | 없음(자동 병합) | 상태 표시만 확인 |
| `ARCHITECTURE.md` | memory·partner | 없음 | 내용 정합성 검토 필요(아래) |
| `backend/app/main.py` | memory만 | 없음 | 소유권 판단 필요 (§9) |
| `backend/tests/test_contract.py` | memory만 | 없음 | ELN도 `file_id` 파라미터 추가를 요청함(CR) |
| `backend/tests/{conftest.py, test_principles.py, test_seed.py}` | seed만 | 없음 | — |

`queries.ts`의 세부 충돌:

- **헤더(import·type alias)는 셋 다 수정했다.** "자기 섹션 끝에 훅 추가"(CLAUDE.md §3) 예외를 벗어난다.
  - ELN: `import type { Schemas }`와 alias 4개(`:7-13`).
  - Analysis: `import type { Schemas }`와 `CriteriaCreate`(`:7-10`).
  - Partner: 기존 `import { api, unwrap }` 줄을 `import { ApiError, api, unwrap, type Schemas }`로 **교체**하고
    `useState` import와 alias 3개를 추가(`:6-12`).
- **Analysis가 기존 공유 훅 `useCriteria`를 변경했다**(`:123-132`).
  인자 `projectId?`가 추가됐고, queryKey가 `["analysis","criteria",projectId??null]`로 바뀌었고,
  `staleTime: Infinity`가 제거됐다.
  Overview(`features/overview/OverviewPage.tsx:15`)는 여전히 인자 없이 호출해 기본 기준만 보여준다.
- **Partner가 SSE 파서 `parseSseBuffer`·`streamAsk`와 React state를 공유 API 파일에 넣었다.**
  위치는 `useAsk` 뒤, `useConditionFields` 앞(`:252-423`)이다.
- **ELN이 요청한 `useRunAnalysis`는 analysis 브랜치가 이미 추가했다.** 중복 요청이다.

### 7. 서로 가정이 어긋나는 지점

1. **memory diff 응답 ↔ partner 입력: 양립한다.**
   - partner는 `memory.service.diff()`의 `condition_changes[].key/.label/.value_a/.value_b`만 읽는다
     (`partner/context.py:184,188`, `engines/designer.py:69`).
   - memory는 이 필드를 유지하고 `sources`·`segments`·`result_changes`·`qc_changes`·`results_available`만
     **추가**했다(`memory/schemas.py:95-115`).
   - 다만 중복 계산이 있다. memory diff 내부에서 포트로 `analysis.compare`를 부르고,
     partner context도 `analysis.compare`를 별도로 부른다(`context.py:92-93`).
2. **analysis 결과 스키마 ↔ 소비자: 필드 제거·이름변경 없음.**
   - analysis 에이전트가 diff의 `-` 줄 전수로 확인했고, partner가 읽는 필드 목록과 대조했다.
   - partner가 읽는 `ExperimentMetrics.recovery_mean_pct/recovery_rsd_pct/is_injections_*/min_r_squared/max_abs_back_calc_error_pct/flags[]`
     와 `MetricsComparison.recovery_delta_pct_points/recovery_t_test.p_value/per_analyte[].delta_pct_points`는 모두 존재한다.
   - ELN CompareModal이 읽는 필드도 모두 존재한다.
   - 그러나 **의미** 차이가 있다.
     - `TrendPoint.flag_count`와 memory `qc_changes`에 새 info 플래그(`loq_above_lowest_level`, `uncertainty_high`, `outlier_suspected`)가
       섞여 들어간다. memory 테스트 2개가 실패하는 원인이다.
     - ELN `CompareModal.tsx`는 `flags.length`를 "QC 플래그" 수로 표시해서 info 플래그까지 센다.
   - `ResultKind`(`limits`, `ion_ratio` 추가)·`FlagCode`(4종 추가) 유니온 확장은 병합 상태 `tsc`에서 문제가 없었다.
3. **Partner 제안 형태 ↔ memory `tests_proposal` 매칭: 사실상 동작하지 않는다.**
   - `memory/conditions.py:164-184`는 제안 `changes`의 **모든 키가 자식 실험 조건 블록에 같은 값으로**
     있어야 연결한다.
   - partner 설계기는 `design: "factorial 2x2"`, `factor_<key>: "a | b"`,
     `calibration_type: "solvent + matrix-matched"` 같은 키·값을 낸다(실측, §12).
     이런 값은 조건 블록에 존재할 수 없으므로 MEM-1 `tests_proposal` 엣지가 거의 생기지 않는다.
4. **`calibration_type` 값 도메인이 세 모듈에서 다르다.**

   | 모듈 | 값 도메인 / 처리 |
   |---|---|
   | Analysis | `solvent \| matrix-matched`만 인식하고, 그 외 값은 조용히 `solvent`로 처리(`analysis/service.py:264-268`). CR은 `Literal["solvent","matrix-matched"]` |
   | Partner | `"standard-addition"`도 매트릭스 보정으로 간주(`partner/knowledge.py:66-68`). CR은 `Literal[..., "standard-addition"]`. 제안 값으로 `"standard-addition"`, `"solvent + matrix-matched"`를 낸다 |
   | ELN | 아직 extra 키 |

   결과:
   - PAR-2 초안으로 `calibration_type=standard-addition` 실험을 만들면 Analysis는 용매 곡선으로 계산하고,
     Partner는 "매트릭스 보정됨"으로 판정한다.
   - ELN이 Analysis 안대로 Literal 필드를 만들면 Partner 초안이 400으로 거부된다.
5. **ELN이 memory 협의 대상 컴포넌트를 삭제했다.**
   - ELN이 `features/notebook/ExperimentDiffView.tsx`를 삭제하고 `CompareModal`로 대체했다.
     CompareModal은 결과 차이를 `analysis.compare`로 그린다.
   - memory CR "ExperimentDiffView에 `result_changes`·`qc_changes`·`segments` 표시"의 대상 파일이 이제 없다.
   - 결과 차이를 그리는 경로가 둘이 됐다: memory `result_changes`와 analysis `compare`.
   - CLAUDE.md §3은 "Notebook 탭의 diff/정리본 컴포넌트는 Notebook 담당과 협의"를 요구하는데,
     ELN 쪽에 협의 기록(CR)이 없다.
6. **ELN·Partner 모두 "실험 초안" 기능을 만들었다.**
   - ELN `/api/eln/projects/{id}/experiment-draft`(복제·프로토콜)과
     Partner `/api/partner/proposals/{id}/experiment-draft`(PAR-2).
   - Partner CR은 "ELN-8 폼이 partner 초안을 초기값으로 쓸 수 있다"고 하지만,
     ELN `ExperimentComposer`에는 제안 ID를 받는 경로가 없다.

### 8. seed-expansion이 다른 모듈 테스트를 깨뜨릴 가능성

- **reference 프로파일(기본값) 기준:**
  - eln과는 1개 깨진다(`test_default_rules_accept_every_seed_condition_block`, API 형 변경).
  - memory·analysis와는 깨지는 것이 없다(seed+memory, seed+analysis 단독 병합 pytest 전부 통과).
  - partner와는 seed 자기 테스트(lab) 전부가 깨진다.
- **lab을 기본값으로 바꾸면** 대량으로 깨진다. 목록은 §11.

---

## ④ E 세션이 반드시 해결해야 할 항목

### 9. 공유 파일 수정 브랜치와 양립성 판정

| 공유 파일 | 수정 브랜치 | 내용 | 판정 |
|---|---|---|---|
| `backend/app/core/**` | 없음 | — | 아무도 수정하지 않았다. 대신 `stream_text`(partner)·`seed_profile`(seed)·Alembic(전원)·wiring 소유권(memory)이 CR로 쌓였다 |
| `backend/pyproject.toml` | 없음 | — | python-multipart가 미선언이다. 현재 venv에는 `mcp` 패키지의 의존성으로 우연히 설치되어 있다(`pip show`: Required-by: mcp) |
| `backend/app/main.py` | memory | `from app.wiring import install as install_memory_fact_providers`(:22) + 호출(:56) | **규칙 위반.** "자기 라우터/모델 등록 한 줄"이 아니라 타 모듈 결선이다. 다른 브랜치와 텍스트 충돌은 없다 |
| `backend/app/wiring.py`(신규) | memory | analysis·partner 서비스를 memory 포트(`ResultFact`·`QCFact`·`ProposalFact`)에 연결하는 composition root(354줄) | **기술적으로는 양립하지만 소유권이 미확정이다.** `test_architecture.py`가 이 파일을 검사하지 않아 의존 방향 규칙의 사각지대가 된다. memory 테스트도 `app.partner.service`·`app.wiring`을 import한다(`memory/tests/conftest.py:14`, `test_knowledge_graph.py:15-16`) |
| `frontend/src/api/queries.ts` | eln·memory·analysis·partner | §6 | **양립 가능하지만 수동 해결이 필요하다.** 헤더 병합과 `useExperimentDraft` 이름 변경. 병합 후 `tsc` 통과를 확인했다 |
| `backend/tests/test_contract.py` | memory | PATH/QUERY 파라미터 3개 추가 | 양립한다(추가만) |
| `backend/tests/{conftest,test_principles,test_seed*}.py` | seed | lab fixture 신설, `load_seed_spec("reference")`로 변경 | 양립한다. 단 `test_principles.py:58-61`이 reference에 고정된다 |
| `backend/app/seed/**` | seed | 데이터 분리, 로더 재작성 | 공유 영역이다(CLAUDE.md §3 목록). 다른 브랜치는 수정하지 않았다 |
| `ARCHITECTURE.md` | memory·partner | 각자 API 표·원칙 문단 추가 | 텍스트 충돌은 없지만 공유 문서 직접 수정이다(규칙상 CR 대상) |

**E가 결정·수행할 것 (필수):**

1. **생성 파일 재생성.** `openapi.json`과 `schema.d.ts`는 양쪽을 버리고 재생성한다.
2. **`queries.ts` 병합.**
   - 헤더 import를 하나로 정리한다.
   - Partner 훅을 `useProposalExperimentDraft`로 바꾸거나 ELN 훅을 `useElnExperimentDraft`로 바꾼다.
     호출부는 `ProposalCard.tsx:2,13`이다.
3. **`app/wiring.py`·`main.py` 소유권 결정.**
   - 권고: core 소유 composition root로 승인하고, `test_architecture.py`에 "wiring은 서비스·스키마만
     import" 규칙을 추가한다.
   - 거부하면 memory의 MEM-1(`tests_proposal`)·diff `result_changes`·knowledge graph가 동작하지 않는다.
4. **병합 상태 실패 테스트 6개 수정.** 원인은 §C1.
   - `test_ingest_units`: `SeedSpec` API에 맞춘다.
   - memory `test_diff` 2개: info 등급을 제외할지 정책을 결정한다. 권고는 memory `qc_changes`에서
     `severity=="info"`를 별도 분류하는 것이다.
   - memory `test_knowledge_graph`: 하드코딩된 `p.id==3`을 제거한다.
5. **ELN 결함 C3·C4는 병합 전 ELN 세션이 수정한다.**
   - 최소 조치: 닫는 경계가 없으면 400, CTE가 있으면 400, 헤더 공백은 main처럼 400.
   - 255자를 넘는 파일명이 500이 되는 문제(`service.py:887`)도 400으로 바꾼다.
6. **seed lab 결정 이력 재설계.** C2 참조. 완료 전에는 seed를 병합하지 않거나,
   reference 부분만 병합하고 lab 테스트를 분리한다.
   - xfail은 `strict=True`로 바꾼다.

### 10. eln·memory·analysis·partner의 DB 스키마 변경 동시 적용

변경 목록(전부 `models.py`에서 직접 확인·집계):

| 모듈 | 신규 테이블 | 기존 테이블 변경 |
|---|---|---|
| eln | `eln_experiment_revisions`(uq experiment_id+revision), `eln_experiment_addenda`, `eln_attachment_files`(sha256 index), `eln_condition_templates`(uq project_id+version), `eln_protocol_templates`(uq project_id+name+version) | `eln_experiments`에 `cloned_from_experiment_id`(self FK), `protocol_template_id`(FK 없음) 추가. `eln_datasets`에 `schema_version`, `source_encoding`, `supersedes_dataset_id`(self FK), `source_attachment_id`(FK → eln_attachment_files) 추가 |
| memory | `memory_knowledge_notes`(FK eln_projects), `memory_index_state`(가변, 비-Immutable), FTS5 가상 테이블 `memory_search_fts`(+shadow 5개, **metadata 밖, 첫 검색 시 지연 생성**) | `memory_digests`에 `fallback_reason`, `input_fingerprint` 추가 |
| analysis | `analysis_criteria_versions`(uq project_id+version, FK eln_projects) | 없음 |
| partner | `partner_hypothesis_transitions`, `partner_exchanges` | `partner_critiques`에 `project_id`(NOT NULL FK), `scope`, `assessments`, `decision_feedback`, `reused_proposal_ids`, `context_fingerprint` 추가, **`experiment_id`가 nullable로 변경**. `partner_proposals`에 `design`, `base_experiment_id`(FK), `priority`, `priority_factors`, `signature`(index), `supersedes_proposal_ids` 추가 |

**판정:**

- **서로 충돌 없음.**
  - 테이블 이름이 겹치지 않고 모두 `<module>_<entity>` 규칙을 따른다.
  - 모듈 간 FK는 전부 `eln_projects`/`eln_experiments` 방향이라 의존 방향(eln ← 나머지)과 일치한다.
  - eln+memory+analysis+partner 병합 상태에서 `create_all`로 만든 빈 in-memory DB로 테스트 269개가 통과했다.
    실패한 4개(§C1의 memory 3개와 openapi 계약 1개)는 스키마와 무관하다.
- **이번 병합에는 재시드로 충분하다.**
  - `core/db.py:52-56`은 `create_all`만 한다. 기존 `biopilot.db`(`core/config.py:23` 기본값)에는
    새 컬럼이 추가되지 않아 런타임 오류가 난다.
  - 지금 DB에 들어 있는 데이터는 전부 시드이므로 `biopilot.db` 삭제 → 자동 시드로 해결된다.
  - 함께 정리할 것:
    - `memory_index_state` 워터마크와 FTS 테이블은 DB 파일과 함께 사라지므로 문제없다.
    - ELN 블롭 저장소 `./eln_storage`(`eln/storage.py:22`, 환경변수 `BIOPILOT_ELN_STORAGE_DIR`)는 DB 밖에 있다.
      sha256 주소라 고아 블롭이 남아도 무해하지만, 같이 비우는 절차를 문서화해야 한다.
- **Alembic은 병합의 차단 조건은 아니지만 다음 스키마 변경 전에 필수다.**
  - 원본 불변 원칙상 연구자가 입력한 원본은 재시드로 복원할 수 없다. 실제 기록이 쌓이는 시점부터는
    "DB 삭제" 전략이 원칙 위반이 된다.
  - SQLite에서 `partner_critiques.experiment_id` NOT NULL→NULL 변경은 테이블 재생성이 필요하다
    (`render_as_batch=True`).
  - FTS5 가상 테이블은 metadata 밖이라 autogenerate 대상이 아니다. revision에서 `op.execute`로
    다루거나 지금처럼 지연 생성을 유지한다.
  - 권고: 병합 직후 core가 **병합된 스키마를 baseline revision 하나로** 도입한다.
    세 CR(main 18행, ELN "기존 로컬 DB 재생성 필요", memory "마이그레이션 대상 추가")을 하나로 합친다.

### 11. reference vs lab 기본값

**판정: 기본값은 `reference`로 유지한다.** lab은 `Settings.seed_profile`(seed CR)로 선택하는 데모용 opt-in 프로파일로 둔다.

근거:

1. lab은 partner 브랜치와 병합하면 로드 자체가 불가능하다(C2, `seed/loader.py:135`). 기본값이 되면 앱 기동이 실패한다.
2. CLAUDE.md §6과 ARCHITECTURE §5의 시나리오 수치(#024 평균 회수율 58–66% 등)와 모든 모듈 테스트가
   reference 7개 실험을 전제한다.
3. 현재 seed 브랜치 안에서도 기본값이 엇갈린다.
   - 앱(`loader.py:54,80-82`, `seed()` 기본 `"reference"`)은 reference.
   - CLI(`seed/__main__.py:24`)는 **lab**.
   - CLI 기본값을 reference로 맞춰야 한다.
4. seed의 CR 완료 기준 "`BIOPILOT_SEED_PROFILE=lab pytest` 전체 통과"는 성립하지 않는다.
   환경변수는 `client` fixture(`seed_if_empty`)에만 적용되고, `seeded` fixture(`backend/conftest.py`의
   `seed(session)`)는 reference로 고정되어 있다.

**lab을 기본으로 바꾸려면 고쳐야 할 테스트**

측정 방법: 이 검토에서 `seed()` 기본값과 환경변수를 모두 lab으로 바꾸는 플러그인을 쓰고, 각 모듈
브랜치에 seed 코드를 덮어 실행했다. partner 브랜치는 lab 시드가 로드되지 않아 측정할 수 없었다.

- **ELN**
  - `app/eln/tests/test_eln_api.py`: `test_seeded_project_and_experiments`(프로젝트 1개 가정),
    `test_experiment_detail_and_datasets`(`/experiments/7`=#024 가정),
    `test_create_experiment_and_errors`(#025가 비어 있다고 가정).
  - `app/eln/tests/test_eln_workflows_api.py`: `test_seeded_experiment_history_and_audit`,
    `test_protocol_templates_versions_and_reuse`, `test_clone_draft_and_create`,
    `test_list_pagination_and_filters`.
  - `app/eln/tests/test_ingest_units.py`: `test_default_rules_accept_every_seed_condition_block`
    (reference에서도 실패한다).
- **Memory**
  - `app/memory/tests/test_memory_api.py`: `test_memory_endpoints`, `test_conditions_endpoints`,
    `test_knowledge_graph_recall_ask_similar`.
  - `app/memory/tests/test_memory_service.py`: `test_graph_lineage_timeline`.
    main 버전 기준으로는 `test_search`, `test_rules_digest_is_stored_and_audited`도 실패한다.
  - `app/memory/tests/test_conditions.py`: `test_similar_experiments_ranked_by_condition_vector`,
    `test_condition_history_shows_extraction_time_10_to_5`, `test_lineage_graph_mem1_edges`,
    `test_proposal_tests_matching`.
  - `app/memory/tests/test_digests_notes.py`: `test_rules_digest_stored_audited_and_fresh`.
  - `app/memory/tests/test_knowledge_graph.py`: `test_seed_graph_has_every_node_type_and_link`,
    `test_incremental_refresh_applies_only_new_events`, `test_rolled_back_events_trigger_rebuild`,
    `test_decision_status_and_tests_proposal_are_tracked`.
  - `app/memory/tests/test_search_recall.py`: `test_search_fields_and_and_semantics`,
    `test_recall_classifies_terms_and_bundles`, `test_recall_sample_facet_and_keyword_only`.
- **Analysis**
  - `app/analysis/tests/test_analysis_api.py`: `test_metrics_compare_trend_and_results`,
    `test_report_export_markdown_and_csv`(id 7 → "biopilot-024" 가정).
  - `app/analysis/tests/test_analysis_service.py`: `test_trend_covers_all_experiments`.
- **Partner**
  - main 시절부터 있던 테스트:
    - `app/partner/tests/test_partner_api.py`: `test_partner_endpoints`.
    - `app/partner/tests/test_partner_service.py`: `test_seeded_critique_records`,
      `test_decisions_accept_modify_reject`, `test_ask_routes_topics_to_evidence`("7건" 문구 가정).
    - `app/partner/tests/test_rules_engine.py`: `test_baseline_passes_and_023_confirms_weighting`
      (#018에 부모가 없다고 가정).
  - partner 브랜치의 신규 테스트는 lab 시드 로드 실패로 **측정 불가**다.
    - `test_designer.py` 11개, `test_critic.py` 5개, `test_partner_features.py` 12개,
      `test_claude_mode.py` 6개, `test_completion_flow.py` 1개가 모두 setup ERROR다.
    - 다수가 "#024 제안이 pending"을 전제하므로 lab의 D05~D07 결정과 충돌할 가능성이 높다.
- **공용 테스트**
  - `tests/test_contract.py::test_every_get_endpoint_returns_real_data`.
  - `tests/test_principles.py::test_ai_records_are_separate_from_originals`(seed가 reference에 고정함).

### 12. seed xfail ↔ partner "기각 제안 미반복": 실제로 어느 쪽이 맞는가

**결론: Partner 구현이 맞고, seed의 xfail 전제("Partner가 결정 이력을 보지 않는다")는 낡았다.**
다만 seed 테스트는 병합 상태에서 의미 있는 검증이 불가능하다. 코드 판독과 실측 결과를 함께 적는다.

**Partner의 동작(코드)**

- 동일성 키는 `proposal_signature(changes)`다(`partner/feedback.py:31-34`).
  `(key.lower(), str(value).lower())` 정렬쌍의 sha256이다.
- 범위는 **프로젝트 전체**다(`feedback.py:115-122`). 매 critique마다 로드된다(`context.py:189,527`).
- 규칙 모드:
  - 기각된 서명의 초안은 버리고 다음 템플릿을 낸다(`designer.py:405-450`, `supersedes_proposal_ids` 기록).
  - 사유 범주별로 다르게 처리한다(자원 / 과학적 / 우선순위; `feedback.py:98-112`).
- Claude 모드: 서명 일치만 검사하고, 일치하면 규칙 모드로 대체한다(`service.py:138-141`).
- 기존 테스트 `test_designer.py:80-104`는 강하다.
  #024 제안을 기각하고 → 재비판한 뒤 → 기각 서명이 없음, 대체 제안이 존재함(`supersedes==[pre.id]`),
  사유 원문이 `decision_feedback.note`에 인용됨을 함께 단정한다.

**lab 데이터로 실측** (스크립트: `scratchpad/probe/item12.py`, `item12b.py`)

- lab 시드에서 결정 적용만 건너뛰고 42개 실험·7개 critique를 partner 엔진으로 생성했다.
- 히스토리 D10(#OA09 기각)과 **같은 변경 키를 가진 partner 제안**
  (`calibration_type=matrix-matched, injection_dilution=researcher-defined`)을 D10의 실제 사유로 기각했다.
  이후 재비판한 결과:

| 재비판 대상 | 기각된 서명 재등장? | 비고 |
|---|---|---|
| organic_acids #OA09(동일 실험) | 아니오 | 대체안 `injection_dilution=series (researcher-defined)`. decision_feedback에 사유가 인용됨 |
| organic_acids #OA10(같은 프로젝트 후속) | 아니오 | |
| organic_acids #OA11, #OA12 | 아니오(제안 0) | |
| residue #024(다른 프로젝트) | **예** | 설계상 프로젝트 범위. 의도된 동작 |

- 추가로 D02·D08·D10·D11 각 critique의 첫 제안을 기각하고 프로브 실험을 재비판했다.
  기각 서명 재등장은 4/4 모두 0건이었다.

**seed 테스트가 이 판정을 내릴 수 없는 이유**

1. 병합 상태에서 lab 시드가 D02에서 `SeedError`로 실패한다. 프로브 테스트는 setup 단계에서 죽고,
   `strict=False` 때문에 XFAIL로 표시된다(실측 출력).
2. 프로브가 기대하는 기각 제안(예: D02 `extraction_solvent=메탄올`, D11 `extraction_solvent=메탄올:물`)은
   main 엔진의 출력이다. partner 엔진은 해당 실험에서 이것을 단일 변수 제안으로 내지 않는다.
   설령 로드에 성공해도 6개 중 4개 이상의 프로브는 **공허하게 통과**한다.
   D04 프로브(#011, #012)는 partner 엔진에서 제안이 0개다.
3. seed 데이터가 스스로 모순된다. D04(#011, 기각, 예산)와 같은 서명을 D07(#024, 같은 residue 프로젝트)이
   "modify"로 다시 결정한다. 같은 프로젝트에서 기각 제안이 재등장하는 것을 시나리오가 전제하는 셈이다.
   또한 로더는 모든 critique를 결정보다 먼저 실행한다(`loader.py:176-181`). 그래서 #024 critique(10월)가
   D04(7월)보다 먼저 저장된다.

**남는 Partner 쪽 한계** (병합 후 개선):

- 서명이 값 문자열 정확 일치라서 Claude가 값을 바꿔 말하면(paraphrase) 통과한다.
- 수용·"scientific" 기각이 프로젝트 전체에서 해당 대조군을 영구 억제한다.
- 사유 분류가 부분 문자열 키워드 기반이다(`knowledge.py:265-286`). 예: "배치"가 들어가면 시료 부담으로 분류된다.
- 실측 #OA09에서 "기기 일정" 사유로 기각했는데 대체안이 다시 재주입(dilution series)을 요구했다.
  사유가 **자원 제약으로 반영되지 않았다.**

### 13. ELN multipart 직접 파싱

**판정: python-multipart를 `pyproject.toml`에 명시하고 FastAPI `UploadFile`/`Form`으로 교체해야 한다.**
요청 형식(필드명 `file`, `kind`, `format`)은 그대로 유지할 수 있다.

재현으로 확인한 결함(`backend/app/eln/multipart.py`, ELN 브랜치):

| # | 결함 | 위치 | 영향 |
|---|---|---|---|
| 1 | 닫는 경계 없는 잘린 본문을 수용 | `:59-62` | **잘린 CSV가 불변 원본으로 저장된다**(C3) |
| 2 | bare CR/LF + 경계 문자열에서 파트가 분할됨 | `:59` (`email.BytesParser`) | 바이너리 첨부(ELN-4) 손상. `b"bin\r--XyZ\rmore"`가 `b"bin"`이 된다 |
| 3 | `Content-Transfer-Encoding` 디코딩 | `:70` | 저장 바이트 ≠ 송신 바이트. RFC 7578은 이 헤더를 폐기했다 |
| 4 | `"boundary="` 대소문자 구분 | `:55` | `Boundary=`가 400이 된다 |
| 5 | 본문 전체를 메모리에 버퍼링한 뒤 join·헤더 붙여 재파싱 | `:91-99` | ELN 에이전트 측정: 20 MB 업로드 시 최대 263 MB 사용 |
| 6 | 텍스트 필드 `errors="replace"` | `:81` | 잘못된 바이트가 조용히 치환됨 |
| 7 | 중복 필드는 마지막 값이 이기고, name 없는 파트는 조용히 버림 | `:67-69` | |
| 8 | 제어 흐름에 `assert` 사용 | `:63` | `python -O`로 실행하면 사라진다 |
| 9 | `async` 핸들러에서 동기 pandas/DB 작업 | router | 이벤트 루프가 블로킹된다 |

- 장점: 크기 제한을 스트리밍 중에 적용한다(`:89-98`). 따옴표 boundary, LF 전용, preamble, RFC 5987 `filename*`도 정상 동작했다.
- 교체할 때는 이 크기 제한 동작을 유지한다. Starlette `request.form(max_part_size=...)` 또는
  업로드 후 `UploadFile.size`를 검사한다.
- python-multipart는 현재 의존성 선언이 없다. 설치되어 있는 것은 우연이다(Required-by: mcp).

### 14. 모듈 간 미완 연결 분류

| 항목 | 현황(근거) | 분류 |
|---|---|---|
| Partner Claude 스트리밍(`stream_text`) | partner는 `StreamingGateway` 프로토콜(`partner/service.py:809-813`)을 `isinstance`로 감지한다(`:1143`). core `ClaudeGateway`에는 `generate`만 있다(`core/llm.py:53-104`). 그래서 Claude 모드는 블로킹 `ask()` 결과를 한 번에 보낸다. `start` 이벤트는 `engine_candidate:"claude"`라고 표시한다. 테스트 대역 `StreamingFake`(`test_stream_and_eval.py:28-43`)에만 메서드가 있다 | **E에서 해결 가능.** core에 `ClaudeGateway.stream_text`(Messages API 스트리밍)를 추가하고, FakeGateway 테스트와 "스트리밍 미지원 게이트웨이" 테스트를 붙인다. partner 쪽은 수정이 필요 없다 |
| Analysis "프로젝트별 QC 기준" 전환 | Partner가 여전히 `analysis.get_criteria()`(기본값)를 쓴다(`partner/context.py:185,525`). Overview는 `useCriteria()`(기본값)를 쓴다. Analysis 프론트 패널은 **현재 활성 기준**과 비교하므로(`RecoveryPanel.tsx:17-18,58,92`), 결과가 판정된 기준 버전과 어긋날 수 있다 | 일부만 E에서 가능 |
| ↳ Partner 두 곳을 `get_project_criteria(...).active`로 바꾸기 | 기계적 변경 | **E에서 가능** |
| ↳ "결과에 기록된 `criteria_version`으로 조회" API | 버전 라벨로 조회하는 서비스가 없다(analysis 에이전트 확인) | **별도 작업 (analysis)** |
| ↳ Overview | Frontend Shell 영역 | **별도 작업 (shell)** |
| ELN 새 실험 비교 모달의 결과 차이가 비어 있음 | `CompareModal`은 `analysis.compare`를 쓰는데, 이 함수는 **저장된** AnalysisResult만 읽는다. 새 실험은 run을 하지 않아 `metrics_b.analyzed=false`다. 모달은 "둘 다 미분석"(`CompareModal.tsx:141`)만 처리해서 전부 "—"가 된다. ELN은 의존 방향상 analysis를 호출할 수 없다 | **E에서 해결 가능.** `useRunAnalysis`는 analysis 브랜치에 이미 있다. Notebook에 "분석 실행" 버튼과 "현재 실험 미분석" 상태 표시를 추가한다(ELN 프론트 몇 줄) |
| memory `tests_proposal` ↔ partner 설계형 제안 | §7-3. factorial·결합값 제안은 매칭될 수 없다 | **별도 작업 (memory + partner 계약 합의).** 예: 제안에 `implementing_changes`(조건 블록 단위 변경 목록) 필드를 추가 |
| `calibration_type` 도메인 | §7-4 | **E에서 계약 결정.** 권고는 `solvent \| matrix-matched \| standard-addition`이며, analysis가 standard-addition을 미지원으로 플래그하게 한다. **구현은 별도 작업 (ELN 필드 + analysis 처리)** |
| ELN-5 시드 템플릿 | ELN은 기본 규칙만 있다(`eln/conditions.py:24-39`, version 0). 시드 저장은 seed 영역이다 | **별도 작업 (seed)** |
| ANA-8 ion_ratio | analysis는 `other` 데이터셋에서 읽는 임시 경로를 쓴다(`analysis/service.py:271-275`). ELN-7 `ion_ratio@1`은 구현됐다 | **E에서 가능.** 병합 후 analysis가 `kind=="ion_ratio"`를 바로 읽으므로 임시 경로를 제거하고 통합 테스트 1개를 추가한다 |
| Partner 결정 → Memory 검색 반영 | partner CR은 `create_knowledge_note(source_ref)`를 요청한다. 한편 memory wiring은 이미 partner 결정을 KG에 읽어 온다 | **별도 작업.** 두 경로 중 하나로 통일한다(wiring pull vs partner push) |
| Partner 결정의 actor/시점 | `decide()` actor가 `"user"`로 고정되어 있어 lab 시드 결정 24건이 user로 감사된다 | **별도 작업 (partner)**, seed 재설계와 함께 |
| memory → ExperimentDiffView 요청 | 대상 파일이 ELN에서 삭제됨(§7-5) | **E에서 CR을 재지정.** CompareModal에 memory `qc_changes`·`segments`를 표시하는 별도 작업으로 넘긴다 |

---

## ⑤ 병합 후로 미뤄도 되는 항목

- **Analysis**
  - LOD 기본 `k=3.0`(`analysis/schemas.py:61`)이 TASKS의 3.3σ/S와 다르다. ICH 3.3은 기준 설정 `lod_k`로만 가능하다.
  - Holm 보정 입력 `per_analyte[i].p_value or 1.0`(`analysis/service.py:879`)은 p=0.0(언더플로)을 1.0으로 바꾼다.
  - F-검정(ANA-5)은 "가중 필요"까지만 보여준다. #023에서는 Σ|%RE| 기준 1/x²(59.8)가 1/x(66.9)보다 낮다.
  - `methods.py:64,107,150`의 가정 설명 문장과 `CalibrationPanel.tsx:103`의 "이분산 → 가중 필요" 배지는
    해석에 가깝다(계산/해석 분리 경계선).
  - ANA-1 #023 테스트(`test_analysis_service.py:182-191`)는 방법만 단정하고 수치 범위는 단정하지 않는다.
  - 순환 단정이 하나 있다: `test_calculations.py:181-182`는 Σ|%RE| 기대값을 운영 코드 잔차에서 합산한다.
- **ELN**
  - ELN-3이 `eln_experiments.title/author`를 in-place로 수정한다(`eln/service.py:476-477`).
    ARCHITECTURE 정책상 허용이고 `ExperimentRevision` 행과 감사 기록이 있다.
    그러나 모델 docstring "Corrections never edit an original"(`models.py:3-4`)과 모순되고,
    revision 번호 `count+1`이 동시 PATCH에서 IntegrityError(500)를 낸다.
  - 첨부 다운로드 라우트가 `include_in_schema=False`(`router.py:511`)라 계약에서 빠져 있다.
  - 블롭을 트랜잭션 전에 쓰므로(`service.py:1043`) 롤백 시 고아 블롭이 남는다.
  - UI에 크기 제한 "5 MB/20 MB"가 하드코딩되어 있다(`DatasetUploadPanel.tsx:150` 외).
  - `CompareModal.tsx:163-164`의 `?? 0`은 값이 없을 때 0을 만들어 낸다.
- **Memory**
  - GET `/search`·`/recall`이 FTS DDL·쓰기를 하고 요청 커밋까지 한다(`memory/search_index.py:197-226`).
  - MEM-3에서 조건 **키 이름** 매칭이 사라졌고(main `service.py:233` 대비), 다중 단어 질의가 AND로 바뀌었다.
  - trigram 토크나이저는 SQLite ≥3.34가 필요한데 런타임 확인이 없다.
  - `grounding.py`가 partner의 검증기를 복제했고, `"1,000"`을 1.0으로 해석한다(`memory/grounding.py:14,21`).
  - 테스트에 시드 수치가 하드코딩되어 있다(`test_diff.py:46,52`, `test_knowledge_graph.py:41,106`; CLAUDE.md §6 위반).
  - main의 diff 테스트 단정(`relation`, `unchanged_keys`, `datasets.both`)이 삭제됐다.
- **Partner**
  - PAR-4 패널이 실험 필터 없이 프로젝트 전체 대화 이력을 보여준다(`PartnerPanel.tsx:20`).
  - `ctx.trend`를 조회만 하고 쓰지 않는다(`context.py:498`).
  - 증거 라벨에서 분석물명을 `split(" ")`로 역파싱한다(`critic.py:75-76,163`).
  - Partner 내부에 산술이 남아 있다.
    - `rules.py:387-390` 상대 개선율은 main부터 있던 것이고 임계 판단에만 쓴다.
    - `context.py:409`는 `min(g.n)`이다.
    - 표시되는 숫자가 아니므로 원칙 위반으로 보지는 않지만, analysis로 이전을 검토할 만하다.
- **Seed**
  - NaN 칸 처리 CR(analysis + eln).
  - 프로젝트 전환 UI(shell).
  - 조건 키 라벨 추가(eln).
- **공통**
  - `api/types.ts` 별칭 요청 3건(eln·memory·partner).
  - ARCHITECTURE 갱신 요청 3건(seed·eln·analysis). 그와 별개로 memory·partner는 직접 수정했다.
  - 인증/사용자 식별(main CR).

---

## 브랜치별 상세 (요구 1–5)

### ELN (`claude/loving-lamport-80sjhe`)

**1. TASKS**

| 항목 | 판정 | 근거 |
|---|---|---|
| ELN-1 | O | `router.py:349-379`. 인코딩 판별 UTF-8 → UTF-8-sig → CP949, NUL 거부(`csv_ingest.py:28-47`). 크기 제한(`multipart.py:85-99`, `service.py:766-770`). 400 테스트(`test_eln_workflows_api.py:209-236`). JSON·CP949 업로드 sha256 동일(`:184-206`) |
| ELN-2 | O | 불변 `ExperimentAddendum`, 감사(`service.py:504-527`), raw_note 불변 단정(`test_eln_workflows_api.py:176-178`) |
| ELN-3 | O | 전/후 값 감사 payload(`service.py:468-500`), 불변 필드 409(`:459-466`), 테스트(`:426-443`) |
| ELN-4 | O | `<root>/<sha[:2]>/<sha>`(`storage.py:30-45`), 디스크 블롭 1개로 중복 제거, DELETE 405(`:369-400`). DB unique 제약은 없다 |
| ELN-5 | △ | 오류 400 / 경고 `warnings[]`는 구현·테스트됨(`:69-142`). **시드 프로젝트 템플릿이 없다**(기본 규칙 fallback, `conditions.py:24-39`) |
| ELN-6 | O | 응답 형태 유지, `X-Total-Count` 헤더, 경계 테스트(`:559-578`). `le=500` 경계는 미검증 |
| ELN-7 | O | `DATASET_KIND_REGISTRY`, `ion_ratio@1`, 하위호환 테스트(`test_ingest_units.py:101`), Analysis 공지 CR |
| ELN-8 | O | 컴포넌트 테스트(`ExperimentComposer.test.tsx:68-141`). 이 검토에서 vitest 19개 통과를 확인 |
| ELN-9 | O | 벤더 샘플 2종(`test_ingest_units.py:124-171`), 원본을 첨부로 보관하고 바이트 일치 단정(`test_eln_workflows_api.py:349-350`) |

**2. 원칙**

- `app/eln`에 raw SQL·UPDATE·DELETE가 없다. 신규 모델은 모두 `ImmutableMixin("*")`이다.
- 쓰기 8경로 모두 `record_event`를 호출한다. 위치는 `service.py`의 116, 180, 434, 487, 518, 666, 855, 1063.
- 위반: 없음. 회귀는 C3·C4 참조.

**3. 테스트:** 강하다. 오류 코드, 감사 payload, sha256, 디스크 블롭 수, 변조 → 400을 단정한다.
빈틈은 multipart 경계 사례, 긴 파일명, 동시 revision이다.

**4. 경계**

- `queries.ts` 헤더 수정(경미).
- Memory 협의 대상인 `ExperimentDiffView.tsx`를 삭제했다(협의 CR 없음).
- 타 모듈 import 없음. `main.py`·`models_registry.py`는 수정하지 않았다.

**5. CR(10건):**

- 필요: python-multipart, `test_contract`의 `file_id`, seed 템플릿, analysis `ion_ratio` 공지, docs, Alembic 보충.
- 중복: `useRunAnalysis`(analysis가 이미 구현함).
- 선택: `pytest-cov`(TASKS에 근거 없음), memory addenda 검색.

**검증:** ruff·format·mypy·openapi check 통과, pytest 113 통과, tsc·vitest(19)·check:api 통과.

### Memory (`feature/memory`)

**1. TASKS**

| 항목 | 판정 | 근거 |
|---|---|---|
| MEM-1 | O | `GraphRelation`에 기존 `derived_from` 유지(`schemas.py:160`), 유사도 단위 테스트(`test_conditions.py:17-29`). 다만 partner 병합 후 `tests_proposal`은 사실상 동작하지 않는다(§7-3) |
| MEM-2 | O | `[10.0]*6+[5.0]`, 없는 키는 `[]`(`test_conditions.py:48-57`) |
| MEM-3 | △ | 실제 FTS5 trigram(`search_index.py:33-38`)과 bm25(`:244`)를 쓴다. 한국어 부분일치 테스트 있음. 기존 `/search` **동작**이 바뀌었다(키 이름 매칭 제거, AND 의미, 기본 limit 50) |
| MEM-4 | O | "10분"→"5분" 단어 segment 단정(`test_diff.py:108-113`) |
| MEM-5 | O | 7개 실험 매트릭스와 `varying_only`(`test_conditions.py:60-79`) |
| MEM-6 | O | FakeGateway로 거짓 숫자를 주입하면 `fallback_reason == "ungrounded_numbers: 97.5, 77"`(`test_digests_notes.py:37-52`) |
| MEM-7 | O | 불변(`models.py:32`), 감사(`service.py:967`), 연결 실험 존재·동일 프로젝트 검증(`:952-959`), 검색 포함 |
| MEM-8 | O | 데이터셋 추가 후 stale(`test_digests_notes.py:63-75`) |

**2. 원칙**

- 원본에 대한 raw SQL은 없다. raw SQL은 파생 FTS 인덱스(`search_index.py:214-222`)에만 쓰므로 허용 범위로 판단한다.
- `memory_index_state`는 가변 테이블이고 감사 대상이 아니다. 파생 데이터라 허용 범위다.
- 정리본과 지식노트 쓰기는 감사된다.
- 유사도·recall 점수는 분석 수치가 아니라 검색 랭킹이므로 허용으로 판단한다.

**3. 테스트:** 대체로 실동작을 검증한다(롤백 후 재구성, FTS와 Python 결과 동치).
약점: 시드 수치 하드코딩, `test_memory_api.py:23`의 search는 `score` 키 존재만 확인, main diff 단정 삭제.

**4. 경계: 위반이 가장 많다.**

- `main.py` 수정, `app/wiring.py` 신설, `tests/test_contract.py`·`ARCHITECTURE.md` 직접 수정.
- Frontend Shell 영역(`features/overview/**`: GlobalSearchBar, KnowledgeGraphView, graphLayout, highlight, OverviewPage) 수정.
- 커밋 086abc9가 여러 모듈을 섞었다. 1커밋 1모듈 규칙 위반이다.
- `memory/service.py`·`ports.py`는 eln·core만 import한다. 역방향 import는 없고 `test_architecture.py`도 변경 없이 통과한다.

**5. CR(9건):**

- wiring 사후 승인 요청과 `[DONE] test_contract` 자기 승인은 규칙상 순서가 뒤바뀌었다.
- Notebook diff 표시 요청은 대상 파일이 삭제되어 재지정이 필요하다.
- types.ts 요청은 ELN·Partner 요청과 중복이다.

**검증:** 정적 검사 전부 통과, pytest 112, tsc·vitest(17)·check:api 통과.

### Analysis (`feature/analysis`)

**1. TASKS**

| 항목 | 판정 | 근거 |
|---|---|---|
| ANA-1 | O(편차) | σ 방식 3종(`calculations.py:363-423`), `limits@1`(`methods.py:17`). 기본 k=3.0(3.3 아님) |
| ANA-2 | O | 곡선 선택(`calculations.py:255-271`), fingerprint 포함(`service.py:641,659`), 테스트(`test_analysis_service.py:265-284`) |
| ANA-3 | O | 플래그만 붙이고 행은 유지(`service.py:455-479`, `outlier_suspected`), 알려진 이상치 테스트(`test_calculations.py:265-275`) |
| ANA-4 | O | docstring 수식(`calculations.py:553-559`), `ExperimentMetrics.expanded_uncertainty_pct`(`schemas.py:471`) |
| ANA-5 | O(한계) | F-검정(`calculations.py:298-329`), #023 테스트. 1/x와 1/x²는 구분하지 못한다 |
| ANA-6 | O | 불변 `analysis_criteria_versions`(`models.py:36-53`), 감사(`service.py:155`), 플래그에 `criteria_version` 기록. 기존 결과 불변·재분석 시 신규 결과 생성 테스트(`test_analysis_service.py:213-237`) |
| ANA-7 | O | Welch + Holm(`service.py:856-882`). 시드 결과 5개 분석물 모두 유의. 테스트는 `>=`라 통과 |
| ANA-8 | △ | ±30% 플래그 구현. ELN-7 미병합 상태라 `other` 경유 임시 경로 |
| ANA-9 | O | 잔차 플롯(`CalibrationPanel.tsx:127-153`), rows 필터(`RecoveryPanel.tsx:27-33,107-130`) |

**2. 원칙**

- `AnalysisResult`와 `AnalysisCriteriaVersion`은 `ImmutableMixin`이다. 쓰기 2경로 모두 감사된다(`service.py:155,248`).
- `report.py`는 포맷만 한다.
- 프론트에 산술이 없다(fixtures는 테스트 전용).
- 프론트가 임계값 비교를 한다(`RecoveryPanel.tsx`). main에 있던 동작을 확장한 것이다.

**3. 손계산 대조 테스트: 진짜다.**

- analysis 에이전트가 독립 스크립트(정확 분수와 scipy)로 재계산했다.
  OLS/WLS, F(=100, F_crit 99, p=1/101), LOD/LOQ, Grubbs 임계값(양측 α/(2n), 공개표 값과 일치),
  G=1.78329, 불확도, Welch, Holm `[0.03,0.06,0.06]` 등 **모든 리터럴이 일치**했다.
- 허용오차는 abs 1e-4~1e-12로 엄격하다.
- Grubbs는 단측이면 n=5에서 1.671이 되므로 이 테스트는 단측 구현을 판별해 낸다.
- 순환은 `test_calculations.py:181-182` 한 곳뿐이다.

**4. 경계:** `queries.ts` 헤더 수정과 기존 `useCriteria` 수정 외에는 없다. 커밋도 모듈별로 분리되어 있다.
`METHOD_VERSIONS`를 올렸다(calibration@3, recovery@2, is_response@2, matrix_effect@2, limits@1, ion_ratio@1).

**5. CR(4건)**

- `calibration_type` 필드 요청은 partner 요청과 도메인이 상충한다(§7-4).
- `ion_ratio` 계약 요청은 ELN이 이미 이행했다.
- partner에 대한 프로젝트 기준 요청(§14)이 있다.
- docs 요청이 있다.

**검증:** 정적 검사 통과, pytest 116, tsc·vitest(22)·check:api 통과.

### Partner (`feature/partner`)

**1. TASKS**

| 항목 | 판정 | 근거 |
|---|---|---|
| PAR-1 | O | 전이표(`service.py:502-507`), 400(`test_partner_features.py:102`), 전/후 감사(`:529-555`) |
| PAR-2 | O | modifications 우선(`service.py:735-739`), 저장하지 않음(실험 수 7 유지 단정, `test_partner_features.py:124-138`) |
| PAR-3 | O | 키 없으면 skip(`scripts/eval_partner.py:134-145`), JSON 리포트(`:155-165`) |
| PAR-4 | △ | 불변 `PartnerExchange`와 감사는 있다. 패널이 실험별이 아니다 |
| PAR-5 | O | 표 기반(`knowledge.py:59,66`), 규칙별 테스트(`test_table_rules.py`). pH 테스트에는 `ungrounded_numbers` 단정이 없다 |
| PAR-6 | O | 엣지 케이스 30개 이상(`test_grounding.py`). 부호 무시 결함은 C5 |
| PAR-7 | O | 동일 `CritiqueDraft`(`service.py:395-416`), 테스트(`test_partner_features.py:253-283`) |
| PAR-8 | O | 정수 가중합(`priority.py:74-84`). Evidence 값을 쓰지 않는다. #024 정렬 테스트(`test_designer.py:60-77`) |
| PAR-9 | △ | SSE 엔드포인트는 있다. Claude 토큰 스트리밍은 실제로 일어나지 않는다(§14) |

**2. 원칙**

- 상태 변경은 `Hypothesis.status`(`service.py:539`)와 `Proposal.status`(`:650`) 두 곳뿐이고, 둘 다 이력 행과 감사를 남긴다.
- 신규 Proposal 컬럼은 `__immutable_fields__`에 포함되어 있다(`models.py:91-96`).
- 프론트 research-ai·partner-panel에 산술이나 하드코딩된 수치가 없다.

**3. 기각 사유 반영 테스트: 진짜다.**

- `test_designer.py:80-178`과 `test_completion_flow.py:42-61`이 기각 → 재비판 → 부재·대체·사유 인용을 모두 단정한다.
- 빈틈:
  - 다른 실험·자식 실험으로 넘어가는 경우의 테스트가 없다.
  - Claude가 값을 바꿔 말하는(paraphrase) 우회 테스트가 없다.
  - lab 데이터 실측은 §12에서 보완했다.

**4. 경계**

- `queries.ts` 헤더 교체와 SSE·React state 추가는 경미한 위반이다.
- `ARCHITECTURE.md`를 직접 수정했다.
- import는 `app.<module>.service/schemas`만 쓴다(`context.py:19-33` 등).
- `scripts/eval_partner.py:146`이 `app.seed.loader`를 지연 import한다. `test_architecture.py`의 검사 사각지대다.
- 계약 변경: `CritiqueOut.experiment_id`가 nullable이 됐다. 필수 필드가 추가됐다. 제거된 필드는 없다.

**5. CR(6건)**

- core `stream_text`.
- memory `source_ref` 노트.
- analysis `spike_recovery`, `by_is_flag`·factorial(규모가 크다).
- eln 조건 필드 3개(analysis 요청과 상충).
- types.ts.

**검증:** 정적 검사 통과, pytest 157, tsc·vitest(16)·check:api 통과.

### Seed-expansion (`feature/seed-expansion`)

**1. TASKS:** 해당 모듈 항목이 없다. 목표는 lab 프로파일(2개 프로젝트, 42개 실험, 결정 12건)이고 구현은 되어 있다.
reference 프로파일은 main과 동일하다(CSV 12개 `cmp` 일치, `_reference_slice`의 필드별 비교 일치).

**2. 원칙**

- 모든 쓰기가 서비스를 거친다. main의 `from app.eln.models import Project`를 `eln.list_projects`로 바꾼 것은 개선이다.
- CSV는 고정 시드(`generate.py:47`, `SEED=20261103`)로 재현되고 전 파일 일치 테스트가 있다.
- 위반: 결정 24건의 감사 actor가 `user`이고 타임스탬프가 오늘 날짜다(partner `decide()` 고정값). "시드는 actor=seed" 일관성이 깨진다.

**3. 테스트**

- 범위 단정을 대체로 준수한다.
- xfail 1건(`test_seed_lab.py:336-340`, `strict=False`)은 setup 오류를 가린다.
- `test_rejected_changes_are_never_applied_later`는 플레이스홀더 값 `researcher-defined`에 대해 자명하게 참이다.

**4. 경계**

- 수정 범위는 `app/seed/**`, `backend/tests/*`, CR이다. 다른 모듈과 core는 건드리지 않았다.
- 공개 API `load_seed_spec()`의 반환형을 바꿔 ELN 테스트를 깨뜨렸다.

**5. CR(9건)**

- `Settings.seed_profile`, `decide(actor=, decided_on=)`, NaN 처리, 조건 라벨, 프로젝트 전환, docs, memory 정답 데이터.
- "기각 제안 반복 금지"는 **partner가 이미 구현했다**(§12). seed 쪽 재설계가 필요하다.
- "타 모듈 테스트 하드코딩 제거"는 완료 기준이 잘못되어 있다(§11-4).

### 5. CHANGES_REQUESTED 중복·상충 정리 (병합 시 합칠 것)

| 주제 | 출처 | 정리 |
|---|---|---|
| Alembic | main, eln("기존 로컬 DB 재생성"), memory("마이그레이션 대상 추가") | **1건으로 병합**(§10) |
| `api/types.ts` 별칭 | eln, memory, partner | **1건으로 병합**(shell) |
| ARCHITECTURE 갱신 | seed, eln, analysis + memory·partner 직접 수정분 | **1건으로 병합.** 직접 수정분과 정합성 확인 |
| ConditionBlock 필드 | analysis(`calibration_type` 2값), partner(`calibration_type` 3값 + `spike_stage` + `is_addition_stage`), seed(`mobile_phase` 등 라벨) | **상충.** E가 도메인을 결정한 뒤 ELN 1건으로(§7-4) |
| `useRunAnalysis` | eln → analysis | **이미 완료**(analysis `queries.ts`) |
| `ion_ratio` 계약 | eln(공지), analysis(요청) | **양방향 충족.** 병합 후 임시 경로 제거 |
| 기각 제안 반복 금지 | seed → partner | **partner 구현 완료.** 남은 일은 seed 재설계(C2) |
| 결정 → Memory | partner(push, `source_ref`), memory(wiring pull) | **상충.** 하나로 통일 |
| `test_contract.py` 파라미터 | memory([DONE] 자기 승인), eln(`file_id` 요청) | 공유 파일이므로 E가 일괄 처리 |
| ExperimentDiffView 표시 | memory → notebook | **대상 파일이 삭제됨.** CompareModal로 재지정 |
| 시드 데이터 추가 | eln(템플릿), memory(지식노트), seed(정답 데이터 제공) | seed 1건으로 병합 |

---

## ⑥ 병합 순서 추천과 이유

**권고 순서: analysis → eln → memory → partner → (재작업 후) seed-expansion**
각 단계 뒤에 openapi·schema.d.ts를 재생성하고 전체 테스트를 돌린다.

1. **analysis 먼저.**
   - 가장 자기완결적이다(타 모듈 의존은 eln.service뿐). 출력 변경은 필드 추가뿐이다.
   - 다른 셋이 analysis 출력을 소비한다. memory diff, partner context, eln CompareModal.
   - 먼저 들어가야 뒤 브랜치가 새 플래그·기준에 맞춰 조정할 수 있다. 실제로 memory+analysis 쌍에서 memory 테스트 2개가 깨진다.
   - 단독 병합 시 충돌은 `queries.ts`·생성 파일뿐이다.
2. **eln 둘째.**
   - 다른 모듈은 eln에 의존하지만 eln은 아무것에도 의존하지 않는다.
   - `ion_ratio@1`이 들어오면 ANA-8 임시 경로를 정리할 수 있다.
   - analysis의 `useRunAnalysis`가 이미 있어 CompareModal 빈 결과 문제(§14)를 이 시점에 고칠 수 있다.
   - 조건: C3·C4 수정 완료.
   - `queries.ts`에서 analysis와 헤더 충돌이 나면 수동으로 해결한다.
3. **memory 셋째.**
   - wiring.py·main.py 소유권 결정이 선행 조건이다.
   - analysis 이후에 들어가야 `test_diff` 2개를 새 플래그 정책에 맞춰 한 번에 고칠 수 있다.
   - eln 이후에 들어가야 ExperimentDiffView 관련 CR을 CompareModal로 재지정할 수 있다.
4. **partner 넷째.**
   - eln·memory·analysis 서비스를 모두 소비하므로 마지막 모듈로 들어와야 연결을 한 번에 검증할 수 있다.
     대상은 diff·metrics·criteria·draft.
   - 이 시점에 할 일:
     - `useExperimentDraft` 이름 충돌 해결.
     - memory `test_knowledge_graph`의 `p.id==3` 수정.
     - 프로젝트별 기준 전환(2줄).
     - core `stream_text`(E).
   - 조건: C5(부호) 수정.
5. **seed-expansion 마지막.**
   - lab 결정 이력이 엔진 출력에 결합되어 있어(C2) partner 이후의 엔진을 기준으로 다시 만들어야 한다.
     결정 대상을 "변경 키 집합"이 아니라 partner의 안정 식별자(설계 템플릿 id + 서명)로 지정하거나,
     결정 적용 시점을 각 critique 직후로 옮긴다.
   - 병합 직전에 할 일:
     - `load_seed_spec` 호환(dict 접근 유지 또는 ELN 테스트 수정).
     - CLI 기본값을 reference로 변경.
     - xfail을 `strict=True`로 바꾸거나 제거.
     - 결정 actor(partner CR) 반영.
   - lab 재작업이 늦어지면 **reference 분리 부분만 먼저 병합**한다. 데이터 디렉터리 이동과 `SeedSpec`이며
     main과 바이트 동일함이 확인됐다. lab은 별도 PR로 미룬다.

이 순서의 핵심 이유: 의존 방향(eln ← memory/analysis ← partner)의 **소비자 쪽을 나중에** 넣는다.
그러면 깨지는 테스트가 항상 "방금 들어온 브랜치"의 책임이 되고, seed처럼 다른 모듈의 파생 출력에
결합된 데이터는 그 출력이 확정된 뒤에 맞춘다.
