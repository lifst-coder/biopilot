# PERFORMANCE — 1000 실험 규모: 측정 → 원인 → 수정 → 재측정 (2026-11-04)

이전 판(2026-11-03)은 측정과 원인만 기록했다. 이번 판은 그 원인을 고치고 같은 데이터로 다시 쟀다.
원칙: **기능·출력은 바꾸지 않는다**(전후 응답 동일을 테스트로 증명), **캐시로 덮지 않고 원인을 고친다**
(인덱스 추가 → 쿼리 일괄화 → 불필요한 비교 제거 순), **수정마다 전후 측정값을 남긴다.**

## 요약

목표: 실험 1000개 기준 모든 조회 2초 이내. 같은 호스트, 같은 데이터베이스 파일, 5회 중앙값(색인 재구축은 2회).

| 구간 | 측정 | 수정 전 ms | 수정 후 ms (최대) | 배율 | 2초 |
|---|---|---:|---:|---:|---|
| 그래프 | `GET …/graph` (derived_from) | 753 | 99 (186) | ×7.6 | OK |
| 그래프 | `GET …/graph` (전체 관계) | 12,096 | 1,559 (1,631) | ×7.8 | OK |
| 그래프 | `GET …/knowledge-graph` 첫 구성(캐시 없음) | 19,927 | **3,362** (3,811) | ×5.9 | **미달** |
| 그래프 | `GET …/knowledge-graph` 캐시 있음 | 2,002 | 1,886 (1,924) | ×1.1 | OK |
| 그래프 | `GET …/timeline` | 689 | 60 (65) | ×11.6 | OK |
| FTS | 색인 전체 재구축(시작 경로) | 26,459 | 1,061 (1,108) | ×24.9 | OK |
| FTS | `POST knowledge-notes` (쓰기 + 증분 색인) | 22 | 12 (18) | ×1.9 | OK |
| FTS | `GET …/search` (3종) | 43–53 | 47–56 | — | OK |
| FTS | `GET …/recall?q=GCB 쓴 실험의 회수율은?` | 6,089 | 256 (744) | ×23.8 | OK |
| FTS | `GET /memory/search?q=GCB` (교차 프로젝트) | 50 | 51 (457) | — | OK |
| Records | `GET /analysis/records/conditions` | 5,418 | 1,256 (1,808) | ×4.3 | OK |
| Records | `GET /analysis/records/operators` | 5,960 | 1,927 (2,333) | ×3.1 | OK(중앙값) |
| Records | `GET /analysis/records/periods` | 5,345 | 1,304 (1,624) | ×4.1 | OK |
| Records | `GET /memory/failures` (실패 아카이브) | 12,773 | **2,039** (2,337) | ×6.3 | **경계 미달** |

- **16개 응답 전부 수정 전과 동일**(`bench_scale --compare`, 아래 §6). 이전 판 표의 숫자(Records 7.7–8.2 s, 지식 그래프 28 s,
  재구축 35 s …)는 다른 호스트에서 잰 값이라 위 "수정 전" 열과 절대값이 다르다. 위 표의 전후 두 열은 **같은 호스트에서
  수정 전 코드(커밋 `07dd14e`)와 수정 후 코드를 같은 데이터베이스 사본으로** 잰 값이다.
- 미달 2건(지식 그래프 첫 구성, 실패 아카이브)의 이유와 남은 일은 §8.

## 1. 재현 (명령어 한 줄)

```bash
cd backend && python -m app.scripts.bench_scale --db /tmp/bench1000.db
```

처음 실행은 시드 + 합성 실험 1000개를 만들어 `/tmp/bench1000.db`에 남기고(≈ 1–2분), 다음부터는 그 파일의 **사본**에서
잰다(원본은 바뀌지 않으므로 두 실행이 바이트 단위로 같은 데이터에서 출발한다). 그 밖의 재현 명령:

```bash
# 전후 응답 비교: 한 번 덤프하고, 코드를 바꾼 뒤 같은 --db·--repeats로 비교 (다르면 exit 1)
cd backend && python -m app.scripts.bench_scale --db /tmp/bench1000.db --dump /tmp/resp-before
cd backend && python -m app.scripts.bench_scale --db /tmp/bench1000.db --compare /tmp/resp-before
```

