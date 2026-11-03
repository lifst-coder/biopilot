# SECURITY_REVIEW — 보안·견고성 점검 (2026-11-03)

저장소 공개 전환에 맞춘 점검이다. 각 항목은 **점검 → 결과 → 조치 → 회귀 테스트** 순서로 적었다.
측정 수치는 이 세션에서 실제로 돌린 값이다(4 vCPU 컨테이너, Python 3.11, SQLite 3.45).
**범위 밖(의도적 제외): 인증·권한.** 이 API는 로그인 없이 누구나 쓰기 요청을 보낼 수 있다는 전제에서
"한 요청이 서버를 멈추거나 내부를 드러내지 않는가"를 점검했다. 공개 배포에는 인증 프록시가 필요하다(§10).

## 요약

| # | 항목 | 발견 | 조치 | 회귀 테스트 |
|---|---|---|---|---|
| 1 | CORS | origin은 좁았지만 `allow_methods=["*"]`, `allow_headers=["*"]`, 목록형 env는 JSON만 | 메서드·헤더를 SPA가 쓰는 것만 허용, `BIOPILOT_CORS_ORIGINS` 쉼표/JSON, `*` 경고 로그, 보안 헤더 추가 | `tests/test_security.py` CORS 2건·헤더 1건 |
| 2 | 의존성 | 설치본은 깨끗하지만 **하한(floor)이 취약 버전을 허용**(starlette 7건, python-multipart 6건, h11 1건). npm 11건은 전부 주요 버전 올림 필요 | backend 하한 상향, CI에 `pip-audit`·`npm audit --omit=dev --audit-level=high`, Dependabot | CI 단계 |
| 3 | 업로드 견고성 | JSON 본문 크기 무제한(300 MB → RSS 2.6 GB), 열 20,000개 CSV가 90초 넘게 응답 없음(O(열²)), 깊은 JSON·서로게이트로 500 | 앱 전역 본문 상한·JSON 깊이·문자열 검증 미들웨어, CSV 행 200,000·열 1,000 상한, 중복 열 검사 O(열) | `tests/test_security.py` 본문 9건, `app/eln/tests/test_concurrency_limits.py` 상한 6건 |
| 4 | FTS5 raw SQL | 사용자 입력은 모두 바인딩 파라미터. 문자열 연결은 모듈 상수(`FTS_TABLE`)뿐 | 변경 불필요 — 주입 시도 회귀 테스트만 추가 | `test_search_input_is_bound_not_interpolated` 6건 |
| 5 | 오류 응답 | 스택트레이스는 없었지만 미처리 예외는 평문 `Internal Server Error`, IntegrityError는 500, 422가 입력 전체(최대 수 MB)를 되돌려 줌 | 500 `internal_error`·409 `conflict` 봉투, 422 `input` 200자 절단, 서로게이트 안전 인코딩 | `tests/test_security.py` 3건 |
| 6 | GET 검색의 쓰기 | `GET /search`·`/recall`이 매번 `CREATE VIRTUAL TABLE`·upsert·FTS 쓰기·커밋 | (병행 세션이 GET 읽기 전용·시작 시/POST 동기화를 먼저 반영) + 쓰기 커밋 시 같은 트랜잭션에서 증분 색인, 테이블 재생성 시 워터마크 초기화 | `app/memory/tests/test_search_readonly.py` 8건(동시 요청 2건) |
| 7 | revision `count+1` | 동시 PATCH 8건 중 대부분 IntegrityError(수정 전 500). 병행 세션의 SAVEPOINT 수정은 pysqlite에서 **감사 없는 커밋**을 남김 | SAVEPOINT 제거, 충돌 시 롤백 → 재조회 → 재시도(최대 5회), 끝내 실패하면 409 `revision_conflict` | `test_concurrency_limits.py` 3건 |
| 8 | 성능 | 1000 실험 규모에서 1초를 크게 넘는 구간 다수 | 기록만 — [PERFORMANCE.md](PERFORMANCE.md) | `python -m app.scripts.bench_scale` |
| 9 | Dependabot | 없음 | `.github/dependabot.yml`(pip·npm·actions) | — |

