# BioPilot — AI Research Partner

분석화학 실험실을 위한 **ELN → Research Memory → Scientific Analysis → AI Partner**.

- 작업 규칙: **[CLAUDE.md](CLAUDE.md)** · 구조와 계약: **[ARCHITECTURE.md](ARCHITECTURE.md)**
- 남은 작업: **[ISSUES.md](ISSUES.md)**(우선순위) · 모듈 간 요청: **[CHANGES_REQUESTED.md](CHANGES_REQUESTED.md)** · 백로그: [TASKS.md](TASKS.md)
- 시드 시나리오: [backend/app/seed/SCENARIO.md](backend/app/seed/SCENARIO.md)

## 1. 문제 정의

LC-MS/MS 잔류농약 분석 같은 방법 개발은 수십 번의 "조건 하나 바꿔 보기"로 이루어진다. 그런데 실험실의 기록은

- **흩어져 있다** — 메모는 노트에, 면적값은 장비 CSV에, 판단 근거는 사람 머릿속에 있다.
- **비교되지 않는다** — "#024가 #018보다 왜 낮지?"에 답하려면 조건 차이·회수율 차이·QC 이탈을 손으로 맞춰 봐야 한다.
- **잊힌다** — 석 달 전 "작업량 때문에 2×2 요인 실험은 기각"한 결정이 다음 제안에서 다시 나온다.
- **AI에게 맡기기 어렵다** — 언어 모델은 그럴듯한 숫자를 지어낸다. 실험 기록에서 그것은 치명적이다.

BioPilot은 원본을 바꾸지 않고 쌓고, 숫자는 결정론적 코드로만 계산하고, AI는 저장된 숫자를 **인용**해서
비판·가설·다음 실험 제안을 만들며, 연구자의 채택·수정·기각과 그 **사유**를 기억해 다음 제안에 반영한다.

## 2. 4레이어 아키텍처

```
 연구자 입력                                                              연구자 결정(+사유)
     │                                                                          ▲
     ▼                                                                          │
┌──────────┐  DTO   ┌─────────────┐        ┌───────────────┐  Evidence  ┌──────┴──────┐
│ L1  ELN  │──────▶│ L2 Memory   │──────▶ │ L3 Analysis   │──────────▶│ L4 Partner  │
│ 원본 기록 │        │ 계보·diff·  │  diff  │ 결정론적 계산  │  metrics   │ 비판·가설·  │
│ (불변)   │───────────────────────────▶│ (Python)      │  compare   │ 제안·결정   │
└──────────┘  CSV   │ 검색·회상·  │        └───────────────┘            └─────────────┘
                    │ 정리본·KG   │◀── app/wiring.py (Analysis·Partner 사실을 읽기 전용으로 연결)
                    └─────────────┘
         모든 생성·상태 변경 ──▶ core_audit_events (append-only)
```

| 레이어 | 모듈 | 하는 일 |
|---|---|---|
| L1 ELN | `backend/app/eln` | 실험·조건 블록·CSV 원본(불변), 업로드 검증(UTF-8/CP949, 스키마 버전), 첨부, 보충 기록, 템플릿 |
| L2 Memory | `backend/app/memory` | 계보 그래프·지식 그래프, 두 실험 diff(조건·결과·QC·단어 단위 메모), FTS5 검색·회상, AI 정리본 |
| L3 Analysis | `backend/app/analysis` | 검량선(WLS, 가중 선택·F-검정), 회수율·불확도·Grubbs, IS 응답, 매트릭스 효과, LOD/LOQ, 이온비, Welch+Holm 비교, 프로젝트별 QC 기준 버전 |
| L4 Partner | `backend/app/partner` | 근거(Evidence) 기반 비판, 가설 상태 전이, 우선순위가 매겨진 다음 실험 설계, 결정 피드백, Q&A(SSE 스트리밍) |
| core | `backend/app/core` | 설정, DB·Alembic, 감사 로그, 불변성 가드, LLM 게이트웨이(규칙/Claude) |

모듈 경계(의존 방향 `eln ← memory/analysis ← partner`, 다른 모듈은 `service`·`schemas`로만 접근)는
`backend/tests/test_architecture.py`가 AST로 검사한다. 프론트엔드는 탭 하나가 모듈 하나다
(Overview · Notebook · Analysis · Research AI + 오른쪽 Research Partner 패널).

## 3. 데이터 무결성 원칙