```bash
# 수정 전 코드 자체로 재기: 07dd14e를 워크트리로 꺼내고 현재 벤치 스크립트만 넣어 실행
git worktree add /tmp/bp-before 07dd14e && cp backend/app/scripts/bench_scale.py /tmp/bp-before/backend/app/scripts/
cd /tmp/bp-before/backend && python -m app.scripts.bench_scale --db /tmp/bench1000.db --dump /tmp/resp-before
```

```bash
# 수정별 기여(§7): 수정을 하나씩 켜며 같은 벤치를 반복, 단계마다 응답이 0단계와 같은지 확인
cd backend && python -m tests.perf_stages --db /tmp/bench1000.db --repeats 3
```

```bash
# 출력 동일성 테스트(CI에서도 돈다)
cd backend && pytest tests/test_perf_equivalence.py app/memory/tests/test_similarity_pruning.py app/memory/tests/test_batched_memory.py app/analysis/tests/test_batch_metrics.py app/eln/tests/test_batch_reads.py
```

## 2. 방법

`app/scripts/bench_scale.py`가 `reference` 시드에 합성 실험 1000개를 더한다. 각 합성 실험은 참조 실험 7개 중 하나의
조건 블록(시료량·pH·정제제를 바꿈)·메모·CSV 데이터셋을 복사하고, 최근 50개 중 하나를 부모로 삼고, 분석을 실행해 결과를
저장한다. 모든 측정은 **실제 HTTP API**(`TestClient`, 규칙 모드, 네트워크 없음)를 거치며 클라이언트의 JSON 파싱까지
포함한다(사용자가 기다리는 시간에 가깝게).

| 데이터 규모 | |
|---|---|
| 실험 | 1,007 (1 프로젝트) |
| 데이터셋 | 1,726 (CSV 원문) |
| 분석 결과 | 3,308 (최신 결과의 출력 JSON 합계 89 MB — 검량선 결과 하나 평균 82 KB) |
| 감사 이벤트 | 6,056 |
| 환경 | 4 vCPU 컨테이너(Xeon 2.1 GHz), Python 3.11.18, SQLite 3.45.1, 단일 프로세스 |

이 호스트의 측정 잡음: 2초 미만 값은 실행마다 ±20% 안팎(가끔 GC로 한 번씩 400 ms가 튀어 "최대" 열에 보인다).

## 3. 측정 (수정 전)

요약 표의 "수정 전" 열. 구간별 프로파일(`cProfile`, 서비스 함수 직접 호출)로 아래 원인을 확인했다.

## 4. 원인 → 수정 → 재측정

수정 순서는 원칙대로 인덱스 → 일괄 조회 → 불필요한 비교 제거. 각 항목의 "재측정"은 §7 단계별 측정(3회 중앙값)의
해당 단계 전후 값이다.

### 4.1 데이터셋 후속본 조회 — 인덱스 없음 (인덱스)

- **원인**: 모든 `DatasetOut`이 `superseded_by_dataset_id`를 채우려고 `WHERE supersedes_dataset_id = :id`를 실행한다. 이
  열에 인덱스가 없어 **데이터셋마다 `eln_datasets` 전체 스캔**(1,726행, CSV 원문 포함 테이블). recall·색인·지식 그래프가
  데이터셋마다 이 조회를 1–2번 한다.
- **수정**: `eln_datasets.supersedes_dataset_id`에 인덱스(`ix_eln_datasets_supersedes_dataset_id`, Alembic `0003`).
- **재측정**: recall 6,159 → 1,852 ms, 지식 그래프 첫 구성 17,254 → 13,732 ms, 색인 재구축 26,572 → 24,317 ms.

### 4.2 FTS 색인 전체 재구축 — UNINDEXED 열로 DELETE (인덱스 + 일괄)

- **원인**: `sync()`가 이벤트마다 `DELETE FROM memory_search_fts WHERE doc_key = :k`. `doc_key`는 FTS5 `UNINDEXED` 열이라
  매번 가상 테이블 전체 스캔(`SCAN … VIRTUAL TABLE INDEX 0`) — 이벤트 6,056건 × 행 16,839개, 이차. 거기에 이벤트마다
  `documents_for()`가 실험·데이터셋을 하나씩 다시 읽었다.