---

## 1. CORS

**점검.** `app/main.py`는 `allow_origins=settings.cors_origins`(기본 `localhost:5173`, `127.0.0.1:5173`)였지만
`allow_methods=["*"]`, `allow_headers=["*"]`였다. 자격 증명(`allow_credentials`)은 꺼져 있었다. 프런트는 개발 시
Vite 프록시(같은 출처)로, 데모는 백엔드 없이 동작하므로 교차 출처 호출은 "API를 다른 도메인에 둘 때"만 필요하다.

**조치.**
- 허용 메서드 `GET, POST, PATCH`(API에 PUT·DELETE 없음), 허용 헤더 `Content-Type, Accept` — 둘 다 환경변수
  `BIOPILOT_CORS_ALLOW_METHODS`/`_HEADERS`로 바꿀 수 있다. 목록 조회의 `X-Total-Count`는 `expose_headers`.
- `BIOPILOT_CORS_ORIGINS`는 쉼표 구분 또는 JSON 목록. 기본은 그대로 Vite 개발 서버 두 개. `*`는 명시적으로 넣을 때만
  허용되고 시작 시 경고 로그를 남긴다. `allow_credentials=False`를 명시.
- `/api` 응답에 `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`,
  `Referrer-Policy: no-referrer`(`SecurityHeadersMiddleware`). 사용자가 올린 첨부(HTML 포함)는 원래부터
  `Content-Disposition: attachment`라 다운로드되지만, MIME 스니핑까지 막았다. `/docs`는 CDN을 쓰므로 CSP 제외.

**테스트.** 허용 origin만 `Access-Control-Allow-Origin`을 받는지, `DELETE` 프리플라이트 거부, env 파싱 두 형식,
보안 헤더(거부 응답 포함).

## 2. 의존성 취약점

### backend — `pip-audit`

| 대상 | 결과 |
|---|---|
| 설치된 환경(`pip install -e ".[dev]"`, 2026-11-03 최신 해석) | **No known vulnerabilities found** |
| `pyproject.toml` **하한 버전**(`fastapi 0.115`가 허용하는 `starlette 0.38.6`, `python-multipart 0.0.18`, `h11 0.14`) | **14건** |

하한 그대로 설치되는 환경(캐시된 휠, 다른 패키지와의 해석 결과)에서는 아래 취약 버전이 깔릴 수 있었다.

| 패키지 (하한) | 권고 | 수정 버전 | 내용 |
|---|---|---|---|
| starlette 0.38.6 | CVE-2024-47874 | 0.40.0 | filename 없는 multipart 파트를 무제한 메모리에 버퍼링(DoS) |
| | CVE-2025-54121 | 0.47.2 | 큰 파일 multipart 파싱 중 이벤트 루프 차단 |
| | CVE-2026-48710 | 1.0.1 | Host 헤더로 재구성한 URL 미검증 |
| | CVE-2026-48817 · CVE-2026-48818 | 1.1.0 | `HTTPEndpoint` 메서드 디스패치, Windows `StaticFiles` 경로 |
| | CVE-2026-54282 | 1.3.0 | 요청 경로 미검증 URL 재구성 |
| | CVE-2026-54283 | 1.3.1 | `request.form()`의 `max_fields`/`max_part_size` 미적용 — **ELN `multipart.py`가 쓰는 옵션** |
| python-multipart 0.0.18 | CVE-2026-24486 | 0.0.22 | `UPLOAD_DIR` 경로 조작(비기본 설정) |
| | CVE-2026-40347 · CVE-2026-42561 | 0.0.26 · 0.0.27 | preamble/epilogue·파트 헤더 파싱 DoS |
| | CVE-2026-53538 · CVE-2026-53539 · CVE-2026-53540 | 0.0.30 · 0.0.31 | urlencoded `;` 구분자·구분자 탐색, `Content-Length` 미검증 |
| h11 0.14.0 (uvicorn 경유) | CVE-2025-43859 | 0.16.0 | chunked 줄 끝 관대 파싱 → 요청 밀수 |