| 원칙 | 어떻게 지키는가 |
|---|---|
| 원본은 불변 | 메모·조건 블록·CSV는 `ImmutableMixin` + `before_flush` 가드로 UPDATE/DELETE 시 409. 잘못 들어온 원본은 `supersedes`로 대체만 된다. 업로드는 잘린 multipart·인코딩 변형을 400으로 거부한다. |
| 모든 변경은 감사 | 모든 생성·상태 변경이 같은 트랜잭션에서 `AuditEvent`를 남긴다. 시드 레코드까지 감사 이벤트가 있는지 `tests/test_principles.py`가 검사한다. |
| 화면의 숫자는 저장 데이터에서 | 분석 결과는 입력 sha256 지문이 붙은 불변 `AnalysisResult`. 프론트는 API 값을 포맷만 한다(`src/lib/format.ts`). 적합선도 백엔드가 계산한다. |
| 계산과 해석의 분리 | `analysis/`에는 해석 문장이 없고, `partner/`는 숫자를 계산하지 않는다 — Analysis 결과를 `Evidence`(출처 레코드 id 포함)로 옮겨 인용할 뿐이다. |
| AI는 근거 있는 숫자만 | Claude 출력은 같은 스키마로 검증하고, 근거와 맞지 않는 숫자(크기·단위·**부호** 포함)가 있으면 규칙 모드로 자동 대체하며 `fallback_reason`을 남긴다. |
| 규칙 모드가 기본 | `ANTHROPIC_API_KEY`가 없으면 모든 AI 기능이 결정론적 규칙 엔진으로 동작한다. 두 모드는 출력 스키마가 같다. |

## 4. 데모 순서

### reference 프로파일 (기본, 7개 실험)

"잔류농약 QuEChERS·LC-MS/MS 회수율 최적화" — 사과 매트릭스, 농약 5종, IS = TPP.
기준 프로토콜 #018의 평균 회수율은 약 89%, 추출 시간 단축 + GCB 정제로 바꾼 #024는 약 62%로 떨어지고
10회 주입 중 3회에서 IS 억제가 보인다. 모든 값은 커밋된 CSV에서 계산된다.

1. **Notebook** → `#024` 선택 → "과거 실험과 비교" → 기준 `#018`: 조건 차이 2개(추출 시간 10→5분, C18→GCB),
   저장된 분석 결과의 회수율 변화(%p)와 Welch t-test, 분석물별 변화.
2. **Analysis** 탭: 평균 회수율·RSD·검량선 R²·IS 이상 주입, QC 판정(carbendazim·thiabendazole 기준 미달), 잔차 플롯, 리포트 내보내기.
3. **Research AI** 탭: "비판적 검토 실행" → 판정(전처리 손실 vs 매트릭스 효과 구분 불가), 대안 설명, 근거 칩(E1…).
4. 다음 실험 제안 하나를 **기각** + 사유 입력 → "결정 기록".
5. 오른쪽 패널에 "#024 다음 실험은?"을 다시 질문하거나 비판을 다시 실행 → 답변과 비판이 방금 쓴 기각 사유를
   "결정 반영"으로 인용하고, 기각한 제안은 다시 나오지 않는다.

### lab 프로파일 (2개 프로젝트, 42개 실험, 6개월의 결정 이력)

`BIOPILOT_SEED_PROFILE=lab`으로 켠다. 잔류농약 30개 + 발효식품 유기산 12개 실험이 같은 장비·컬럼·내부표준·작업자를
공유한다. Overview 검색에 `#OA02`를 입력하면 잔류농약 #011 메모(같은 C18 컬럼 공유 → 피크 테일링)가 회상되고,
#024 비판은 6월에 "작업량 과다"로 기각된 2×2 요인 실험 대신 단일 변수 실험을 제안하며 그 사유를 인용한다.
이 흐름은 `frontend/e2e/`의 Playwright 테스트가 실제 백엔드로 재현한다.

### 백엔드 없는 데모 (GitHub Pages)

`.github/workflows/pages.yml`이 두 프로파일을 `scenario.json` / `scenario-lab.json`으로 내보내고, 프론트를
`VITE_DEMO=true`로 빌드해 배포한다. 모든 `/api` 요청은 파일 속 **실제 API 응답**으로 답한다(읽기 전용,
Partner 패널은 제안 질문 3개에만 답한다). 헤더에서 reference/lab을 바꿀 수 있다.

## 5. 로컬 실행

요구 사항: Python 3.11, Node 22.

