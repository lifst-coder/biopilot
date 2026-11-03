# CLAUDE.md — BioPilot 작업 규칙

BioPilot은 AI Research Partner다: **ELN → Research Memory → Scientific Analysis → AI Partner**.
여러 세션이 이 저장소에서 **병렬로** 작업한다. 아래 규칙은 그 병렬 작업이 깨지지 않게 하기 위한 것이다.
구조와 계약의 상세는 [ARCHITECTURE.md](ARCHITECTURE.md), 집어갈 작업은 [TASKS.md](TASKS.md).

## 1. 절대 원칙 (변경 금지)

- 원본 기록(메모·조건 블록·CSV)은 불변. AI 정리본·계산 결과·제안은 별도 레코드로 저장하고
  모든 변경은 AuditEvent에 남긴다.
- 화면의 모든 숫자는 저장된 데이터에서 계산된 값만. 예시 숫자 하드코딩 금지.
- 수치 계산은 Python 결정론적 코드, 해석·비판은 Partner 레이어. 둘을 섞지 않는다.
- AI 기능은 오프라인 규칙 모드가 기본이고, ANTHROPIC_API_KEY가 있을 때만 Claude 생성 모드.
  두 모드는 같은 출력 스키마를 쓴다.

이 원칙이 코드에서 어떻게 강제되는지:

| 원칙 | 강제 장치 |
|---|---|
| 원본 불변 | `app/core/immutability.py` — `ImmutableMixin` + `before_flush` 가드. UPDATE/DELETE 시 `ImmutableRecordError`(409). ELN 라우터에는 update/delete 엔드포인트가 없다. |
| 모든 변경 감사 | 서비스의 모든 생성/상태변경은 `app.core.audit.record_event()` 호출. `tests/test_principles.py`가 시드 레코드 전부에 감사 이벤트가 있는지 검사. AuditEvent 자체도 불변. |
| 숫자는 저장 데이터에서 | 분석 결과는 `AnalysisResult`(불변, 입력 sha256 지문)로 저장. Partner는 `Evidence`(출처 레코드 id 포함)로만 숫자를 인용. 프론트는 API 값을 **포맷만** 한다(`src/lib/format.ts`). 차트의 적합선도 백엔드가 계산(`fit_line`). |
| 계산/해석 분리 | `app/analysis/`에는 해석 문장이 없다(QC 플래그는 기준 대비 결정론적 판정). `app/partner/`는 숫자를 계산하지 않는다 — `partner/context.py`가 Analysis 서비스 결과를 Evidence로 옮길 뿐. |
| 규칙 모드 기본·동일 스키마 | `app/core/llm.py` 게이트웨이. 키가 없으면 `RulesOnlyGateway`. Claude 출력은 `CritiqueDraft`/`DigestDraft`/`AskDraft` 스키마로 검증하고, 근거 키 불일치·근거 없는 숫자(`ungrounded_numbers`)가 있으면 규칙 모드로 자동 대체(`fallback_reason` 기록). |

## 2. 모듈 경계

```
backend/app/
  core/       공유 커널: config, db, audit, immutability, llm, errors  (기능 모듈 import 금지)
  eln/        L1 원본 기록: Project, Experiment, Dataset
  memory/     L2 연구 기억: 계보 그래프(NetworkX), 타임라인, diff, 검색, AI 정리본(ExperimentDigest)
  analysis/   L3 결정론적 계산: 검량선, 회수율, IS 응답, 매트릭스 효과, 비교, AnalysisResult
  partner/    L4 해석: Critique, Hypothesis, Proposal, Decision, Q&A
  seed/       시드 데이터(CSV는 generate.py로 재현 가능) + 로더
```

- 각 모듈은 `models.py · schemas.py · service.py · router.py · tests/`를 자기 폴더에 가진다.
- **모듈 간 호출은 `app.<module>.service`(함수)와 `app.<module>.schemas`(DTO)로만.** 다른 모듈의
  `models`, `router`, 내부 파일을 import하지 않는다. 서비스는 ORM 객체가 아니라 Pydantic DTO를 반환한다.
- 의존 방향: `eln ← memory`, `eln ← analysis`, `eln/memory/analysis ← partner`. 역방향 금지.
- 다른 모듈 테이블에는 FK 컬럼만 허용, `relationship()` 금지.
- 테이블 이름은 `<module>_<entity>` (`eln_experiments`, `partner_proposals` …).
- `tests/test_architecture.py`가 위 규칙을 AST 정적 분석으로 검사한다. 이 테스트를 약화시키지 말 것.