**조치(수정 가능 → 올림).** `fastapi>=0.162`, `starlette>=1.3.1`, `python-multipart>=0.0.31`, `h11>=0.16`,
`pydantic-settings>=2.7`(`NoDecode`). 새 하한으로 다시 `pip-audit --no-deps -r <하한>` → **0건**. 주요 버전 경계를 넘는
것은 starlette 0.x → 1.x인데, 설치·테스트된 버전이 이미 1.10이고 FastAPI 0.162가 요구하므로 올렸다.
dev 의존성에 `pip-audit`을 넣고 CI backend 잡에 `pip-audit --skip-editable` 단계를 추가했다.

### frontend — `npm audit`

결과 11건(critical 2, high 1, moderate 8). **모두 해당 패키지의 현재 주요 버전 안에는 수정이 없다**
(`npm audit fix` 비강제 실행 결과 변경 0, 각 패키지는 이미 그 주요 버전의 최신: vite 5.4.21, vitest 2.1.9,
react-router-dom 6.30.6). 지시대로 **기록만** 한다.

| 패키지 | 심각도 | 범위 | 필요한 올림 | 런타임 번들 포함? | 영향 판단 |
|---|---|---|---|---|---|
| vitest / tinypool / @vitest/mocker / vite-node | critical | 개발 | vitest 2 → 5 | 아니오 | 테스트 러너 내부(프로토타입 오염 → RCE 가젯). 신뢰한 테스트 코드만 실행하므로 노출 없음 |
| vite / esbuild | high | 개발 | vite 5 → 8 | 아니오 | 개발 서버가 임의 사이트 요청에 응답(GHSA-67mh…) 등. `npm run dev`를 공용 네트워크에 열지 말 것 |
| openapi-typescript / @redocly/openapi-core / minimatch | moderate | 개발 | openapi-typescript 7 → 6(다운그레이드 제안) | 아니오 | 저장소 안의 `openapi.json`만 입력 |
| react-router / react-router-dom | moderate | **런타임** | 6 → 7 | 예 | GHSA-wrjc(`<Link>` 백슬래시 오픈 리다이렉트): 앱의 링크는 모두 내부 경로 상수라 사용자 입력이 `to`로 가지 않음. GHSA-337j는 SSR 하이드레이션 전용 — 이 앱은 SPA |

CI frontend 잡에 `npm audit --omit=dev --audit-level=high`(런타임 의존성, high 이상이면 실패)를 넣었다. 현재 통과한다.
주요 버전 올림(vite 8, vitest 5, react-router 7)은 Dependabot이 개별 PR로 제안하도록 두었다(§9).

## 3. 업로드 견고성

**방법.** 실제 `uvicorn` 프로세스를 케이스마다 새로 띄우고 요청 한 건을 보낸 뒤 서버 프로세스의 최대 RSS(`VmHWM`)와
응답 시간을 쟀다. 같은 스크립트를 수정 전(`main`)과 수정 후에 돌렸다. "수억 행 CSV"는 그대로 보낼 수 없어서
(1억 행 ≈ 1 GB+) **상한을 넘는 바이트를 계속 흘려 보내는 요청**과 **바이트 상한 안에서 행 수를 최대로 늘린 요청**으로 나눴다.