- **수정** (`memory/search_index.py`):
  - B-tree 보조 테이블 `memory_search_fts_rows(fts_rowid INTEGER PRIMARY KEY, doc_key TEXT)` + `doc_key` 인덱스. 삭제는
    `DELETE FROM fts WHERE rowid IN (SELECT fts_rowid FROM rows WHERE doc_key IN (…))` — rowid 점 조회. FTS 테이블과 함께
    만들고 버리며(접두사가 같아 Alembic autogenerate가 무시), 맵 없는 옛 색인은 다음 동기화에서 다시 만든다.
  - 한 배치에서 같은 엔티티의 이벤트는 **마지막 것만** 문서화(이전 것은 어차피 바로 지워진다). 마지막 등장 순서를 지키므로
    행 순서도 이벤트별로 하나씩 교체할 때와 같다.
  - 실험·데이터셋·어휘를 종류별 한 번에 읽고(`prefetch`), 삭제·삽입은 500키 단위 문장과 `executemany`.
- **재측정**: 색인 재구축 24,317 → 1,130 ms. 증분 쓰기(`POST knowledge-notes`) 24 → 12 ms.

### 4.3 실험 목록 — 실험마다 쿼리 3개 (일괄)

- **원인**: `eln.list_experiments_full()`의 `_to_out()`이 실험마다 revision `COUNT`, 추가 기록, 첨부 파일을 따로 조회 —
  1,007개면 3,000여 쿼리. 그래프·타임라인·Records·실패 아카이브·recall이 모두 이 목록을 쓴다.
- **수정**: revision 수(`GROUP BY`), 추가 기록, 첨부 파일, 데이터셋 종류를 **각각 한 번의 `IN` 쿼리**로 읽는 `_to_outs()`.
  같은 방식의 `get_experiments`, `get_datasets`, `list_project_datasets`, `get_dataset_contents`(CSV는 필요할 때만, 메타데이터
  조회는 `defer(content)`).
- **재측정**: 기본 그래프 719 → 196 ms, 타임라인 681 → 114 ms.

### 4.4 Records — 실험별 N+1과 저장 결과 전체 재검증 (일괄 + 불필요한 작업 제거)

- **원인**: `records._rows()`가 실험마다 `get_metrics()` → `latest_results()` → 결과마다 `get_result()`. 결과 하나하나의
  출력 JSON을 판별 유니온 모델로 **전부** 검증했다 — 검량선 결과는 평균 82 KB(차트용 적합선·잔차·가중치별 적합 전부)인데
  지표에 필요한 것은 R²·역산 오차·가중치 몇 개뿐.
- **수정** (`analysis/metrics_view.py`, `analysis/service.py`):
  - 지표가 읽는 필드만 가진 뷰 모델(`extra="ignore"`, 필드 타입은 원래 스키마와 동일). 출력 JSON 텍스트를
    `validate_json`으로 바로 뷰에 검증해, 나머지 필드는 객체로 만들지 않는다.
  - `get_metrics_many()`: 실험 500개당 쿼리 하나로 최신 결과(실험·종류별 `max(id)`)를 읽는다. 종류 순서는
    `latest_results()`의 `GROUP BY kind`와 같게(`ORDER BY experiment_id, kind`) — 플래그 순서가 같아야 하므로.
  - `get_metrics()`(단건)도 같은 경로. Records는 프로젝트당 목록 1번 + 지표 1번.
- **재측정**: Records 조건별 4,543 → 1,285 ms, 작업자별 5,668 → 1,772 ms, 기간별 4,887 → 1,453 ms.

### 4.5 실패 아카이브 — 포트를 통한 실험별 조회, 쌍마다 계보 거슬러 오르기 (일괄 + 불필요한 비교 제거)

- **원인**: `failures.load()`가 실험마다 Memory 포트 `results()`·`qc_flags()`(→ wiring에서 다시 `get_metrics()` +
  `latest_results()` 2회) — 실험당 결과 9건 재검증. 그리고 반복 패턴 탐색 `_links()`가 실패 쌍(523개 → 136k쌍)마다
  `_descends()`로 계보 사슬을 처음부터 거슬러 올랐다.
