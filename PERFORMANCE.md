# PERFORMANCE — 1000 실험 규모 측정 (2026-11-03)

**최적화는 하지 않았다.** 지금 코드가 어디서 느려지는지 기록하는 문서다. 보안 점검([SECURITY_REVIEW.md](SECURITY_REVIEW.md) §8)의 일부.

## 방법

```bash
cd backend && python -m app.scripts.bench_scale --experiments 1000 --repeats 5 --json bench.json
```

`app/scripts/bench_scale.py`가 임시 파일 SQLite에 `reference` 시드를 넣고 합성 실험 1000개를 더한다. 각 합성 실험은
참조 실험 7개 중 하나의 조건 블록(시료량·pH·정제제를 바꿈)·메모·CSV 데이터셋을 복사하고, 최근 50개 중 하나를 부모로
삼고(계보 깊이가 커지도록), 분석을 실행해 결과를 저장한다. 모든 측정은 **실제 HTTP API**(`TestClient`, 규칙 모드, 네트워크 없음)를
거친다. 값은 5회 중앙값·최댓값(색인 재구축은 2회). 최종 코드(병행 세션 병합 후)로 측정했고, 병합 전 같은 측정과 ±10% 안에서 같았다.

| 데이터 규모 | |
|---|---|
| 실험 | 1,007 (1 프로젝트) |
| 데이터셋 | 1,726 (CSV 원문 저장) |
| 분석 결과 | 3,308 |
| 감사 이벤트 | 6,056 |
| 구축 시간 | 113.6 s (실험당 ≈ 0.11 s: 생성 + 데이터셋 + 분석 실행) |
| 환경 | 4 vCPU 컨테이너, Python 3.11.18, SQLite 3.45.1, 단일 프로세스 |

## 결과

| 구간 | 측정 | 중앙값 ms | 최대 ms | 1초 기준 |
|---|---|---:|---:|---|
| 그래프 | `GET /memory/projects/{id}/graph` (derived_from) | 935 | 1,066 | 경계 |
| 그래프 | `GET …/graph` (derived_from + shares_conditions + tests_proposal) | **15,367** | 15,686 | **초과** |
| 그래프 | `GET …/knowledge-graph` 캐시 없음(전체 구축) | **27,557** | 27,632 | **초과** |
| 그래프 | `GET …/knowledge-graph` 캐시 있음 | **2,684** | 2,987 | **초과** |
| 그래프 | `GET …/timeline` | 850 | 1,237 | 경계 |
| FTS | 색인 전체 재구축(시작 경로 `sync_search_index`, 테이블 삭제 후) | **34,780** | 35,908 | **초과** |
| FTS | `POST knowledge-notes` (쓰기 + 증분 색인) | 29 | 31 | OK |
| FTS | `GET …/search?q=회수율` | 70 | 472 | OK |
| FTS | `GET …/search?q=GCB 정제` (2 용어) | 71 | 86 | OK |
| FTS | `GET …/search?q=회수` (2자, LIKE 경로) | 89 | 413 | OK |
| FTS | `GET …/recall?q=GCB 쓴 실험의 회수율은?` | **7,307** | 8,040 | **초과** |
| FTS | `GET /memory/search?q=GCB` (교차 프로젝트) | 99 | 104 | OK |
| Records | `GET /analysis/records/conditions?key=cleanup_sorbent` | **7,744** | 8,284 | **초과** |
| Records | `GET /analysis/records/operators` | **8,150** | 8,778 | **초과** |
| Records | `GET /analysis/records/periods` | **7,808** | 7,880 | **초과** |
| Records | `GET /memory/failures` (실패 아카이브) | **17,881** | 20,093 | **초과** |

참고로 같은 스크립트를 실험 47개(참조 7 + 합성 40)로 돌리면 Records 340–430 ms, 지식 그래프 첫 구축 414 ms,
recall 311 ms, 전체 관계 그래프 95 ms였다 — 아래 원인대로 실험 수에 대해 선형~이차로 커진다.

## 1초를 크게 넘는 구간의 원인

서비스 함수를 직접 `cProfile`로 돌려 확인했다(`TestClient`는 엔드포인트를 다른 스레드에서 실행해 프로파일에 안 잡힌다).

### 그래프: `shares_conditions` 관계와 지식 그래프 — 조건 유사도 O(n²)

- `memory/conditions.py: similar_pairs()`가 **모든 실험 쌍**(1,007 → 506,521쌍)에 `similarity()`를 부르고, 쌍마다 조건 키 13개
  각각 `key_similarity()` → `_norm_text()`(문자열 정규화·split)·`_is_number()`를 다시 계산한다. 호출 650만 회, 프로파일 33 s(전체 42.7 s 중).
  같은 실험의 정규화 값이 쌍마다 재계산되고, 임계값 미만 쌍을 미리 거르는 색인(예: 키·값 버킷)이 없다.