| 입력 | 수정 전 | 수정 후 |
|---|---|---|
| JSON 300 MB (`Content-Length` 있음) | 400, **25.4 s, RSS 216 → 2,617 MB** | **413**, 본문을 읽기 전에 거부(0.9 s는 클라이언트 전송), RSS 변화 없음 |
| JSON 300 MB (chunked, 길이 없음) | 400, 14.7 s, RSS → **2,699 MB** | 413, 0.08 s(12 MB 넘는 순간 중단), RSS +11 MB |
| JSON 텍스트 CSV 2,000,000행 (`/datasets/validate`) | 200 OK, 3.2 s, RSS +476 MB | 413(JSON 12 MB 상한) — 상한 안이면 행 상한으로 400 |
| multipart CSV 5 MB = 356,922행 (저장) | **201 저장됨**(이후 분석·미리보기가 매번 35만 행 파싱) | 400 "행이 너무 많습니다 (최대 200,000행)" |
| multipart CSV 5,000열 (검증) | 8.6 s | 0.08 s(`ok=false`, `parse_error` "열이 너무 많습니다") |
| multipart CSV 20,000열 (검증) | **90 s 타임아웃 — 응답 없음**, 그동안 워커 1개 점유 | 0.09 s |
| UTF-8 폭탄(5 MB 유효 UTF-8 + 끝 1바이트 무효 → UTF-8·CP949 두 번 전체 디코딩) | 400, 0.18 s, +14 MB | 400, 0.14 s (원래 선형이라 문제 없음) |
| JSON 중첩 100,000단계 | 400(FastAPI 기본 문구) | 400 `validation_failed` "최대 32단계" |
| JSON 중첩 500단계 (`condition_block` 안) | **500** — 저장 시도 후 응답 직렬화에서 `Circular reference detected (depth exceeded)` | 400 |
| JSON 짝 없는 서로게이트 `\ud800` × 1M | **500** — 오류 응답을 UTF-8로 인코딩하다 `UnicodeEncodeError` | 400 |

원인과 조치:

1. **JSON 본문 크기 무제한.** FastAPI는 JSON 본문을 끝까지 메모리에 읽은 뒤 `json.loads`한다. multipart 업로드는
   ELN이 스트리밍 중 크기를 세지만(`eln/multipart.py`), `POST /datasets`(CSV 텍스트)·`/datasets/validate` 같은 JSON
   경로에는 상한이 없었다. → `app/core/limits.py` **`RequestLimitMiddleware`**(순수 ASGI):
   - 모든 본문 ≤ `BIOPILOT_MAX_REQUEST_BYTES`(기본 32 MiB = 첨부 20 MB + 여유), JSON 본문 ≤ `BIOPILOT_MAX_JSON_BYTES`
     (기본 12 MiB = CSV 텍스트 5 MiB의 JSON 이스케이프 여유). `Content-Length`로 먼저 거르고, chunked는 받는 동안 센다 → 413.
   - JSON은 한 번 파싱해 **반복(비재귀) 순회**로 깊이 ≤ `BIOPILOT_MAX_JSON_DEPTH`(기본 32; API의 가장 깊은 요청 모델은
     8단계 미만)와 모든 문자열·키의 UTF-8 인코딩 가능 여부를 검사 → 400. 잘못된 JSON 문법은 FastAPI 기본 422 그대로.
   - `DatasetCreate.content`에 `max_length = 5 MiB`(스키마에도 반영, `openapi.json` 재생성).
2. **열 수에 대해 이차 시간.** `validate_frame`의 중복 열 검사가 열마다 `list(frame.columns).count(c)` → O(열²)
   (5,000열에서 프로파일 28 s). → `Counter`로 O(열). 그리고 **열 상한 1,000**(와이드 장비 내보내기는 분석물당 2열 →
   수백 성분 다성분법 여유)을 pandas 실행 **전에** `csv.reader`로 헤더만 읽어 검사.
3. **행 수 상한 없음.** 5 MB 안에 35만 행이 저장됐고, 이후 Analysis·미리보기·지식 그래프가 매번 다시 파싱한다.
   → **행 상한 200,000**(장기 계약 행 = 주입 × 분석물 ≈ 300 × 300 = 90,000의 두 배 여유). `pd.read_csv(nrows=상한+1)`라서
   상한을 넘는 파일도 상한+1행까지만 읽는다. 와이드 → 롱 변환은 행이 분석물 수만큼 곱해지므로 변환 직후 다시 검사.
   상한 이전에 저장된 큰 데이터셋의 미리보기는 500 대신 400.
4. **UTF-8 폭탄.** 디코딩은 최대 2회 선형(UTF-8 → CP949)이고 바이트 상한 5 MB가 먼저 걸리므로 문제가 없음을 확인했다.
   요청 `Content-Encoding: gzip`은 서버가 풀지 않으므로 압축 폭탄 경로는 없다. CSV 외 첨부는 파싱하지 않는다(블롭 저장만).