- **수정**:
  - 포트에 일괄 메서드 `results_many` / `qc_flags_many` / `facts_many` / `describe_many`(`memory/schemas.FactProvider`, 기본
    구현은 항목별 호출이라 다른 제공자는 그대로 동작). wiring은 Analysis의 `get_metrics_and_heads_many`(한 번 읽어 지표와
    결과 머리 — id·종류·플래그 — 를 함께)로 구현한다.
  - 실패마다 조상 집합을 한 번만 계산(`_ancestors`)하고 쌍 판정은 집합 조회.
- **재측정**: 4,904 → 2,328 ms(일괄 포트·조상 집합 단계). 최종 2,039 ms(§8).

### 4.6 recall — 질문마다 모든 실험의 어휘를 하나씩 (일괄)

- **원인**: `recall()`이 실험 1,007개 각각 `experiment_vocab()` → `list_datasets()`(데이터셋마다 후속본 스캔) →
  데이터셋마다 `get_dataset()` 한 번 더.
- **수정**: `facts.experiment_vocabs()` — 프로젝트의 데이터셋 메타데이터 한 번, 아직 파싱하지 않은 CSV 한 번(`dataset_vocabs`).
  CSV 파싱 결과는 원래 있던 데이터셋 id·sha256 캐시(원본 불변이라 무효화가 필요 없음)를 그대로 쓴다. 새 캐시는 없다.
- **재측정**: recall 1,731 → 278 ms.

### 4.7 지식 그래프 첫 구성 — 이벤트마다 조회 (일괄)

- **원인**: 감사 이벤트 6,056건을 하나씩 `apply()`하며 실험(`get_experiment`), 데이터셋(`get_dataset` — CSV 원문까지 로드),
  분석 결과(`describe` → `get_result` — 82 KB 출력 전체 검증, 라벨에는 종류·버전·플래그만 필요)를 각각 따로 읽었다.
- **수정**: `refresh()`가 이벤트 배치를 적용하기 전에 종류별로 한 번에 읽는다(`_Builder.prefetch`: `get_experiments`,
  `get_datasets` + 어휘, 이벤트별 `describe_many`). 결과 라벨은 출력 없이 `get_result_heads()`로. 적용 순서·그래프 변경은 그대로.
- **재측정**: 첫 구성 14,366 → 10,196 ms.

### 4.8 조건 유사도 — 모든 쌍 비교 (불필요한 비교 제거)

- **원인**: `similar_pairs()`가 실험 쌍 전부(506,521쌍)에 `similarity()`를 부르고, 쌍마다 조건 키 13개의 값을 다시
  정규화했다. 전체 관계 그래프와 지식 그래프의 `shares_conditions`가 이 함수를 쓴다. 또 그래프는 간선마다 변경 키 목록만
  필요한데 `condition_changes()`로 `ConditionChange`·`SourceRef` 객체를 200만 개 만들었다.
- **수정** (`memory/conditions.py`) — **결과는 전수 비교와 정확히 같다**(점수는 비트 단위로 같고, 버리는 쌍은 임계값에 못
  미침이 증명된 것뿐):
  1. 키 집합 + 정규화된 텍스트 값이 같은 실험끼리 묶는다(묶음 안에서는 텍스트 값이 모두 같다).
  2. 묶음 쌍 후보는 접두사 필터(집합 유사도 조인)로 고른다: 점수 ≥ t이려면 일치 키 수 ≥ ⌈t·|키|⌉여야 하므로, 전역 순서로
     정렬한 앞쪽 `|키| − ⌈t·|키|⌉ + 1`개 토큰 중 하나는 공유해야 한다. 텍스트 불일치·한쪽에만 있는 키(기여 0)만으로 허용치
     `(1−t)·U`를 넘는 묶음 쌍은 버린다.
  3. 남은 묶음 쌍 안에서는 남은 허용치가 정규화 수치 거리의 합을 제한하고, 그 합은 정규화 좌표 합(1차원 투영)의 차보다
     크거나 같다 → 투영으로 정렬 + 창(window)으로 점수를 매길 쌍만 고른다.
  4. 점수는 실험마다 한 번 정규화한 값으로, 같은 키 순서·같은 IEEE 연산을 numpy로 묶음 단위 계산하고 반올림은 Python
     `round()`(비트 동일). 텍스트/수치가 섞인 키, NaN/inf, 2⁵³ 초과 정수가 있으면 해당 부분은 스칼라 경로.
  5. 안전 여유 `PRUNE_MARGIN = 1e-3`: 점수가 `t − 0.001` 미만임이 증명될 때만 버린다(4자리 반올림보다 훨씬 큼).
  6. 간선의 변경 키는 `changed_condition_keys()` — 객체를 만들지 않고 키만(정렬된 키 목록을 실험마다 한 번).
