# TASKS

다음 세션들이 집어갈 디테일 작업. **한 세션 = 한 영역**(CLAUDE.md §3 병렬 작업 규칙).
작업을 집으면 상태를 `[ ]` → `[~] (세션/날짜)`로, 끝나면 `[x]`로 바꾼다.
모든 작업의 공통 완료 기준: ruff·mypy·pytest·typecheck·build 통과, 새 코드에 타입·docstring·테스트,
API 변경 시 `openapi.json`/`schema.d.ts` 재생성, 새 쓰기 경로는 AuditEvent 기록.

---

## ELN (`backend/app/eln/**`, `frontend/src/features/notebook/**`)

- [x] **ELN-1 파일 업로드(multipart) 데이터셋 수집**
  `POST /api/eln/experiments/{id}/datasets/upload` (multipart, UTF-8/CP949 자동 판별, 최대 크기 제한).
  완료 기준: 기존 JSON 업로드와 같은 검증·sha256·감사 이벤트; 잘못된 인코딩/크기 초과 시 400 테스트.
- [x] **ELN-2 실험 보충 기록(Addendum)**
  원본을 고치지 않고 `ExperimentAddendum{experiment_id, note, author, created_at}`(불변)을 추가하는 엔드포인트.
  완료 기준: `ExperimentOut.addenda[]` 노출, 원본 raw_note 불변 테스트, 감사 이벤트.
- [x] **ELN-3 제목/작성자 변경 API + 감사**
  현재 title/author는 ORM상 변경 가능하지만 API·감사가 없다. `PATCH /api/eln/experiments/{id}/metadata`.
  완료 기준: 변경 전/후 값을 AuditEvent payload에 기록, 불변 필드 포함 시 409.
- [x] **ELN-4 첨부파일 바이너리 저장**
  attachments는 현재 메타데이터만. 파일 저장소(로컬 디렉터리, sha256 이름) + 다운로드 엔드포인트.
  완료 기준: 업로드 후 sha256 일치, 동일 파일 재업로드 시 중복 저장 없음, 삭제 엔드포인트 없음.
- [x] **ELN-5 프로젝트별 조건 블록 템플릿**
  필수 키·단위·허용 범위를 프로젝트에 정의하고 실험 생성 시 검증(경고 vs 오류 구분).
  완료 기준: 템플릿 위반 시 400(오류) 또는 `warnings[]`(경고) 응답, 시드 프로젝트 템플릿 포함.
- [x] **ELN-6 목록 페이지네이션·필터**
  `list_experiments`에 `limit/offset`, 기간, 작성자, dataset_kind 필터.
  완료 기준: 기존 응답 형태 유지(필드 추가만), 경계값 테스트.
- [x] **ELN-7 데이터셋 종류 레지스트리 확장**
  `DATASET_COLUMNS`를 버전 있는 레지스트리로(`kind@version`), 신규 kind `ion_ratio`(qualifier/quantifier 면적).
  완료 기준: 기존 kind 하위호환, Analysis 담당에 CHANGES_REQUESTED로 계약 공지.
- [x] **ELN-8 Notebook: 실험 생성 폼 + CSV 업로드 UI**
  조건 블록 편집기(조건 라벨은 `/api/eln/condition-fields`), 부모 실험 선택, CSV 드래그&드롭.
  완료 기준: 생성 후 목록 갱신, 서버 검증 오류 표시, 컴포넌트 테스트.
- [x] **ELN-9 장비 내보내기 형식 변환기**
  벤더 CSV(wide 형식)를 long 형식 계약으로 변환하는 순수 함수 + 미리보기 엔드포인트.
  완료 기준: 샘플 파일 2종 변환 테스트, 원본 파일도 그대로 보관.

## Memory (`backend/app/memory/**`)

- [ ] **MEM-1 계보 외 관계 엣지**
  `shares_conditions`(조건 유사도 ≥ 임계), `tests_proposal`(Proposal → 후속 실험) 엣지 추가.
  완료 기준: `GraphEdge.relation` enum 확장(기존 값 유지), 유사도 계산 단위 테스트.
- [ ] **MEM-2 조건 키별 이력**
  `GET /api/memory/projects/{id}/conditions/{key}/history` — 실험별 값 변화 타임라인.
  완료 기준: 시드에서 `extraction_time_min` 이력이 10→5로 나타남, 키 미존재 시 빈 배열.
- [ ] **MEM-3 FTS5 전문 검색**
  SQLite FTS5 인덱스로 메모·정리본·비판 요약 검색, 랭킹·하이라이트.
  완료 기준: 기존 `/search` 계약 유지 + `score` 필드 추가, 한국어 부분일치 테스트.