**회귀 테스트.** `tests/test_security.py` — 선언된 초과 크기 413, chunked JSON이 1 MiB 직후 읽기를 멈추는지(ASGI 수준에서
`receive` 호출 수 확인), non-JSON 스트림 상한, 적대적 JSON 5종이 400, 정상 JSON·이모지(유효한 서로게이트 쌍) 통과.
`app/eln/tests/test_concurrency_limits.py` — 행 상한 경계(200,000 통과 / 200,001 거부), 50,000열 거부, 1,000열 검증 2초 미만,
읽을 수 없는 헤더, `content` 길이 상한, 상한 이전 데이터셋 미리보기 400.

## 4. FTS5 raw SQL

`app/memory/search_index.py`가 저장소에서 유일한 raw SQL이다(`grep text(` 확인). 모든 사용자 입력은 바인딩 파라미터다.

| 문장 | 사용자 입력 | 방식 |
|---|---|---|
| `... WHERE {FTS_TABLE} MATCH :match` | 검색어(3자 이상) | 각 용어를 FTS5 구문 `"…"`으로 감싸고 내부 `"`를 `""`로 이스케이프한 뒤 **`:match` 파라미터**로 전달 → `NEAR(`, `*`, `^`, `col:` 같은 FTS 문법이 연산자로 해석되지 않음 |
| `text LIKE :s0 ESCAPE '\'` | 검색어(3자 미만) | `%`, `_`, `\` 이스케이프 후 파라미터 |
| `DELETE … WHERE doc_key = :k`, `INSERT … VALUES (:text, …)` | 저장된 기록에서 나온 텍스트 | 파라미터 |
| f-string 보간 | `FTS_TABLE`(모듈 상수), `score` 식(`"0.0"` 또는 `-bm25(...)` 상수), `where` 조각(상수 문자열만) | 사용자 값 없음 |

조치 불필요. `" OR 1=1 --`, `'); DROP TABLE eln_experiments; --`, 따옴표 깨기, FTS 연산자, LIKE 와일드카드를
`search`·`recall`·`search_all`에 넣고 결과가 정상이며 테이블이 그대로인지 확인하는 회귀 테스트를 추가했다.

## 5. 오류 응답의 정보 노출

**점검.** `uvicorn`은 debug가 아니라 스택트레이스를 응답에 싣지 않았다. 다만:
- 미처리 예외 → 평문 `Internal Server Error`(JSON 봉투가 아님), `IntegrityError` → 500.
- 422가 pydantic의 `input`을 그대로 되돌려 줘서 필수 필드 하나가 빠진 5 MB 요청은 5 MB를 되돌려 받았고,
  입력에 짝 없는 서로게이트가 있으면 응답 인코딩 자체가 실패해 500이 됐다(§3 마지막 행).
- `DomainError` 메시지 중 예외 문자열을 싣는 곳(`CSV를 해석할 수 없습니다: {pandas 오류}`, multipart 파서 메시지,
  partner 조건 블록 검증)은 모두 입력에 관한 설명이며 경로·SQL을 담지 않음을 확인했다.

**조치(`app/main.py`).**
- `Exception` → 500 `{"code":"internal_error","message":"서버 내부 오류가 발생했습니다"}`, 트레이스는 서버 로그(`app` 로거)에만.
- `IntegrityError` → 409 `{"code":"conflict"}` — 제약 위반 SQL·값은 로그에만(경고). §7의 재시도가 1차 방어, 이것은 안전망.
- `RequestValidationError` → FastAPI와 같은 `{"detail":[{loc,msg,type,input,…}]}` 형태를 유지하되 `input`을 JSON 200자로
  자르고 서로게이트를 `\udXXX`로 이스케이프. (`ARCHITECTURE.md` §3 오류 표에 413·409 `conflict`·500 추가.)

**테스트.** 일부러 경로·SQL이 담긴 `RuntimeError`와 `IntegrityError`를 던지는 라우트를 붙여 응답에 `Traceback`, `/home/`,
`.py`, `SELECT`, `UNIQUE constraint`가 없는지, 422 응답이 5 KB 미만인지, 404가 `{code,message}`인지 검사.

