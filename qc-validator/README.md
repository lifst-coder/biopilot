# BioPilot QC Validator — LC-MS/MS 정량 데이터 품질 검증 도구

장비에서 내보낸 정량 결과 파일 하나로 검량선과 QC를 계산·판정하고, 이상 항목마다 관측 사실과 원인 가설을 나눠 정리한다.
서버 없이 브라우저에서만 동작하는 독립 도구이며, 검증한 배치의 원자료를 BioPilot 본편(ELN)의 데이터셋 형식으로 내보낸다.

## 본편과의 관계

BioPilot 본편은 실험 기록을 쌓고 왜 그렇게 했는지를 기억하는 시스템이다. 이 도구는 그 앞 단계, 즉 **한 배치의 정량 결과를 믿을 수 있는지 빠르게 확인하는 일**을 맡는다.

| | 본편 (`backend/`, `frontend/`) | QC Validator (`qc-validator/`) |
|---|---|---|
| 실행 | FastAPI + React, DB에 기록 | `dist/index.html` 하나, 서버·설치 없음 |
| 입력 | 실험별 데이터셋(calibration, recovery …) | 한 배치 전체가 든 파일 하나(긴 형식 CSV·XLSX) |
| 계산 | Python (L3 Analysis) | JavaScript (같은 가중 회귀 식, 본편 Python 계산과 대조 검증) |
| 점검 항목 | 검량선, 회수율, IS 응답, 매트릭스 효과, LOD/LOQ, 이온비, 실험 간 비교 | 검량선 적합성·비선형·이상점, 바탕 오염, QC 정확도, 중복, 첨가 회수율, IS 응답, 머무름 시간, 필수 QC 누락 |
| 기록 | 불변 원본 + 감사 로그 | 브라우저 세션 안의 검토 기록(보고서로 내보냄) |

본편의 원칙은 "화면의 숫자는 저장된 데이터에서 Python 코드가 계산한 값"이다. 그래서 이 도구의 계산 결과는 본편 화면에 쓰이지 않는다.
연결은 한 방향이다: 이 도구가 **원자료만** 본편 계약(`calibration@1`, `recovery@1`)으로 내보내고, 본편이 올린 원본에서 다시 계산한다.
같은 원자료에 대해 두 구현의 기울기·절편·R²·회수율이 일치하는지는 `scripts/verify_eln_bridge.py`로 확인한다.

이 도구에만 있는 점검(바탕, 머무름 시간, 중복, 필수 QC, 검량선 진단)을 본편 L3로 옮기는 일은 [CHANGES_REQUESTED.md](../CHANGES_REQUESTED.md)에 요청으로 남겼다.

## 바로 실행

`dist/index.html`을 브라우저로 연다. 처음 열면 합성 예시 데이터가 들어 있다. 파일은 브라우저 안에서만 처리된다.

## 구성

| 경로 | 내용 |
|---|---|
| `src/stats.js` | 결정론적 통계: 평균·RSD·RPD·회수율, 가중 회귀, 곡률 F 검정, t 분포 |
| `src/parse.js` | CSV·XLSX 판독(의존성 없음), 컬럼 매핑, 값 검증(값을 채우지 않음) |
| `src/rules.js` | 설정 가능한 QC 기준과 예시 기준 묶음, 출처 |
| `src/calibration.js` | 검량선: 내부·외부표준법, 가중 회귀, 역산, 적합성 판정, 비선형·이상점·설정 진단 |
| `src/qc.js` | QC 검증: 바탕, QC 시료, 중복, 첨가 회수율, 내부표준, 머무름 시간, 필수 QC |
| `src/analyze.js` | 배치·분석물별 실행과 결과 집계 |
| `src/diagnose.js` | 규칙 기반 원인 진단(관측 사실 / 가설 / 확인 / 검증, 원인 미확정) |
| `src/llm.js` | LLM 프롬프트 구성과 응답 검사(수치·단정 표현) |
| `src/report.js` | 보고서 JSON·HTML·CSV |
| `src/eln.js` | 본편 ELN 데이터셋 형식으로 원자료 내보내기 |
| `src/synth.js` | 합성 데이터 생성기와 오류 시나리오 정답표 |
| `src/app.js`, `charts.js`, `styles.css`, `page.html` | 화면 6개 |
| `data/` | 테스트용 CSV·XLSX, 시나리오별 파일, `answer_key.json`, 파싱 시험 입력 |
| `tests/` | 단위·통합 시험(`*.test.mjs`), 브라우저 시험(`browser.mjs`) |
| `docs/` | QC 규칙 명세, 오류 탐지 보고서, 설치 및 사용 설명서, 확장 설계 |
| `dist/index.html` | 빌드 결과(커밋함). 소스와 일치하는지 `tests/eln.test.mjs`가 검사 |

## 명령

Node.js 22. 외부 패키지 없음.

```
cd qc-validator
node --test tests/*.test.mjs     # 단위·통합 시험
node scripts/build.mjs           # dist/index.html 다시 만들기 (소스를 고치면 반드시 실행)
node tests/browser.mjs           # 브라우저 시험 (Chrome 또는 Edge, CHROME_PATH로 경로 지정 가능)
node scripts/evaluate.mjs 300    # 합성 데이터 오탐·미탐 평가
node scripts/gen-data.mjs        # 합성 CSV·정답표 재생성
node scripts/gen-docs.mjs 300    # docs/ 재생성
node scripts/eln-export.mjs data/scenarios/S4_B04-SPIKE.csv B04-SPIKE out/   # 본편 형식으로 내보내기
```

본편 코드와 대조(저장소 루트에서, backend 가상환경 필요):

```
backend/.venv/bin/python qc-validator/scripts/verify_eln_bridge.py out/ B04-SPIKE
```

## 설계 원칙

- **계산과 해석의 분리**: 검량선과 QC 계산은 결정론적 함수가 한다. LLM은 계산 결과를 읽기 전용으로 받아 요약과 가설만 쓰고, 돌아온 글은 계산 결과에 없는 수치와 단정 표현을 자동 검사한다.
- **R²만으로 판정하지 않는다**: 검량점별 역산 정확도, 농도 수준 수, 범위 끝점으로 판정한다.
- **기준은 설정값이다**: 기본값은 예시이며 화면에서 바꾼다. 출처는 `docs/QC-규칙-명세.md`.
- **값을 채우지 않는다**: 읽을 수 없는 값, 없는 열은 "평가 불가"로 보고한다.
- **원인을 확정하지 않는다**: 진단의 결론은 항상 "원인 미확정"이며 구별에 필요한 확인 절차를 제시한다.

## 알아 둘 한계

- 합성 데이터로만 검증했다. 실제 기관 데이터로는 시험하지 않았다.
- 한 행이 한 주입의 한 분석물인 긴 형식만 지원한다. 구형 .xls와 넓은 형식은 지원하지 않는다.
- 직선 모형만 정량에 쓴다. 2차 모형은 비선형성 진단에만 쓴다.
- LLM 연결은 Claude Artifact로 게시했을 때만 동작하고, 실제 호출은 자동 시험에 포함되지 않았다. 로컬에서는 규칙 기반 진단만 동작한다.
- CI와 GitHub Pages에는 아직 연결되지 않았다(공유 파일이라 [CHANGES_REQUESTED.md](../CHANGES_REQUESTED.md)에 요청으로 남김). 시험은 위 명령으로 직접 실행한다.