## 3. 병렬 작업 규칙

> **자기 모듈 폴더와 자기 화면 탭만 수정한다. 다른 모듈에 필요한 변경은 CHANGES_REQUESTED.md에 적는다.**

| 담당 | 수정 가능 경로 |
|---|---|
| ELN | `backend/app/eln/**`, `frontend/src/features/notebook/**` |
| Memory | `backend/app/memory/**` (+ Notebook 탭의 diff/정리본 컴포넌트는 Notebook 담당과 협의) |
| Analysis | `backend/app/analysis/**`, `frontend/src/features/analysis/**` |
| Partner | `backend/app/partner/**`, `frontend/src/features/research-ai/**`, `frontend/src/features/partner-panel/**` |
| Frontend Shell | `frontend/src/{layout,components,lib,styles}/**`, `frontend/src/App.tsx`, Overview 탭 `frontend/src/features/overview/**` |

- 공유 파일(`app/core/**`, `app/main.py`, `app/models_registry.py`, `app/seed/**`, `frontend/src/api/queries.ts`,
  `frontend/src/api/types.ts`, CI, 이 문서)은 **직접 고치지 말고** CHANGES_REQUESTED.md에 요청을 적는다.
  예외: 자기 모듈의 새 라우터/모델을 등록하는 **한 줄 추가**는 허용 (`main.py`, `models_registry.py`),
  자기 모듈 엔드포인트용 훅을 `queries.ts`의 자기 섹션 끝에 추가하는 것은 허용.
- **생성 파일** `backend/openapi.json`, `frontend/src/api/schema.d.ts`는 손으로 고치지 않는다.
  머지 충돌이 나면 양쪽을 버리고 재생성한다(아래 명령).
- API 스키마를 바꾸면 같은 커밋에서 `openapi.json`과 `schema.d.ts`를 재생성한다(CI가 검사).
- 저장된 결과의 출력 형태가 바뀌면 `analysis/service.py`의 `METHOD_VERSIONS`를 올린다(예: `calibration@2`).
- 공유 계약(엔드포인트 경로·응답 필드)을 **삭제/이름변경**하지 않는다. 필드 추가는 자유, 제거는 CHANGES_REQUESTED.md로.

## 4. 커밋 규칙

- 타입 힌트, 문서화(docstring), 테스트 없이 커밋하지 않는다.
- 커밋 전에 아래 "테스트 실행"이 전부 통과해야 한다.
- 커밋 메시지: `<module>: <요약>` (예: `analysis: add LOQ estimation`, `frontend/notebook: dataset upload`).
  모듈 접두사는 `core|eln|memory|analysis|partner|seed|frontend/<tab>|frontend/shell|ci|docs`.
- 하나의 커밋은 하나의 모듈(+그 모듈의 화면)만 건드린다. 계약 재생성 파일은 예외.
- 원본 불변성을 우회하는 코드(raw SQL UPDATE, 가드 비활성화)는 금지.

## 5. 테스트 실행

```bash
# backend (Python 3.11)
cd backend
python -m venv .venv && source .venv/bin/activate   # 또는: uv venv -p 3.11 .venv
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy app
pytest                                   # 전체 (모듈 tests + tests/)
pytest app/analysis                      # 모듈 하나만
python -m app.scripts.export_openapi --check   # 계약 최신 여부

# frontend (Node 22)
cd frontend
npm ci
npm run check:api    # openapi.json → schema.d.ts 재생성 후 diff 없는지
npm run typecheck
npm test
npm run build
```

계약 재생성:

```bash
cd backend && python -m app.scripts.export_openapi
cd ../frontend && npm run gen:api
```

로컬 실행: `cd backend && uvicorn app.main:app --reload` (빈 DB면 자동 시드) + `cd frontend && npm run dev`
→ http://localhost:5173 . Claude 모드는 `ANTHROPIC_API_KEY`를 설정하고 서버를 재시작.

## 6. 테스트 작성 규칙

- 공용 픽스처는 `backend/conftest.py`: `session`(빈 in-memory DB), `seeded`(시드 + `{"#024": id, ...}`),
  `client`(시드된 TestClient), `fake_gateway_factory`(Claude 모드 대역).
- 시드 시나리오의 수치는 **범위**로 검증한다(예: #024 평균 회수율 58–66%). 정확한 값을 하드코딩하지 않는다.
- 네트워크 호출 테스트 금지. Claude 경로는 `FakeGateway`로 검증한다.