## 6. GET `/search`·`/recall`의 DDL·쓰기·커밋

**문제.** `search_index.search()`가 매 호출마다 `sync()`를 불렀다: `CREATE VIRTUAL TABLE IF NOT EXISTS`,
`memory_index_state` upsert, 새 감사 이벤트의 FTS 삭제·삽입, 그리고 요청 세션 커밋. GET이 쓰기 락을 잡으므로 동시 검색이
SQLite에서 직렬화되거나 `database is locked`가 날 수 있고, 읽기 전용 복제본·권한이 낮은 DB 계정에서는 실패한다.

**병합 경위.** 이 점검 도중 병행 세션이 같은 문제를 main에 먼저 고쳤다(`ab34ac8`): 읽기는 워터마크까지 FTS + 이후 감사
이벤트 Python 스캔, 동기화는 시작 시(`lifespan`)와 새 엔드포인트 `POST /api/memory/search-index/sync`에서만. 그 구현과 계약은
그대로 두고 아래를 더했다.

**추가 조치(`app/memory/search_index.py`).**
- **쓰기 시점 색인:** 병행 수정만으로는 다음 재시작이나 수동 POST 전까지 새 기록이 전부 스캔 경로로 가서, 검색 비용이 마지막
  동기화 이후 쓰기 양에 비례해 커진다. `after_flush`에서 감사 이벤트가 생긴 프로젝트를 기록하고, `before_commit`에서 그 프로젝트만
  **같은 트랜잭션 안에서** 증분 색인한다. SAVEPOINT 안에서 돌려(이미 감사 INSERT로 바깥 트랜잭션이 열려 있으므로 안전 — §7 참고)
  색인이 실패해도 원본 쓰기는 커밋되고 로그만 남는다. composition root `app/wiring.py`가 `memory.install_search_index_sync()`로 등록.
- **워터마크 초기화:** 테이블을 새로 만들면 모든 프로젝트 워터마크를 함께 지운다. 이전에는 테이블이 지워진 뒤 한 프로젝트가
  다시 만들면 다른 프로젝트들이 "이미 색인됨" 워터마크 때문에 FTS에서 영영 빠졌다.

**테스트(`app/memory/tests/test_search_readonly.py`).** 엔진의 `before_cursor_execute`에서 INSERT/UPDATE/DELETE/CREATE/DROP을
기록해 GET 5종(프로젝트·교차, 짧은 검색어 포함)이 **0건**인지; 인덱스를 지운 상태에서도 GET이 쓰지 않고 같은 결과를 주는지;
시작 시 색인·커밋 시 증분 색인; 미커밋 쓰기 스캔; 색인 실패가 쓰기를 막지 않음; **동시성** — 파일 SQLite에서 GET 24건 동시
(전부 200, 순차 결과와 동일, 쓰기 0건)와 쓰기 6 + 읽기 6 동시(500 없음, 모든 메모 색인·검색됨, 워터마크 = 최신 감사 id).
점검 시작 시점의 코드로 돌리면 "쓰기 0건" 두 테스트가 실패함을 확인했다.

## 7. ELN revision `count+1` 경쟁

**재현.** 파일 SQLite에서 같은 실험에 PATCH 8건을 배리어로 동시에 보내면 대부분이 `UNIQUE constraint failed:
eln_experiment_revisions.experiment_id, revision`(점검 시작 시 500)으로 실패했다(3회 반복 모두 재현).

**병행 수정의 결함.** 병행 세션이 main에 넣은 수정(`f8928b6`)은 `update_metadata()` 안에서 `session.begin_nested()`(SAVEPOINT)로
개정을 기록하고 충돌이면 409 `revision_conflict`를 냈다. 그런데 이 시점까지 그 요청은 SELECT만 했으므로 pysqlite가 `BEGIN`을
보내지 않았고, SQLite에서 **SAVEPOINT가 바깥 트랜잭션이 되어 RELEASE가 곧 커밋**이다. 실제로 수정 후 요청을 롤백해 보면
제목 변경과 개정 행은 남고 `update_metadata` 감사 이벤트만 사라졌다 — "모든 변경은 AuditEvent에" 원칙 위반.