- **재측정**: 전체 관계 그래프 8,598 → 1,417 ms, 지식 그래프 첫 구성 10,196 → 3,462 ms. 1,007개에서 점수 계산 쌍
  506,521 → 129,618(그중 76,073쌍이 임계값 0.9 이상 — 출력 자체), `similar_pairs` 4.8 s → 0.2 s.

## 5. 한 일 / 하지 않은 일

- 캐시 추가 없음. 지식 그래프의 기존 감사 워터마크 캐시, 데이터셋 어휘의 sha256 캐시는 원래 있던 것이고, 지식 그래프
  "첫 구성" 측정은 매번 그래프 캐시와 무관하게 처음부터 만든다(`reset_cache()`).
- 원본 불변·감사 원칙과 무관한 변경만: 새 테이블은 파생 색인(FTS 보조 테이블)뿐, 원본 테이블에는 인덱스 하나 추가.
  `ImmutableMixin` 가드·raw UPDATE 없음.
- API 계약(경로·응답 필드) 변경 없음 — `openapi.json` 그대로. 서비스·포트에 함수를 **추가**만 했다.
- 시도했다가 되돌린 것: 지식 그래프 스냅샷의 `KGEdge.model_construct()` — 파이썬 수준이라 검증보다 3배 느렸다(1.4 s vs 0.46 s).

## 6. 출력 동일성 증명

1. **같은 데이터, 실제 이전 코드**: 커밋 `07dd14e`(수정 전)를 워크트리로 꺼내 같은 DB 사본에서 16개 응답을 덤프하고, 수정
   후 코드의 응답과 비교했다 — `all 16 responses identical`. 색인 재구축 측정은 FTS 테이블의 **모든 행**(텍스트·출처 열
   전부)을 응답으로 덤프하므로 색인 내용까지 같다. (이전 코드도 다른 호스트에서 만든 첫 덤프와 동일 — 데이터가 결정론적이다.)
2. **CI 테스트** `tests/test_perf_equivalence.py`: `lab` + `reference` 두 프로젝트에 합성 실험 65개를 더한 DB에서,
   최적화한 함수 전부를 **수정 전 구현(`tests/perf_reference.py`, `07dd14e`에서 그대로 옮김)**으로 바꿔 끼운 결과와 비교한다.
   - 엔드포인트 150개 이상: 그래프(관계별), 지식 그래프(필터 포함), 타임라인, 검색, recall(프로젝트·교차), Records 3종(옵션
     포함), 실패 아카이브, **모든 실험의** 지표, 비교, diff, 유사 실험, 추세 — 전부 동일.
   - FTS 전체 재구축의 모든 행이 rowid 순서까지 동일.
   - 함수 수준(순서 포함): `get_metrics_many`/`latest_result_refs_many` 종류 순서, 포트 일괄 메서드 vs 항목별, `describe_many`,
     ELN 일괄 조회 vs 단건, 일괄 어휘 vs 실험별 어휘.
   - 변이 검사로 테스트가 실제로 잡는지 확인했다: 유사 쌍 하나 누락, 플래그 종류 순서 뒤집기 → 실패.
3. **유사도 속성 테스트** `app/memory/tests/test_similarity_pruning.py`: 무작위 조건 블록 12세트(대소문자·공백만 다른 텍스트,
   범위 0인 키, 숫자/문자가 섞인 키, bool, 2⁶⁰ 정수, NaN·inf, 빈 블록) × 임계값 6개에서 `similar_pairs == 전수 비교`, 점수는
   `similarity()`와 `==`(근사 아님). 접두사 길이를 하나 줄이거나 창을 좁히는 변이는 실패한다.