- 지식 그래프 첫 구축(`knowledge_graph.refresh` 51.8 s, 프로파일 기준)은 `recompute_derived()`에서 **같은 `similar_pairs()`**(32.6 s)를
  부르고, 나머지는 감사 이벤트 6,056건을 하나씩 `apply()`(18.2 s)하면서 데이터셋마다 `eln.get_dataset()`·`dataset_vocab()`으로
  **CSV 원문을 다시 파싱**한다(데이터셋 1,726개 × 2회).
- 캐시가 있어도 2.7 s인 것은 스냅샷 직렬화(노드·엣지 수천 개의 Pydantic 변환)와 캐시 유효성 확인 때문이다.
- 기본 그래프(`derived_from`)가 1초 근처인 것은 `eln.list_experiments_full()`의 실험별 추가 조회(`_to_out`마다 revision 수
  `COUNT`, 데이터셋 종류) — 실험당 쿼리 3개, 1,007개면 3,000여 회.

### FTS 색인 전체 재구축 — UNINDEXED 열로 DELETE (이차)

- `sync()`는 이벤트마다 `DELETE FROM memory_search_fts WHERE doc_key = :k`를 실행한다. `doc_key`는 FTS5의 `UNINDEXED` 열이라
  **매번 가상 테이블 전체 스캔**이다(`EXPLAIN QUERY PLAN`: `SCAN memory_search_fts VIRTUAL TABLE INDEX 0`). 행 16,839개에서 문장당
  ≈ 6.9 ms, 이벤트 6,056건 → 그 자체로 이차. 프로파일 40 s 중 `sqlite3.Cursor.execute`가 29.8 s, 문서 생성(`documents_for`,
  데이터셋 CSV 재파싱 포함)이 12.9 s.
- 이 경로는 §6 수정 후 **앱 시작 시 한 번**(색인 테이블이 없거나 뒤처진 DB)과 시드 커밋에서만 돈다. 평소 쓰기는 이벤트 1–2건이라
  29 ms다. 다만 기존의 큰 DB를 처음 띄우면 시작이 그만큼 늦어진다.

### recall — 질문마다 모든 실험의 어휘를 다시 만듦

- `memory/service.py: recall()`이 질문 하나에 **실험 1,007개 전부**의 `facts.experiment_vocab()`을 계산하고(8.5 s), 그 안에서
  `eln.list_datasets()`·`get_dataset()`·`dataset_vocab()`이 데이터셋 CSV를 다시 읽고 파싱한다. 검색(FTS) 자체는 70–90 ms다.

### Records·실패 아카이브 — 실험별 N+1 조회와 저장 결과 JSON 재검증

- `analysis/records.py: _rows()`(9.3 s)가 실험마다 `analysis.get_metrics()` → `latest_results()` → `get_result()`를 부른다. 결과마다
  `AnalysisResult.output` JSON을 디코딩하고 판별 유니온 Pydantic 모델로 다시 검증한다(`json.raw_decode` 1.2 s,
  `validate_python` 1.3 s, SQL 12,377회). 또 실험마다 `eln.get_experiment()`(revision `COUNT` 포함)를 따로 부른다.
- `memory/failures.py: load()`(23.7 s)는 같은 일을 Memory 포트(`wiring.py`의 `results()`·`qc_flags()`)로 한 번 더 한다 —
  실험당 `latest_results()` 3회(결과 9,924건 재검증). 세 Records 엔드포인트와 실패 아카이브는 모두 요청마다 전체를 다시 계산하고 캐시가 없다.

## 개선 방향 (기록만, 구현하지 않음)

| 구간 | 방향 | 담당 |
|---|---|---|
| 유사도 | 실험별 정규화 값을 한 번만 계산, 키·값 버킷으로 후보 쌍을 줄이기, 결과를 감사 워터마크로 캐시 | memory |
| 지식 그래프 | 데이터셋 어휘를 데이터셋 id(불변)로 캐시, `apply()` 일괄 조회 | memory |
| FTS 재구축 | 전체 재구축은 `DELETE` 없이 빈 테이블에 일괄 `INSERT`, 증분은 `doc_key` → rowid 매핑 테이블(일반 B-tree)로 삭제 | memory |
| recall | 실험 어휘를 색인(또는 데이터셋 id 캐시)으로 미리 계산 | memory |
| Records·실패 | 실험 목록·최신 결과를 한 번의 쿼리로 읽는 배치 서비스 함수(`latest_results_many`), 결과 출력 검증 생략 경로 | analysis(+eln, wiring) |
| ELN 목록 | revision 수·데이터셋 종류를 `GROUP BY` 한 번으로 | eln |

현재 데모 시드(참조 7개, lab 42개)에서는 위 구간이 모두 0.1–0.5 s 수준이라 사용자 체감 문제는 없다. 실험이 수백 개를 넘는
실사용에서는 Records 탭·지식 그래프·recall(Partner 패널의 과거 사례)이 먼저 느려진다.
