# FINAL_CHECK — 제출 전 최종 점검 (2026-11-04)

SK AIGEN 지원 포트폴리오(접수 마감 11/15) 제출 전, 심사위원이 **README를 읽고 데모 링크를 열어 몇 분 클릭해 보는**
경로를 처음 보는 눈으로 따라가며 점검했다. 아래는 실제로 돌려 본 결과와 고친 것, 고치지 않고 남긴 것이다.

> **태균이 직접 판단·확인해야 할 항목은 [§4](#4-제출-전에-태균이-직접-판단확인할-것)에 따로 모았다.**

## 1. 점검 방법

| 범위 | 방법 |
|---|---|
| 문서 정합성 | README · ARCHITECTURE · ISSUES · SECURITY_REVIEW · PERFORMANCE · CHANGES_REQUESTED를 코드와 대조. ARCHITECTURE §3은 `backend/openapi.json`의 경로 82개와 스크립트로 대조 |
| 데모 전체 | `VITE_DEMO=true`, `VITE_BASE=/biopilot/` 빌드를 GitHub Pages와 같은 방식(딥 링크는 `404.html`)으로 띄우고 Playwright로 **reference·lab × 1440/768/390px × 탭·하위 화면 29개 = 87화면** 순회: 콘솔 오류, 페이지 예외, `scrollWidth > clientWidth`(가로 스크롤), 빈 본문, 오류 문구, 전체 화면 캡처 |
| 쓰기 동작 | 데모에서 결정 기록, 비판 실행, 프로젝트 수준 검토, 자유 질문, 프로토콜 추출·저장, 실행 시작, 새 실험 작성·저장, 정리본 생성, 재분석, 리포트 다운로드를 실제로 눌러 결과 확인 |
| README 클릭 순서 | §6의 1~6단계를 lab 데모에서 스크립트로 그대로 따라가며 각 단계에서 README가 약속한 내용(코드·수치·문구)이 화면에 있는지 확인 |
| CI | GitHub Actions 최근 실행 기록 확인(이 세션은 Actions를 실행할 수 없어 로그만 읽었다) |
| 전체 검증 | pytest · ruff · mypy · 계약 검사 · alembic · vitest · tsc · build · build:demo · e2e (§3) |

## 2. 고친 것

### 2.1 CI가 main에서 빨간색이었다 (가장 중요)

최근 3번의 main 푸시에서 CI가 **실패**하고 있었다. 원인은 코드가 아니라 `pip-audit` 단계: GitHub 러너의 Python에
기본 설치된 `setuptools 79.0.1`에 새 취약점 공지(PYSEC-2026-3447, GHSA-xmj3-9gf7-h52w)가 나왔다. 프로젝트 의존성은 깨끗했다.
이 단계가 실패하면서 **Alembic 검사와 e2e 잡도 건너뛰어지고 있었다.** 저장소를 연 심사위원이 커밋 옆 빨간 ✕를 보게 되는 상태.

- 수정: `.github/workflows/ci.yml` Install 단계에서 `pip`·`setuptools`를 먼저 올린다.
- 확인: 로컬 venv에 `setuptools==79.0.1`을 넣어 같은 3건을 재현 → 올린 뒤 "No known vulnerabilities found".

### 2.2 데모에서 쓰기가 "오류"로 보였다

데모는 읽기 전용이라 쓰기는 403으로 막히는데, 화면에는 빨간 `오류: …`로 나와 고장처럼 보였다. 두 군데는 아예 안내가 없었다.

| 동작 | 이전 | 이후 |
|---|---|---|
| 모든 쓰기(결정·비판·정리본·저장·실행 등) | 빨간 "오류: 데모 모드(읽기 전용)…" | 노란 **"데모 · 읽기 전용 —"** 안내(`ErrorState`가 `demo_read_only`·`not_in_scenario`를 오류와 구분) |
| Research AI "프로젝트 수준 검토" | **아무 반응 없음**(오류를 표시하는 코드가 없었다 — 로컬에서도 실패 시 무반응) | 안내 표시 |
| Notebook "+ 새 실험" | 빈 화면에 "오류: 데모 시나리오에 미리 저장되지 않은 요청" | 작성 양식이 열리고(빈 초안·프로토콜 초안을 시나리오에 추가), 위에 "저장되지 않음" 안내 |
| Analysis 리포트 Markdown/CSV | "리포트를 받지 못했습니다 (HTTP 404)" | **실제로 내려받아진다**(내보내기가 실험별 리포트 본문·헤더를 저장) |
| Protocols 붙여넣기 → 조건 추출 | 무엇을 붙여넣든 실패 | **"예시 원문 넣기"** 버튼 → 추출 결과(실제 API 응답)를 볼 수 있다. 다른 원문은 이유를 설명하는 안내 |
| 제안 결정 폼 | 눌러야 실패를 알 수 있었다 | 폼 아래에 "데모는 저장되지 않음 — 반영된 모습은 '기각 사유 반영'·'반영된 연구자 결정'에서" |
| 안내 바 ④ "제안 기각해보기 (데모: 읽기 전용)" | 할 수 없는 일을 권했다 | 데모에서는 **"결정·기각 사유 보기"**(같은 위치로 이동) |
| reference 데모의 Protocols | "저장된 프로토콜이 없습니다"만 | "버전 계보는 lab 시나리오에 있습니다 [lab으로 전환]" |

관련 파일: `backend/app/scripts/export_scenario.py`(+ 테스트 2건), `frontend/src/api/demo.ts`(+ 테스트 2건),
`components/QueryState.tsx`(+ 테스트 1건), 각 탭의 오류 표시 6곳.

### 2.3 처음 보는 사람의 경로

- 안내 바 문구에 제품의 핵심(연구자가 기각한 이유를 AI가 기억해 다음 제안을 바꾼다)이 빠져 있었다 → 추가.
- 390px에서 탭 줄이 가로 스크롤인데 활성 탭이 화면 밖에 남았다(안내 바 ③을 누르면 "Research AI" 탭이 잘린 채
  보이지 않음) → 활성 탭을 탭 줄 안으로 스크롤.
- README 맨 위에 "3분뿐이라면 안내 바 ①→④"를 한 줄 추가.

### 2.4 문서

| 문서 | 어긋난 것 | 고친 것 |
|---|---|---|
| README | Protocols 탭이 **어디에도 없었다**("탭 5개"로 서술). 성능·보안 작업 언급 없음. 데모에서 되는 것/안 되는 것 불명확 | §3에 Protocols 화면 2개, §4 탭 6개·ELN/Analysis 표·wiring 행, §5 "규모와 견고성은 측정했다"(PERFORMANCE·SECURITY_REVIEW 요약), §6에 Protocols 단계(5) 추가, 데모에서 되는 것 명시 |
| ARCHITECTURE | §2 소유 테이블 절반 누락(eln 10개 중 6개, memory 3개 중 1개, partner 6개 중 4개, analysis 기준 버전), core `grounding`·wiring 없음, §3에 **openapi 경로 18개 누락**, §4 탭 목록에 데모 어댑터·안내 바 없음, §5가 존재하지 않는 `seed.json`을 원본으로 지목, lab 프로파일 없음 | 전부 반영. §3은 82개 경로 전부와 일치(스크립트 확인). 불변 엔티티 표는 `ImmutableMixin` 사용 모델과 대조 |
| ISSUES | ★1이 "결정 필요"인데 P1-4에서 이미 결정됨, P2-6(ARCHITECTURE 갱신)이 열린 채, 검증 상태 표의 수치가 옛 값(pytest 408, vitest 80) | 결정됨·완료로 표시, 검증 표를 이번 실행 결과로 교체 |
| CHANGES_REQUESTED | "ARCHITECTURE.md 갱신" OPEN | DONE |

README §6의 1~6단계는 lab 데모에서 전부 확인했다: #024 조건 2개·62.0%, #018 비교, "현재 데이터로 확정 불가"와
"반영된 연구자 결정"(인력 사유), #OA06 "과거에 같은 증상이 있었다"·PSA 사용 이력, Records #029/#030·기록 공백,
실패 아카이브 #014→#016·MgSO4, Protocols v1/v1.1 4/4·v2 불합격 #024·#026·#028·예시 추출 "13개 중 10개",
Overview `#OA02` 검색 → #011 테일링 메모.

## 3. 마지막 전체 검증 (이 세션, 이 커밋 기준)

| 검사 | 결과 |
|---|---|
| backend `ruff check` · `ruff format --check` | 통과 |
| backend `mypy app` (strict) | 통과 (86 파일) |
| backend `pytest` | 510 passed, 실패·건너뜀·xfail 0 (이번에 추가 2: 리포트 기록, 예시 원문 추출) |
| `python -m app.scripts.export_openapi --check` | 통과 (API 계약 변경 없음) |
| `alembic upgrade head && alembic check` (새 DB) | 통과 ("No new upgrade operations detected") |
| `pip-audit --skip-editable` | 통과 (CI 수정 후 재현 포함, §2.1) |
| frontend `npm run check:api` | 통과 |
| frontend `tsc` (typecheck) | 통과 |
| frontend `vitest` | 통과 — 19 파일 88 테스트 (이번에 추가 3: 데모 리포트 재생·예시 추출, ErrorState 데모 안내) |
| frontend `npm run build` · `npm run build:demo` | 통과 |
| Playwright e2e (`npm run e2e`, 실제 백엔드 reference + lab) | 통과 — 7 passed (reference 1 + lab 4 + protocols·lab 2). CI에서는 §2.1 때문에 그동안 건너뛰어졌다 |
| 데모 87화면 순회 (§1) | 가로 스크롤 0, 페이지 예외 0, 앱 콘솔 오류 0 (딥 링크의 HTTP 404 문서 응답은 §5) |

## 4. 제출 전에 태균이 직접 판단·확인할 것

1. **푸시 후 CI가 초록색인지 확인.** 이 세션은 Actions를 실행할 수 없다. 푸시 직후 GitHub Actions 결과는 아래 §6에 적었다.
   `pip-audit` 외에 그동안 건너뛰어진 Alembic·e2e 잡이 CI에서 처음으로 다시 돈다(로컬에서는 둘 다 통과).
2. **라이브 데모를 직접 열어 볼 것.** Pages 배포 워크플로는 매번 성공했지만, 이 세션의 네트워크에서는
   `lifst-coder.github.io`에 접속할 수 없어 배포된 페이지 자체는 보지 못했다(로컬에서 같은 빌드로 확인).
   lab 시나리오 파일은 14.6 MB(gzip 1.8 MB)라 첫 로딩에 1~3초 걸릴 수 있다.
3. **열린 Dependabot PR 2개(vitest 5, react-router-dom 7)가 CI 실패 상태다.** 주요 버전 올림이라 코드 수정이 필요하다.
   심사 기간에 저장소의 Pull requests 탭에 실패한 PR이 보이는 것이 괜찮은지 — 닫을지(SECURITY_REVIEW §2에서 런타임
   영향 없음으로 판단) 그대로 둘지 결정.
4. **데모는 항상 "규칙 모드"다.** Claude 생성 모드는 API 키가 있어야 하고 데모는 정적 파일이라 보여줄 수 없다.
   설계상 의도(규칙 모드가 기본, 같은 스키마)이고 README에 적혀 있지만, 심사위원이 "AI 연구 파트너"에서 LLM 출력을
   기대할 수 있다. Claude 모드 화면 캡처나 짧은 영상을 README에 추가할지 판단.
5. **ISSUES.md의 P2 항목(기능 완성 백로그)이 공개 저장소에 그대로 남아 있다.** 솔직한 한계 기록으로 둘지, 제출용으로
   요약할지 판단. 내용은 사실과 맞게 정리해 두었다.

## 5. 고치지 않고 남긴 것과 이유

| 항목 | 이유 |
|---|---|
| GitHub Pages 딥 링크(`/biopilot/notebook?...`)를 새로 열면 문서가 **HTTP 404 상태**로 오고(내용은 `404.html` = 앱이라 정상 렌더링) 콘솔에 "Failed to load resource 404" 1줄 | Pages의 SPA 표준 우회법의 한계. 없애려면 HashRouter로 바꿔야 해서 URL 구조 변경(큰 구조 변경 금지). README 링크는 루트(`?scenario=`)라 해당 없음 |
| 데모에서 미리 계산하지 않은 검색어·비교 쌍·자유 질문은 "데모 · 읽기 전용 / 저장되지 않은 조합" 안내 | 정적 데모의 본질(ISSUES P2-17). 추천 경로의 조합은 전부 들어 있다 |
| Overview 진입 시 Research Partner 패널 컨텍스트는 가장 최근 실험(#030)인데 "지금 봐야 할 것" 카드는 #024 | 선택 규칙(`?exp=` 없으면 최근 실험)은 탭 전체의 공용 동작이라 이번 범위에서 바꾸지 않았다. 안내 바 ①을 누르면 일치 |
| 실패한 쓰기의 안내는 다른 실험으로 바꿔도 그 화면에 남는다(예: "프로젝트 수준 검토" 안내) | 무해하고 새로 고치면 사라진다 |
| Overview 타임라인의 변경 배지가 390px에서 조건 키 원문(`cleanup_sorbent`)으로 표시되고 칸 안에서 잘린다 | 가로 스크롤은 없고 정보는 Notebook에 라벨로 있다. 문구 수준을 넘는 표 레이아웃 변경이라 남김 |
| 데모 Partner 답변의 "비판 #33" 배지가 스냅샷에 없는 비판 번호 | 답변을 DB 사본에서 계산하기 때문(스냅샷 불변 유지가 목적). 링크가 아닌 배지라 이동 오류는 없다 |
| ISSUES P2/P3 백로그(첨부 시드, ConditionBlock 정식 필드, Records의 부분 일치 비교 등) | 기능 추가라 마지막 점검 범위 밖 |
| PERFORMANCE의 2초 미달 2건(지식 그래프 첫 구성 3.4 s, 실패 아카이브 2.0 s) | 응답 크기·지표 저장 방식에 대한 결정이 필요(PERFORMANCE §8). 데모(42개 실험)에는 영향 없음 |
| 인증·rate limit | 의도적 범위 밖(README "무엇을 의도적으로 만들지 않았나", SECURITY_REVIEW §10) |

## 6. 푸시 후 CI

(푸시 후 갱신)