4. 모듈 테스트: `app/eln/tests/test_batch_reads.py`(일괄 = 단건, 쿼리 수가 실험 수와 무관, 인덱스 사용),
   `app/analysis/tests/test_batch_metrics.py`(뷰의 모든 필드 = 전체 모델의 같은 필드), `app/memory/tests/test_batched_memory.py`
   (FTS 맵 교체·옛 색인 재구축, 포트 기본 구현, 지식 그래프 prefetch 유무 동일, 실패 아카이브·recall 일괄 = 항목별).

## 7. 수정별 기여 (재측정)

`python -m tests.perf_stages --db … --repeats 3` — 현재 코드에서 수정을 앞에서부터 하나씩 켠 누적 단계. 0단계는 모든 수정을
수정 전 구현으로 되돌리고 인덱스를 지운 상태(실제 `07dd14e`와의 차이는 표 아래). **9단계 모두 응답이 0단계와 동일.** 3회 중앙값,
2초 미만 값은 잡음 ±20–40%.

| 측정 (ms) | 0 수정 전 | +인덱스 | +FTS | +ELN 일괄 | +지표 뷰 | +실패 | +recall | +KG | +유사도 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| graph (derived_from) | 793 | 615 | 719 | 196 | 219 | 222 | 145 | 108 | 64 |
| graph (전체 관계) | 8,311 | 8,697 | 8,802 | 8,083 | 8,241 | 8,364 | 8,300 | 8,598 | 1,417 |
| knowledge-graph 첫 구성 | 17,254 | 13,732 | 13,578 | 13,459 | 13,473 | 13,871 | 14,366 | 10,196 | 3,462 |
| knowledge-graph 캐시 | 1,952 | 1,928 | 2,028 | 1,969 | 2,002 | 1,634 | 1,899 | 1,933 | 1,978 |
| timeline | 654 | 605 | 681 | 114 | 140 | 114 | 113 | 119 | 72 |
| 색인 전체 재구축 | 26,572 | 24,317 | 1,130 | 1,169 | 1,312 | 716 | 1,163 | 1,068 | 1,064 |
| POST knowledge note | 16 | 24 | 12 | 11 | 15 | 16 | 13 | 14 | 13 |
| recall | 6,159 | 1,852 | 1,978 | 1,543 | 1,550 | 1,731 | 278 | 318 | 264 |
| records/conditions | 5,411 | 5,315 | 5,291 | 4,543 | 1,285 | 1,480 | 1,413 | 1,324 | 1,345 |
| records/operators | 5,712 | 5,696 | 5,728 | 5,668 | 1,772 | 1,804 | 1,965 | 1,743 | 1,786 |
| records/periods | 5,415 | 5,337 | 5,055 | 4,887 | 1,453 | 1,374 | 857 | 886 | 1,417 |
| memory/failures | 7,217 | 7,238 | 7,620 | 6,922 | 4,904 | 2,328 | 2,216 | 2,111 | 2,054 |

(검색 3종·교차 검색은 전 단계 43–83 ms로 변화 없음 — 생략.)

0단계와 실제 이전 코드(요약 표의 "수정 전")의 차이: 14개 측정은 ±13% 안이지만 두 개가 다르다 — 전체 관계 그래프
8.3 s vs 12.1 s(0단계의 간선 변경 키 계산은 대체 함수가 객체 없이 키만 구하므로 이전 코드보다 가볍다), 실패 아카이브 7.2 s
vs 12.8 s(대체 지점 밖에서 0단계가 이미 새 코드를 쓰는 부분 — 단건 `get_experiment` 등 — 이 있으나 차이 전부를 분해하지는
못했다). 그래서 이 표는 **수정별 상대 기여**로 읽고, 전후 절대값은 요약 표(실제 이전 코드 vs 수정 후 코드)를 기준으로 한다.

## 8. 미달 항목 — 왜, 무엇이 남았나

### 지식 그래프 첫 구성 3.4 s (캐시 있으면 1.9 s)