- [ ] **MEM-4 단어 단위 메모 diff**
  줄 diff에 더해 변경 줄 내부 단어 diff(`NoteDiffLine.segments[]`).
  완료 기준: 숫자·단위 변경("10분"→"5분")이 segment로 잡히는 테스트.
- [ ] **MEM-5 N-way 조건 비교 매트릭스**
  `GET /api/memory/compare-conditions?ids=1,2,7` — 키 × 실험 행렬, 변하는 키만 필터 옵션.
  완료 기준: 시드 7개 실험 매트릭스 테스트, 프론트 사용을 위해 Frontend에 공지.
- [ ] **MEM-6 Claude 정리본 근거 검증**
  Partner의 `ungrounded_numbers`와 동일한 원칙: 정리본에 원본에 없는 숫자가 있으면 규칙 모드 대체.
  완료 기준: FakeGateway로 거짓 숫자 주입 시 rules로 대체되는 테스트, `DigestOut.fallback_reason` 추가.
- [ ] **MEM-7 연구자 지식 노트**
  프로젝트 수준 `KnowledgeNote{statement, linked_experiment_ids, author}`(불변 + 감사), 검색 대상 포함.
  완료 기준: CRUD 중 생성/조회만, 연결된 실험 존재 검증.
- [ ] **MEM-8 정리본 최신성**
  데이터셋 추가 등으로 정리본이 오래되면 `stale=true` 표시(입력 지문 비교).
  완료 기준: 데이터셋 추가 후 기존 정리본 stale 테스트.

## Analysis (`backend/app/analysis/**`, `frontend/src/features/analysis/**`)

- [ ] **ANA-1 LOD/LOQ 추정**
  검량선 절편 표준편차 기반(3.3σ/S, 10σ/S) + 저농도 반복 기반 옵션. 새 result kind `limits`.
  완료 기준: 손계산 가능한 단위 테스트, `METHOD_VERSIONS` 등록, 시드 #023에서 값 생성.
- [ ] **ANA-2 매트릭스 매칭 검량선 정량**
  조건 블록 `calibration_type=matrix-matched`일 때 해당 곡선으로 회수율 계산.
  완료 기준: 용매/매트릭스 곡선 선택 로직 테스트, 파라미터가 fingerprint에 포함.
- [ ] **ANA-3 이상치 검정(Grubbs)**
  반복 측정 그룹별 Grubbs 검정 결과를 플래그로만 제공(데이터 제거 금지).
  완료 기준: 알려진 이상치 데이터 단위 테스트, `QCFlag.code="outlier_suspected"`.
- [ ] **ANA-4 측정 불확도**
  반복성 RSD + 회수율 편향으로 확장 불확도(k=2) 계산.
  완료 기준: 수식 docstring + 단위 테스트, `ExperimentMetrics`에 필드 추가.
- [ ] **ANA-5 가중 선택 근거 강화**
  Σ|%RE| 외에 잔차 이분산성 F-검정 결과 제공.
  완료 기준: #023에서 무가중 대비 1/x 선택 근거가 F-검정으로도 지지되는 테스트.
- [ ] **ANA-6 프로젝트별 허용 기준 저장**
  `AcceptanceCriteria`를 프로젝트별 버전 레코드로 저장, 결과 플래그에 사용 기준 버전 기록.
  완료 기준: 기준 변경 시 기존 결과 불변, 재분석 시 새 결과 생성.
- [ ] **ANA-7 분석물별 비교 + 다중비교 보정**
  `compare`에 분석물별 Welch t-test + Holm 보정 p-value.
  완료 기준: 시드 #018 vs #024에서 carbendazim/thiabendazole 유의 테스트.
- [ ] **ANA-8 이온비(qualifier/quantifier) QC**
  ELN-7의 `ion_ratio` kind 소비, 기준 ±30% 플래그.
  완료 기준: ELN-7 완료 후 진행, 결과 kind `ion_ratio`.
- [ ] **ANA-9 Analysis 탭: 잔차 플롯·원시 행 테이블**
  검량선 잔차(%RE) 차트, 회수율 rows 테이블(주입 ID 필터).
  완료 기준: 모든 값은 API 필드 그대로 표시, 프론트 계산 없음.

## Partner (`backend/app/partner/**`, `frontend/src/features/{research-ai,partner-panel}/**`)

- [ ] **PAR-1 가설 상태 전이 API**
  `POST /api/partner/hypotheses/{id}/status {status, rationale, evidence_result_ids}` (proposed→open→supported/refuted).
  완료 기준: 허용되지 않는 전이 400, 감사 이벤트에 전/후 상태.