**조치.** SAVEPOINT를 없앴다. 라우터가 쓰는 `eln.service.update_metadata_in_own_transaction()`(트랜잭션에 이 수정만 있는 호출)이
`uq_experiment_rev` 위반(`IntegrityError`)을 받으면 **트랜잭션 전체를 롤백** → 실험을 **다시 읽어** 번호와 before/after를
이긴 쪽이 커밋한 값 기준으로 재계산 → 재시도(최대 5회). 끝내 지면 병행 수정과 같은 409 `revision_conflict`. 동시 수정은 이제
대부분 200으로 끝나고, before까지 다시 읽기 때문에 revision 사슬(각 before = 직전 after)이 끊기지 않는다.

**테스트.** (결정적) 카운트 직후 다른 세션이 끼어들어 커밋하게 만들어 재시도와 사슬 정합 확인, 끝까지 지는 경우 409,
롤백된 수정이 제목·개정·감사 어느 것도 남기지 않음, (동시성) HTTP PATCH 8건 동시 → 전부 200, revision 2–9 유일, 감사 사슬 연속.
병행 세션의 `test_concurrent_metadata_patch_is_409_not_500`(영구히 오래된 카운트 → 409)도 그대로 통과한다.

## 8. 성능

[PERFORMANCE.md](PERFORMANCE.md). 1000 실험에서 지식 그래프 첫 구축 28 s, 전체 관계 그래프 15 s, 색인 전체 재구축 35 s,
Records 7.7–8.2 s, 실패 아카이브 18 s, recall 7 s. 원인(유사도 O(n²), FTS UNINDEXED 열 삭제 풀스캔, 실험별 N+1 조회)을 적었고
최적화는 하지 않았다. 참고: GET 검색 자체는 70–90 ms로, §6 이후 색인 비용은 쓰기(29 ms)와 시작 시점으로 옮겨졌다.

## 9. Dependabot

`.github/dependabot.yml` — `pip`(`/backend`), `npm`(`/frontend`) 매주 월요일, `github-actions` 매월. minor·patch는 생태계별
한 PR로 묶고, 주요 버전은 개별 PR(§2의 vite·vitest·react-router). 커밋 접두사 `ci`(CLAUDE.md §4). 보안 업데이트는 저장소
Settings → Code security에서 "Dependabot security updates"를 켜야 별도로 열린다.

## 10. 남은 위험 (고치지 않음)

| 항목 | 이유 |
|---|---|
| 인증·권한 없음 — 누구나 기록 생성·첨부 업로드·Claude 모드 호출(비용) 가능 | 의도적 범위 밖. 공개 배포 시 인증 프록시(예: OAuth2 Proxy)와 IP 제한 필요 |
| 요청 빈도 제한 없음 — 상한 안의 요청(5 MB CSV, Records 8 s)을 반복하면 워커를 붙잡을 수 있음 | 리버스 프록시의 rate limit 권장. 무거운 GET은 PERFORMANCE.md |
| 첨부 저장소 총량 제한 없음(파일당 20 MB, 개수 무제한) | 인증 없이는 사용자별 쿼터를 둘 수 없음 |
| SQLite 쓰기 직렬화 — 동시 쓰기가 5초 넘게 기다리면 `database is locked` → 500 `internal_error` | 운영 규모면 PostgreSQL. 오류는 이제 내부 정보 없이 봉투로 나감 |
| `/docs`·`/openapi.json` 공개 | 공개 저장소에 계약이 이미 있으므로 유지 |
| npm 주요 버전 올림 필요 11건 | §2 — 개발 의존성이거나 런타임 영향 없음으로 판단, Dependabot PR로 처리 |

## 재현 명령

```bash
cd backend && pip-audit --skip-editable
cd frontend && npm audit && npm audit --omit=dev --audit-level=high
cd backend && pytest tests/test_security.py app/eln/tests/test_concurrency_limits.py app/memory/tests/test_search_readonly.py
cd backend && python -m app.scripts.bench_scale --experiments 1000
```