- **왜**: 응답 자체가 크다. 노드 4,371개 · 간선 103,819개 · JSON 17 MB이고, 그중 `shares_conditions` 간선이 76,073개(73%)다.
  합성 실험이 7개 조건 블록의 변형이라 유사도 0.9 이상인 쌍이 실제로 그만큼 많다. 남은 시간은 출력에 비례한다(첫 번째
  호스트 기준 내역: 일괄 읽기 ≈ 0.5 s, 이벤트 적용·NetworkX 간선 10만 개 ≈ 0.55 s, 유사도 + 파생 간선 ≈ 0.35 s, 스냅샷
  — 간선 10만 개의 Pydantic 변환 ≈ 1.1 s, 직렬화 ≈ 0.15 s, 클라이언트 JSON 파싱 ≈ 0.3–0.5 s).
- **남은 일**(출력이 바뀌므로 이번 범위 밖, 결정 필요):
  1. 지식 그래프의 `shares_conditions`를 연구 그래프처럼 **선택적 관계**로(`relations=` 파라미터) — 기본 응답이 ⅓로.
  2. 실험당 유사 이웃 상위 k개만 간선으로(예: k=10).
  3. 화면 기본값을 `focus`+`radius` 하위 그래프로(이미 지원) — 전체 그래프를 한 번에 그리지 않기.
  4. (출력 유지) 간선을 Pydantic 모델 대신 직렬화 전용 경로로 — FastAPI 응답 계층 변경이라 별도 검토.
- 캐시로 덮는 방법(시작 시 미리 구성)은 원칙상 쓰지 않았다. 첫 구성은 프로세스 시작 후·롤백 직후 한 번만 일어난다.

### 실패 아카이브 2.04 s (중앙값, 최대 2.34 s), Records 작업자별 최대 2.33 s

- **왜**: 실험 1,007개 전부의 지표가 필요하고, 지표의 출처는 저장된 결과 출력 JSON(최신분 89 MB)이다. 뷰 검증으로 객체는
  거의 만들지 않지만 JSON 텍스트를 한 번은 끝까지 읽어야 한다(이 호스트에서 ≈ 0.95 s — 첫 호스트 0.66 s). 나머지는 실험
  목록, 실패 523건의 레코드 구성, 2.3 MB 응답 직렬화·파싱이다. 이 호스트는 첫 호스트보다 ≈ 40% 느리다(첫 호스트에서는
  `facts_many` 이전 코드로도 1.89 s였다) — 2초 경계에 걸려 있다.
- **남은 일**: 결과마다 지표에 쓰는 요약(수 KB)을 결과와 **함께 불변 레코드로 저장**하면(분석 실행 시 같은 트랜잭션,
  기존 결과는 새 레코드로 백필 — UPDATE 없음) 89 MB 대신 수 MB만 읽는다. 저장 스키마 변경이라 Analysis 담당 결정으로
  남긴다. 그 전까지는 Records·실패 아카이브의 프로젝트 필터(`project_id=`)가 읽는 양을 줄인다.

## 9. 바뀐 것 (모듈별)

| 모듈 | 변경 |
|---|---|
| eln | `_to_outs()` 일괄 변환, `get_experiments`·`get_datasets`·`list_project_datasets`·`get_dataset_contents`, 인덱스 `ix_eln_datasets_supersedes_dataset_id` (+ Alembic `0003_dataset_supersedes_index`) |
| analysis | `metrics_view.py`(지표 뷰), `get_metrics_many`·`get_metrics_and_heads_many`·`latest_result_refs_many`·`latest_result_ids_many`·`get_result_heads`, DTO `ResultHead`, Records 일괄 |
| memory | 유사도 가지치기·벡터화(`similar_pairs`, `similar_pairs_bruteforce`는 명세로 유지), `changed_keys`/`changed_condition_keys`, FTS 보조 테이블·일괄 동기화, `experiment_vocabs`/`dataset_vocabs`, 포트 일괄 메서드, 실패 아카이브 조상 집합, 지식 그래프 prefetch |
| core | `wiring.py` 일괄 포트 구현, `bench_scale.py` `--db/--dump/--compare` |
| tests | `tests/perf_reference.py`(수정 전 구현), `tests/test_perf_equivalence.py`, `tests/perf_stages.py`, `tests/test_bench_scale.py` |