- [ ] **PAR-2 수락된 제안 → 실험 초안**
  `GET /api/partner/proposals/{id}/experiment-draft` — 기준 실험 조건 + 변경 적용한 `ExperimentCreate` 초안 반환(생성은 ELN 화면에서).
  완료 기준: modify 결정이면 modifications 우선 적용, 초안은 저장하지 않음.
- [ ] **PAR-3 Claude 모드 평가 세트**
  시드 7개 실험 × 기대 지적 목록으로 Claude 출력 평가 스크립트(근거 통과율, 기대 지적 재현율).
  완료 기준: `scripts/eval_partner.py`, API 키 없으면 skip, 결과 리포트 JSON.
- [ ] **PAR-4 Q&A 기록 저장**
  `PartnerExchange{question, answer, engine, evidence}`(불변 + 감사), 패널에 대화 이력.
  완료 기준: 실험별 이력 조회 엔드포인트, 패널 표시.
- [ ] **PAR-5 규칙 확장**
  RSD 초과, R² 미달, ME 유의인데 용매 검량선 사용, pH 민감 분석물 표 등 규칙 추가(표 기반).
  완료 기준: 규칙별 단위 테스트, 모든 출력이 `ungrounded_numbers == []`.
- [ ] **PAR-6 근거 검증기 고도화**
  `%`/`%p` 단위 구분, 천 단위 구분자, 한국어 수사("세 번") 처리, 근거 값과 반올림 허용오차.
  완료 기준: 엣지케이스 테스트 10개 이상.
- [ ] **PAR-7 프로젝트 수준 비판**
  전 실험 추이 기반 비판(예: "회수율 저하가 GCB 도입 실험에만 나타남").
  완료 기준: `POST /api/partner/projects/{id}/critiques`, 동일 CritiqueDraft 스키마.
- [ ] **PAR-8 제안 우선순위**
  결정론적 휴리스틱(교란 해소 여부, 기준 미달 분석물 수)으로 `priority` 점수 — 숫자는 Evidence 기반.
  완료 기준: 시드 #024 제안 정렬 테스트.
- [ ] **PAR-9 Claude 스트리밍 답변**
  `/ask`의 Claude 모드 SSE 스트리밍(최종 검증 후 확정, 실패 시 규칙 답변으로 교체).
  완료 기준: 규칙 모드 응답 계약 불변, 스트림 종료 이벤트에 evidence 포함.

## Frontend (`frontend/src/{layout,components,lib,styles}/**`, `features/overview/**`)

- [ ] **FE-1 계보 그래프 시각화**
  `/api/memory/projects/{id}/graph`로 Overview에 실험 계보 그래프(노드 클릭 → `?exp=`).
  완료 기준: 7노드/6엣지 렌더, 키보드 포커스 가능.
- [ ] **FE-2 오류 경계 + 토스트**
  라우트별 ErrorBoundary, mutation 성공/실패 토스트, 409(불변 위반)·400 메시지 매핑.
  완료 기준: 컴포넌트 테스트, 공통 `useToast`.
- [ ] **FE-3 API 모킹 컴포넌트 테스트**
  MSW로 각 탭 렌더 테스트(시드 응답 픽스처는 실제 API에서 덤프).
  완료 기준: 4탭 + 패널 렌더 테스트가 `npm test`에 포함.
- [ ] **FE-4 E2E 스모크(Playwright) CI 잡**
  백엔드 + 프론트 기동 후 4탭 진입, 비판 실행, 결정 기록 시나리오.
  완료 기준: GitHub Actions 잡 추가(CI 파일은 공유 파일 → CHANGES_REQUESTED 경유), 콘솔 에러 0.
- [ ] **FE-5 반응형 레이아웃**
  1280px 미만에서 Partner 패널 접기/서랍, 모바일 탭 스크롤.
  완료 기준: 3개 뷰포트 스크린샷 비교, 가로 스크롤 없음.
- [ ] **FE-6 다크 모드 토큰**
  `tokens.css`에 `[data-theme=dark]` 세트, 차트 색 포함.
  완료 기준: WCAG AA 대비 확인 스크립트 통과.
- [ ] **FE-7 접근성 점검**
  탭 `role=tablist`, 포커스 링, 표 헤더 scope, 차트 대체 텍스트(데이터 테이블 토글).
  완료 기준: axe-core 위반 0 (테스트로 실행).
- [ ] **FE-8 감사 로그 화면/필터**
  Overview 감사 로그에 주체·엔티티 필터와 페이지네이션, payload 상세 보기.
  완료 기준: `/api/audit` 파라미터만 사용, 필터 상태 URL 반영.
- [ ] **FE-9 번들 최적화**
  Recharts 분리 청크, 탭 프리페치.
  완료 기준: 초기 JS < 250 kB gzip, 빌드 경고 없음.