```bash
cd backend
uv venv -p 3.11 .venv && source .venv/bin/activate   # 또는 python3.11 -m venv .venv
pip install -e ".[dev]"
uvicorn app.main:app --reload            # 빈 DB면 마이그레이션 후 자동 시드(reference)
```

```bash
cd frontend
npm ci
npm run dev                              # http://localhost:5173 (/api → :8000 프록시)
```

| 설정 (`backend/.env` 또는 환경변수) | 기본값 | 설명 |
|---|---|---|
| `BIOPILOT_DATABASE_URL` | `sqlite:///./biopilot.db` | DB 위치 |
| `BIOPILOT_SEED_PROFILE` | `reference` | 빈 DB에 넣을 시드: `reference` \| `lab` |
| `BIOPILOT_ELN_STORAGE_DIR` | `./eln_storage` | 첨부·원본 파일 블롭 저장소(sha256 주소) |
| `ANTHROPIC_API_KEY` | (없음) | 설정하면 Claude 생성 모드(`BIOPILOT_CLAUDE_MODEL`, `BIOPILOT_CLAUDE_EFFORT`) |
| `BIOPILOT_FORCE_RULES_MODE` | `false` | 키가 있어도 규칙 모드 |

lab 프로파일로 실행:

```bash
cd backend && BIOPILOT_SEED_PROFILE=lab BIOPILOT_DATABASE_URL=sqlite:///./lab.db uvicorn app.main:app --reload
```

백엔드 없는 데모를 로컬에서:

```bash
cd frontend && npm run demo:export && npm run dev:demo
```

### 검사

```bash
cd backend && ruff check . && ruff format --check . && mypy app && pytest && python -m app.scripts.export_openapi --check
```

```bash
cd frontend && npm run check:api && npm run typecheck && npm test && npm run build
```

```bash
cd frontend && E2E_PYTHON=../backend/.venv/bin/python npm run e2e   # Playwright, reference + lab
```

### DB 스키마와 기존 DB 재생성

스키마는 Alembic이 관리한다(`backend/app/core/migrations`, baseline `0001_baseline` = 5개 브랜치 병합 후 전체 스키마).
앱은 시작할 때 `Database.prepare_schema()`를 실행한다: 빈 DB는 생성 후 head로 표시, Alembic이 관리하는 DB는
`upgrade head`, **병합 이전에 `create_all`로 만든 DB는 `LegacyDatabaseError`로 시작을 거부**한다(어떤 컬럼이
빠졌는지 알 수 없어서 안전하게 올릴 수 없다). 그런 DB는 지금까지 시드 데이터뿐이므로 지우고 다시 시드한다:

```bash
cd backend
rm -f biopilot.db biopilot.db-journal     # BIOPILOT_DATABASE_URL을 바꿨다면 그 파일
rm -rf eln_storage                        # BIOPILOT_ELN_STORAGE_DIR (DB 밖의 블롭 저장소)
uvicorn app.main:app --reload             # 빈 DB → 마이그레이션 → 자동 시드
```

`eln_storage`는 sha256 주소라 남겨 둬도 해가 없지만(고아 블롭), DB와 함께 비우는 것을 기본 절차로 한다.
Memory의 FTS5 검색 인덱스(`memory_search_fts`)는 마이그레이션 대상이 아니며 첫 검색 때 다시 만들어진다.
연구자가 직접 입력한 원본은 재시드로 복원할 수 없으므로, 실제 기록이 쌓인 DB에서는 **절대 지우지 말고**
모델을 바꿀 때 revision을 추가한다: `cd backend && alembic revision --autogenerate -m "<module>: <변경>"`.

## 6. 의도적으로 구현하지 않은 것

| 범위 밖 | 이유 / 현재 상태 |
|---|---|
| 로그인·권한 | 단일 연구실 데모. 감사 이벤트의 actor는 `user`/`seed`/`ai:*` 고정 문자열이다(CHANGES_REQUESTED "인증/사용자 식별"). |
| 리치 텍스트 에디터 | 원본 메모는 불변 평문이다. 정정은 원본 수정이 아니라 보충 기록(addenda)과 메타데이터 개정 이력으로 남긴다. |
| 기기 연동 | LC-MS/MS 소프트웨어와 직접 연결하지 않는다. 벤더 내보내기 CSV(2종)를 가져오기 변환기로 받아 원본은 첨부로 보관한다. |
| 다중 사용자 협업 | 동시 편집·알림·리뷰 워크플로 없음. 동시 메타데이터 수정은 아직 409 대신 500이 날 수 있다(ISSUES.md). |
