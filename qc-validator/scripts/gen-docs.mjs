// BIOPILOT — 문서 생성기. 규칙 명세와 오류 탐지 보고서의 수치는 엔진과 시험을 실제로 실행해 채운다.  node scripts/gen-docs.mjs [seed 수]
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { RULE_META, PROFILES, defaultRules, profileRules, getRule, ruleText } from '../src/rules.js';
import { CODES } from '../src/qc.js';
import { FIELDS, TYPES } from '../src/parse.js';
import { WEIGHTINGS, WEIGHTING_LABEL } from '../src/stats.js';
import { OUTLIER_ALPHA } from '../src/calibration.js';
import { ENGINE_VERSION } from '../src/analyze.js';
import { SCENARIOS, generateDataset, CAL_LEVELS, QC_LEVELS, ANALYTES } from '../src/synth.js';
import { runRows, scoreScenario } from '../src/pipeline.js';
import { diagnose } from '../src/diagnose.js';
import { evaluate } from './evaluate.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..'); mkdirSync(join(root, 'docs'), { recursive: true });
const out = (name, text) => { writeFileSync(join(root, 'docs', name), text.replace(/\n{3,}/g, '\n\n')); console.log('docs/' + name); };
const today = new Date().toISOString().slice(0, 10);
const head = t => '# ' + t + '\n\nBIOPILOT · 분석 엔진 v' + ENGINE_VERSION + ' · 생성일 ' + today + ' · `node scripts/gen-docs.mjs`가 만든 문서다.\n\n';
const table = (h, rows) => '| ' + h.join(' | ') + ' |\n|' + h.map(() => '---').join('|') + '|\n' + rows.map(r => '| ' + r.map(c => String(c).replace(/\|/g, '/').replace(/\n/g, ' ')).join(' | ') + ' |').join('\n') + '\n';
const R = defaultRules();

// ───────────── QC 규칙 명세 ─────────────
{
  let t = head('QC 규칙 명세');
  t += '> **모든 기본값은 예시 기준이다.** 허용 기준은 장비·분석법·규격·SOP에 따라 다르다. 실제 판정에는 해당 분석법의 값을 QC Review 화면의 "QC 기준 설정"에 입력해야 한다. 아래 출처는 2026-11에 원문에서 확인한 조항이며, "출처 없음"으로 표시한 값은 이 도구가 정한 진단용 값이다.\n\n';
  t += '## 1. 설정 가능한 규칙\n\n' + table(['구분', '규칙 키', '항목', '기본값', '허용 입력', '출처·비고'], RULE_META.map(m => [m.group, '`' + m.path + '`', m.label, ruleText(R, m.path), m.bool ? '켬/끔' : m.options ? m.options.map(o => o[1]).join(' / ') : m.min + ' – ' + m.max + (m.int ? ' (정수)' : ''), m.source]));
  t += '\n잘못된 입력(숫자가 아님, 범위 밖, 정수가 아님)은 거부되고 기존 값이 유지된다. 값을 바꾸면 즉시 다시 판정하며 검토 기록에 "이전 값 → 새 값"이 남는다.\n\n';
  t += '## 2. 기준 묶음(프로파일)\n\n모두 예시이며 출발점으로만 쓴다.\n\n';
  const diffKeys = RULE_META.filter(m => Object.keys(PROFILES).some(id => getRule(profileRules(id), m.path) !== getRule(R, m.path)));
  t += table(['항목'].concat(Object.keys(PROFILES).map(id => PROFILES[id].name)), diffKeys.map(m => [m.label].concat(Object.keys(PROFILES).map(id => ruleText(profileRules(id), m.path)))));
  t += '\n' + Object.keys(PROFILES).map(id => '- **' + PROFILES[id].name + '**: ' + PROFILES[id].note).join('\n') + '\n\n';
  t += '## 3. 계산식\n\n모든 계산은 `src/stats.js`, `src/calibration.js`, `src/qc.js`의 결정론적 함수가 수행한다. LLM은 계산에 관여하지 않는다.\n\n';
  t += table(['항목', '식', '비고'], [
    ['응답값', '내부표준법: 분석물 면적 / 내부표준 면적. 외부표준법: 분석물 면적', '내부표준 면적이 없거나 0 이하이면 응답값 없음'],
    ['가중 선형 회귀', '응답 = 기울기 × 농도 + 절편, Σw(y − ŷ)² 최소화', '가중치 ' + WEIGHTINGS.map(w => WEIGHTING_LABEL[w]).join(', ') + '. 기본 1/x²'],
    ['결정계수 R²', '1 − Σw(y − ŷ)² / Σw(y − ȳw)²', '참고값. 단독으로 적합을 판정하지 않는다'],
    ['역산 농도', '(응답 − 절편) / 기울기', ''],
    ['검량점 편차', '(역산 농도 − 명목 농도) / 명목 농도 × 100', '최저 수준에는 LLOQ 허용 편차 적용'],
    ['최종 농도', '장비 측정 농도 × 희석배수', '희석배수가 없으면 계산하지 않는다(사용자가 "1로 간주"를 켠 경우 제외)'],
    ['평균, 표준편차', '표본 표준편차(n − 1)', 'n < 2이면 표준편차 없음'],
    ['RSD(%)', '표준편차 / 평균 × 100', ''],
    ['상대오차(%)', '(측정 − 명목) / 명목 × 100', 'QC 정확도'],
    ['RPD(%)', '|a − b| / ((a + b)/2) × 100', '2회 측정. 3회 이상은 RSD'],
    ['회수율(%)', '(측정 농도 − 원시료 농도) / 첨가 농도 × 100', '원시료가 연결되지 않으면 원시료 농도 0(바탕 첨가 방식)'],
    ['바탕(응답 방식)', '바탕 시료의 분석물 면적 / LLOQ 표준의 평균 분석물 면적 × 100', ''],
    ['내부표준 응답(%)', '내부표준 면적 / 검량 표준의 평균 내부표준 면적 × 100', ''],
    ['머무름 시간 차이', '머무름 시간 − 검량 표준의 평균 머무름 시간', ''],
    ['추세', '주입 순서에 대한 단순 선형 회귀의 기울기와 p값', '주입 순서 열이 없으면 행 순서를 쓰고 그 사실을 표시'],
  ]);
  t += '\n기준값과 비교할 때는 부동소수점 오차 때문에 경계값(예: 정확히 15.0%)이 뒤집히지 않도록 10⁻⁹ 수준의 여유를 둔다. 경계값은 "기준 내"다.\n\n';
  t += '## 4. 검량선 적합성 판정\n\nR²만으로 판정하지 않는다. 다음을 모두 충족해야 "적합"이다.\n\n1. 농도 수준 수 ≥ `cal.minLevels`\n2. 기준 내 검량점 비율 ≥ `cal.minPassPct` (각 점 ±`cal.devPct`%, 최저 수준 ±`cal.devPctLloq`%)\n3. 기준 내 농도 수준 수 ≥ `cal.minLevels` (한 수준의 반복 중 절반 이상이 기준 내이면 그 수준은 적합)\n4. 최저 수준(LLOQ)과 최고 수준(ULOQ)이 각각 적합\n5. 기울기 > 0\n6. `cal.useR2`를 켠 경우에만 R² ≥ `cal.r2Min`\n\n명목 농도가 0인 표준은 회귀에 넣지 않는다. 도구는 검량점을 스스로 제외하지 않는다. 제외는 사용자가 사유를 적어야만 가능하고 검토 기록에 남는다.\n\n### 진단(판정과 별개)\n\n';
  t += '- **비선형성**: 같은 가중치로 직선과 2차식을 적합해 F 검정. p < `cal.alpha`이고, 최고 농도에서 2차 항이 1차 항의 `cal.curvatureMinPct`% 이상이며, 최대 역산 편차가 허용 편차의 2/3 이상일 때 경고한다. 2차식은 진단에만 쓰고 정량에는 쓰지 않는다.\n- **이상점 후보**: 기준을 벗어난 점 가운데 외적 스튜던트화 잔차의 본페로니 보정 p < ' + OUTLIER_ALPHA + '이거나, 그 점을 빼고 적합했을 때 나머지가 모두 기준 내이고 그 점의 편차가 허용 편차의 2배를 넘는 경우.\n- **끝점의 모호성**: 이상점 후보가 최저·최고 수준이고 전체 곡률이 유의하면 비선형성으로 보고한다. 끝점 하나만 벗어난 경우 포화와 단일 이상점은 이 데이터로 구별되지 않으며, 진단 문구에 그렇게 적는다.\n- **설정 점검**: 내부표준법인데 내부표준 면적 없음, 기울기 음수, 수준 라벨과 명목 농도 불일치, 적용할 수 없는 가중치, 선택한 가중치에서만 저농도가 벗어나는 경우, 검량점 부족.\n\n';
  t += '## 5. 오류 유형 코드\n\n' + table(['코드', '오류 유형'], Object.keys(CODES).map(k => ['`' + k + '`', CODES[k]]));
  t += '\n판정 단계: **기준 미충족**(설정된 기준을 벗어남), **주의**(기준은 충족하지만 진단 경고), **참고**(평가 불가, 사용자 조작 기록 등).\n\n';
  t += '## 6. 입력 필드와 시료 유형\n\n' + table(['필드', '한글', '필수', '자동 인식하는 머리글 예'], FIELDS.map(f => [f.label, f.ko, f.required ? (f.constantOk ? '필수(고정값 입력 가능)' : '필수') : '선택', f.syn.slice(0, 6).join(', ')]));
  t += '\n한 행은 한 주입의 한 분석물이다(긴 형식). 시료 유형: ' + Object.keys(TYPES).map(k => TYPES[k]).join(', ') + '. 인식하지 못한 유형 값은 추측하지 않고 Data Import 화면에서 사용자가 지정한다.\n\n';
  t += '### 시료 연결 규칙\n\n- **중복 시료**: 원시료 ID 열 → 같은 Sample ID → `-DUP` 접미사를 뗀 ID 순서로 원시료를 찾는다. 같은 Sample ID의 미지 시료가 2개면 RPD, 3개 이상이면 RSD로 평가한다.\n- **첨가 시료**: 원시료 ID 열 → `-MS`, `-SPIKE` 접미사를 뗀 ID. 원시료를 찾지 못하면 바탕 첨가 방식으로 계산하고 그 사실을 계산 근거에 적는다.\n- 정량한계 미만 측정이 포함된 중복·반복은 평가하지 않고 "평가 불가"로 보고한다.\n\n';
  t += '## 7. 값을 채우지 않는 원칙\n\n- 숫자가 아닌 값(`N/A`, `<LOQ`, `1,234` 등)은 숫자로 바꾸지 않고 해당 계산에서 제외하며 행 번호를 보고한다.\n- 희석배수, 내부표준 면적, 머무름 시간이 없으면 해당 평가를 "평가 불가"로 둔다.\n- 필수 열이 없으면 분석을 시작하지 않는다.\n- 지원하지 않는 형식(.xls, 암호 보호, 확장자와 내용 불일치)은 오류를 표시하고 기존 데이터를 유지한다.\n';
  out('QC-규칙-명세.md', t);
}

// ───────────── 오류 탐지 보고서 ─────────────
{
  const N = Number(process.argv[2] || 300); const ev = evaluate(N);
  const FILES = ['stats', 'parse', 'calibration', 'qc', 'scenarios', 'llm_report', 'eln'];
  const tests = spawnSync(process.execPath, ['--test', ...FILES.map(n => join(root, 'tests', n + '.test.mjs'))], { encoding: 'utf8' });
  const num = k => { const m = new RegExp('ℹ ' + k + ' (\\d+)').exec(tests.stdout); return m ? Number(m[1]) : null; };
  const perFile = {}; for (const n of FILES) { const r = spawnSync(process.execPath, ['--test', join(root, 'tests', n + '.test.mjs')], { encoding: 'utf8' }); perFile[n] = [Number((/ℹ pass (\d+)/.exec(r.stdout) || [0, 0])[1]), Number((/ℹ tests (\d+)/.exec(r.stdout) || [0, 0])[1])]; }
  let t = head('오류 탐지 보고서');
  t += '## 1. 요약\n\n- 단위·통합 시험: **' + num('pass') + '/' + num('tests') + ' 통과**, 실패 ' + num('fail') + '건 (`node --test tests/*.test.mjs`).\n';
  for (const w of [1280, 400]) { const f = join(root, 'tests', 'last-browser-' + w + '.json'); if (existsSync(f)) { const b = JSON.parse(readFileSync(f, 'utf8')); t += '- 브라우저 통합 시험(헤드리스 Chrome, 요청 폭 ' + w + 'px): ' + b.filter(x => x.ok).length + '/' + b.length + ' 통과. 실제 파일 업로드(CSV, Excel이 저장한 XLSX, CP949 CSV), 오류 파일 거부, 화면 조작, 내보내기를 포함한다.\n'; } }
  const errScn = ev.filter(o => o.id !== 'S0'); const det = errScn.reduce((a, o) => a + o.detected, 0), runs = errScn.reduce((a, o) => a + o.runs, 0); const cleanAll = ev.reduce((a, o) => a + o.clean, 0), runsAll = ev.reduce((a, o) => a + o.runs, 0);
  t += '- 합성 데이터 평가(seed ' + N + '개 × 시나리오 9개): 오류 시나리오 탐지 ' + det + '/' + runs + ' (' + (det / runs * 100).toFixed(1) + '%), 정답표에 없는 경고가 하나도 없는 실행 ' + cleanAll + '/' + runsAll + ' (' + (cleanAll / runsAll * 100).toFixed(1) + '%).\n- 모든 진단 카드의 원인 상태는 "원인 미확정"이다. 합성 시 넣은 실제 원인을 도구가 확정하지 않는 것이 정답이다.\n\n';
  t += '## 2. 시험 구성\n\n' + table(['파일', '통과', '다루는 것'], [
    ['tests/stats.test.mjs', perFile.stats.join('/'), '평균·표준편차·RSD·RPD·회수율, 가중 회귀 5종(NumPy 기준값과 대조), 곡률 F 검정과 t 분포(SciPy 기준값과 대조), 스튜던트화 잔차, 추세'],
    ['tests/parse.test.mjs', perFile.parse.join('/'), 'CSV(따옴표·구분자·BOM), 인코딩(UTF-8·CP949·UTF-16), XLSX(openpyxl 생성본과 Excel 저장본), 지원하지 않는 형식, 컬럼 매핑, 결측·비정상 값, 희석배수 누락, 시료 유형'],
    ['tests/calibration.test.mjs', perFile.calibration.join('/'), '계산 재현, 내부·외부표준법, R²가 높아도 부적합인 경우, 기준 경계와 변경, 이상점·비선형 구별, 잘못된 설정 6종, 0·음수 입력, 사용자 제외, 정량 범위 표시, 분석물·배치 분리'],
    ['tests/qc.test.mjs', perFile.qc.join('/'), '각 QC 기준의 경계값(15.0% 대 15.1% 등), 배치 기준, 바탕 두 방식, 매질 첨가, 중복 연결 3가지, 내부표준·머무름 시간, 필수 QC, 평가 불가 보고, 규칙 입력 검증'],
    ['tests/scenarios.test.mjs', perFile.scenarios.join('/'), '정답표 대비 9개 시나리오, 전체 파일의 배치 분리, 오탐·미탐률(seed 60개), 진단의 사실/가설 분리와 원인 미확정'],
    ['tests/llm_report.test.mjs', perFile.llm_report.join('/'), 'LLM에 넘기는 사실 묶음, 프롬프트 규칙, 가짜 응답으로 수치·단정 표현·잘못된 참조 검사, 보고서 JSON·HTML·CSV'],
    ['tests/eln.test.mjs', perFile.eln.join('/'), 'BioPilot 본편 ELN 계약(calibration@1, recovery@1)으로 내보내기: 열 이름·원자료 보존·옮기지 않는 행의 사유, 커밋된 dist/index.html과 소스의 일치'],
  ]);
  t += '\n본편과의 교차 검증: `scripts/verify_eln_bridge.py`가 내보낸 CSV를 본편의 업로드 검증(`app.eln.service.validate_csv_text`)에 넣고, 본편 L3의 Python 계산(`app.analysis.calculations`)과 이 도구의 기울기·절편·R²·회수율을 상대 오차 10⁻⁹로 대조한다. 2026-11-11에 B04-SPIKE, B02-OUTLIER 두 배치에서 모든 값이 일치했다. 이 대조는 backend 가상환경이 필요해 자동 시험에는 넣지 않았다.\n';
  t += '\n## 3. 합성 데이터\n\n- 분석물 ' + ANALYTES.map(a => a.name).join(', ') + ' (각각 동위원소 표지 내부표준), 검량 수준 ' + CAL_LEVELS.join(', ') + ' ng/mL, QC ' + QC_LEVELS.map(q => q[1]).join(', ') + ' ng/mL × 3회.\n- 배치당 주입: 검량 바탕 3, 검량 표준 8, 방법 바탕 1, QC 9, 바탕 첨가 1, 매질 첨가 1, 미지 시료 10, 중복 2.\n- 잡음: 분석물 면적 CV 2.5%, 내부표준 면적 CV 2.5%, 주입·이온화 공통 변동 CV 2.5%(분석물과 내부표준에 함께 적용), 머무름 시간 SD 0.008분.\n- 오류는 한 분석물에만 넣어 나머지 분석물이 깨끗한지(분석 항목별 분리)도 함께 시험한다.\n- 정답표: `data/answer_key.json`. 탐지 단위는 (오류 코드, 분석물)이며 기준 미충족·주의만 센다. "허용"은 넣은 오류의 직접적 결과로 함께 나오는 항목이다.\n\n';
  t += '## 4. 시나리오별 결과 (seed ' + N + '개)\n\n' + table(['시나리오', '넣은 오류', '기대 탐지', '탐지율', '오탐 없는 실행', '미탐 내역', '오탐 내역'], ev.map(o => { const s = SCENARIOS.find(x => x.id === o.id);
    return [o.id + ' ' + o.name, s.rootCause, s.expected.concat(s.expectedAny ? [['(다음 중 하나) ' + s.expectedAny.map(e => e[0]).join(' 또는 '), s.expectedAny[0][1]]] : []).map(e => e[0] + ' / ' + e[1]).join('; ') || '경고 없음', o.id === 'S0' ? '–' : o.detected + '/' + o.runs + ' (' + (o.detected / o.runs * 100).toFixed(1) + '%)', o.clean + '/' + o.runs + ' (' + (o.clean / o.runs * 100).toFixed(1) + '%)', Object.keys(o.fn).map(k => k + ' ×' + o.fn[k]).join(', ') || '없음', Object.keys(o.fp).map(k => k + ' ×' + o.fp[k]).join(', ') || '없음']; }));
  const fpTotals = {}; for (const o of ev) for (const k of Object.keys(o.fp)) { const c = k.split('|')[0]; fpTotals[c] = (fpTotals[c] || 0) + o.fp[k]; }
  t += '\n### 오탐의 성격\n\n전체 ' + runsAll + '회 실행(분석물 3종 × ' + runsAll + ' = ' + runsAll * 3 + '개 검량선·QC 묶음)에서 정답표에 없는 경고: ' + (Object.keys(fpTotals).map(k => CODES[k] + ' ' + fpTotals[k] + '회').join(', ') || '없음') + '.\n\n- 오탐은 오류를 넣지 않은 분석물에서 잡음만으로 기준을 넘은 경우다. QC 정확도 오탐은 주로 저농도 QC(3 ng/mL)에서 나온다.\n- 비선형성 오탐은 잡음이 우연히 굽은 모양을 만든 경우다. 개발 중 첫 버전은 seed 1의 S3 배치에서 오류를 넣지 않은 Carbamazepine에 비선형성 경고를 냈고, 곡률 검정에 "최대 편차가 허용 편차의 2/3 이상" 조건을 추가해 줄였다.\n\n### 미탐의 성격\n\n';
  const mb = id => { const o = ev.find(x => x.id === id); return { miss: o.runs - o.detected, flagged: o.missButFlagged }; };
  t += '- **S1 비선형성**: 미탐 ' + mb('S1').miss + '회 중 ' + mb('S1').flagged + '회는 같은 분석물에 다른 경고(검량점 편차 초과, 검량선 부적합, 이상점 후보 등)가 보고되었다. 이상은 잡았지만 유형이 "비선형"으로 분류되지 않은 경우다. 나머지는 아무 경고도 없었다.\n- **S2 이상치**: 미탐 ' + mb('S2').miss + '회 중 ' + mb('S2').flagged + '회는 같은 분석물에 다른 경고가 보고되었다.\n- **S7 반복 변동**: 정밀도 지표(QC RSD, 중복 RPD) 중 하나라도 걸리면 탐지로 본다.\n\n';
  t += '## 5. 시나리오별 탐지 예 (seed 1, `data/scenarios/`)\n\n';
  for (const s of SCENARIOS) {
    const run = runRows(generateDataset([s.id], 1)); const sc = scoreScenario(run.result, s.id); const cards = diagnose(run.result); const fs = run.result.findings.filter(f => f.severity !== 'info');
    t += '### ' + s.id + ' ' + s.name + '\n\n- 넣은 오류(정답): ' + s.rootCause + '\n- 탐지: ' + (fs.length ? fs.map(f => '`' + f.code + '` ' + f.analyte).join(', ') : '경고 없음') + '\n- 정답표 대비: 미탐 ' + (sc.fn.length || '없음') + ', 오탐 ' + (sc.fp.length || '없음') + '\n';
    const main = cards.find(c => (s.expected.concat(s.expectedAny || [])).some(e => e[0] === c.code && e[1] === c.analyte) && c.hypotheses.length);
    if (main) { t += '- 관측 사실(첫 항목): ' + main.observations[0] + '\n- 제시한 가설과 이 데이터에서의 상태:\n' + main.hypotheses.map(h => '  - ' + h.cause + ' — **' + h.standingLabel + '**').join('\n') + '\n- 결론: ' + main.conclusion + '\n'; }
    else if (fs.length) { const c0 = cards.find(c => c.code === fs[0].code); t += '- 진단: ' + c0.conclusion + '\n'; }
    t += '\n';
  }
  t += '## 6. 원인을 확정하지 않는다는 요구의 검증\n\n- 시험 `진단: 모든 카드가 … 원인을 확정하지 않는다`가 모든 카드에서 `causeStatus === "원인 미확정"`, 가설 2개 이상, 결론이 "원인 미확정"으로 시작하는지 확인한다.\n- 예: S4에서 실제로 넣은 것은 "분석물 면적만 0.45배"다. 도구는 전처리 손실, 보정되지 않은 매질 효과, 첨가 용액 오류, 분해를 모두 후보로 두고, 매질이 없는 바탕 첨가 시료도 낮다는 점을 매질 효과 가설의 반대 근거로 적는다. 어느 것도 확정하지 않는다.\n- 예: S5에서는 내부표준과 분석물이 함께 줄어 면적비가 유지되지만, 벗어난 주입이 모두 미지 시료라 "보정이 제대로 되었는지 이 데이터로 확인할 수 없다"고 적는다.\n\n## 7. LLM 경로의 검증 범위\n\n- 프롬프트 구성과 응답 검사(계산 결과에 없는 수치, 단정 표현, 존재하지 않는 항목 참조)는 가짜 응답으로 시험했다.\n- 실제 Claude 호출은 게시된 Artifact 안에서만 동작하며(보는 사람의 승인 필요), 자동 시험에는 포함되지 않는다. 로컬 파일(`dist/index.html`)에서는 LLM 없이 규칙 기반 진단만 동작한다.\n- 검사기는 휴리스틱이다. 수치를 바꾸지 않은 그럴듯한 오해석은 잡지 못한다. 그래서 LLM 출력은 항상 "LLM 생성 해석"으로 구분해 표시하고 계산 결과 옆에 둔다.\n\n## 8. 한계\n\n- 합성 데이터는 잡음 구조가 단순하다(정규 잡음, 독립). 실제 데이터의 적분 오류, 공용출 간섭, 비정규 분포는 반영하지 않았다. 실제 기관 데이터로는 검증하지 않았다.\n- 오류를 한 번에 하나만 넣었다. 여러 오류가 겹친 배치는 평가하지 않았다.\n- 시나리오의 오류 크기(예: 이상점 +45%, 회수율 45%)는 기준에서 충분히 떨어져 있다. 기준 근처의 약한 오류에 대한 탐지율은 이 표보다 낮다.\n- 주입 순서가 필요한 진단(표류, 직전 주입)은 주입 순서 열이 없으면 행 순서에 의존한다.\n- 피크 모양, 이온비, 크로마토그램은 입력에 없어 적분 오류와 피크 오인은 가설로만 제시된다.\n';
  out('오류-탐지-보고서.md', t);
}

// ───────────── 설치 및 사용 설명서 ─────────────
{
  let t = head('설치 및 사용 설명서');
  t += '## 1. 설치\n\n설치가 필요 없다. `dist/index.html`을 브라우저(Chrome, Edge, Firefox, Safari 최신판)로 연다. 파일은 브라우저 안에서만 처리되고 서버로 보내지 않는다.\n\n개발·시험에는 Node.js 18 이상이 필요하다. 외부 패키지는 없다.\n\n```\nnode --test tests/*.test.mjs     # 단위·통합 시험\nnode scripts/build.mjs           # 웹앱 빌드 (dist/index.html, dist/artifact.html)\nnode tests/browser.mjs           # 브라우저 시험 (Chrome 또는 Edge 필요)\nnode scripts/gen-data.mjs        # 합성 CSV와 정답표 재생성\nnode scripts/evaluate.mjs 300    # 오탐·미탐 평가\nnode scripts/gen-docs.mjs        # 문서 재생성\n```\n\nXLSX·CP949 시험 파일은 `uv run --with openpyxl python scripts/gen-fixtures.py`로 다시 만든다.\n\n';
  t += '## 2. 입력 파일 준비\n\n- 형식: CSV(.csv, .tsv, .txt; 쉼표·세미콜론·탭 구분, UTF-8 또는 CP949) 또는 Excel(.xlsx). 구형 .xls와 암호 보호 파일은 지원하지 않는다.\n- 구조: 첫 행은 머리글, 그 아래 한 행이 한 주입의 한 분석물(긴 형식).\n- 필드: ' + FIELDS.filter(f => !f.extra).map(f => f.label).join(', ') + '. 선택 필드로 Injection Order, Parent Sample ID를 쓸 수 있다.\n- 필수: Sample ID, Sample Type, Analyte, Nominal Concentration, Peak Area, Batch ID. Analyte와 Batch ID는 열이 없으면 화면에서 고정값을 입력할 수 있다.\n- 예시 파일: `data/synthetic_all_batches.csv`, `data/scenarios/*.csv`, `data/synthetic_all_batches.xlsx`.\n\n';
  t += '## 3. 화면별 사용법\n\n### Dashboard\n전체 배치 수, 분석 항목 수, QC 경고 수, 검토 필요 시료 수를 보여 준다. 배치 × 분석물 표의 칸을 누르면 해당 QC 검토로 이동한다. 처음 열면 합성 예시 데이터가 들어 있고, 그 사실이 상단 띠에 표시된다.\n\n### Data Import\n1. 파일을 고르거나 끌어다 놓는다. XLSX에 시트가 여러 개면 시트를 고른다.\n2. **컬럼 매핑**을 확인한다. 머리글 이름으로 자동 연결하며, 이름이 모호하면 "추정: 확인 필요"로 표시한다. 잘못 연결된 항목은 목록에서 바꾼다.\n3. **누락 항목과 데이터 문제**를 본다. 숫자가 아닌 값, 음수, 누락은 행 번호와 함께 나오며 값을 채우지 않는다.\n4. 인식하지 못한 시료 유형이 있으면 유형을 지정한다. 지정하지 않으면 그 행은 분석에서 빠진다.\n5. 희석배수가 비어 있으면 최종 농도를 계산하지 않는다. 모두 1배라면 "희석배수 누락 시 1로 간주"를 켠다.\n6. 매핑을 바꾸면 즉시 다시 분석한다. 필수 열이 없으면 분석하지 않고 이유를 보여 준다.\n\n### Calibration\n- 배치와 분석물을 고르면 검량선 그래프, 잔차 그래프(역산 편차), 회귀식, 적합성 기준별 판정, 역산 결과 표가 나온다.\n- 정량 방식(내부·외부표준법)과 가중치를 바꾸면 그 배치·분석물만 다시 계산한다.\n- 적합성은 역산 정확도·수준 수·범위 끝점으로 판정한다. R²는 참고값이다.\n- 검량점을 빼려면 "제외…"를 누르고 사유를 적는다. 사유 없이는 제외되지 않는다.\n- 가중치 비교 표는 같은 점에 가중치만 바꾼 결과다. 가중치는 분석법에서 정한 것을 써야 한다.\n\n### QC Review\n- 항목별 판정, 오류 유형, 관측값, 기준, 출처, 계산 근거를 표로 보여 준다.\n- 배치와 분석물을 모두 고르면 QC 통계, 바탕·첨가·중복 표, 내부표준·머무름 시간 그래프가 나온다.\n- 항목마다 검토 상태(미검토·확인함·조치 필요·해당 없음)와 메모를 남길 수 있다.\n- **QC 기준 설정**을 펼쳐 값을 바꾼다. 기본값은 예시다. 바꾼 내용은 검토 기록에 남는다.\n\n### AI Research Assistant\n- 경고 항목마다 **관측 사실**, **가능한 원인(가설)**, **추가 확인 항목**, **권장 검증**, **결론**을 나눠 보여 준다.\n- 가설마다 이 데이터 안의 근거, 맞지 않는 점, 판단할 수 없는 부분을 적는다. 결론은 항상 "원인 미확정"이다.\n- 게시된 Artifact에서 열면 "Claude에게 해석 요청"을 쓸 수 있다. 엔진의 판정 결과만 보내고 원자료 행은 보내지 않는다. 돌아온 글은 계산 결과에 없는 수치와 단정 표현을 자동 검사해 표시한다.\n\n### Report\n- 보고서(HTML), 구조화 데이터(JSON), QC 판정 표(CSV), 정량 결과 표(CSV)를 내보낸다.\n- PDF는 HTML 보고서를 브라우저에서 열어 인쇄 → "PDF로 저장"으로 만든다. 로컬에서 열었을 때는 화면의 인쇄 버튼도 쓸 수 있다.\n- 검토 메모를 추가하면 검토 기록에 시각과 함께 남는다.\n\n';
  t += '## 4. 결과를 읽을 때\n\n- **기준 미충족**은 설정된 기준을 벗어났다는 뜻이다. 기준이 분석법과 다르면 판정도 의미가 없다.\n- **주의**는 기준은 충족하지만 진단상 살펴볼 점이 있다는 뜻이다(예: 검량선은 적합이지만 이상점 후보가 있음).\n- **평가 불가**는 필요한 데이터가 없어 계산하지 않았다는 뜻이다. 통과가 아니다.\n- 원인 후보는 가설이다. 장비 기록, 크로마토그램, 조제 기록 없이 데이터 표만으로는 원인을 정할 수 없다.\n\n';
  t += '## 5. 분석 엔진을 코드에서 쓰기\n\n```js\nimport { readTableFile } from \'./src/parse.js\';\nimport { runRows } from \'./src/pipeline.js\';\nimport { diagnose } from \'./src/diagnose.js\';\nconst file = await readTableFile(\'batch.xlsx\', bytes);\nconst run = runRows(file.sheets[0].rows);            // { built: 검증 결과, result: 분석 결과 }\nconsole.log(run.result.dashboard, run.result.findings, diagnose(run.result));\n```\n';
  t += '\n## 6. BioPilot 본편(ELN)으로 보내기\n\n이 도구는 본편과 별개로 브라우저에서만 동작한다. 본편은 "수치 계산은 Python 결정론적 코드"가 원칙이므로, 이 도구의 계산 결과를 본편 화면에 쓰지 않는다. 대신 검증한 배치의 **원자료**를 본편 데이터셋 계약으로 내보내 본편이 다시 계산하게 한다.\n\n- Report 화면의 "BioPilot 본편(ELN)으로 보내기"에서 배치를 고르고 `calibration CSV`, `recovery CSV`를 받는다. 본편 Notebook 탭에서 실험을 만들고 두 파일을 데이터셋으로 올린다.\n- 옮기는 것: 검량 표준(`injection_id, level_ng_ml, analyte, analyte_area, is_area`)과 원시료가 연결되지 않은 첨가 시료(`injection_id, sample_id, analyte, spike_ng_g, analyte_area, is_area`).\n- 옮기지 않는 것과 이유는 화면에 표시된다: 내부표준 면적이 없는 행, 원시료가 연결된 매질 첨가(본편은 원시료 농도를 빼지 않음), 희석된 첨가 시료, QC·바탕·중복·미지 시료(본편 계약에 해당 열이 없음).\n- 단위: 숫자를 그대로 옮긴다. 본편은 조건 블록의 추출 부피와 시료 질량으로 ng/g을 환산하므로, 파일의 첨가 농도가 바이알 내 농도라면 환산 계수가 1이 되도록 조건을 입력한다.\n- 명령줄: `node scripts/eln-export.mjs <입력 파일> [배치 ID] [출력 폴더]`. 본편 코드로 대조하려면 저장소 루트에서 `backend/.venv/bin/python qc-validator/scripts/verify_eln_bridge.py <출력 폴더> <배치 ID>`.\n';
  out('설치-및-사용-설명서.md', t);
}

// ───────────── 확장 설계 ─────────────
{
  let t = head('향후 GC-MS/MS 및 미생물 분석 확장 설계');
  t += '> 이 문서는 설계안이다. 여기 적힌 기능은 구현되어 있지 않다. 기준 수치는 구현 시점에 해당 분석법 원문에서 확인해 예시 기준으로 넣는다.\n\n';
  t += '## 1. 현재 구조에서 재사용되는 것\n\n```\n파일 → parse.js (형식·매핑·검증) → 레코드\n레코드 → analyze.js → [calibration.js → qc.js] → 판정(findings)\n판정 → diagnose.js (규칙 기반 가설) → llm.js (선택) → report.js\n```\n\n- `stats.js`의 통계 함수, `parse.js`의 파일 판독과 "값을 채우지 않는" 검증, `rules.js`의 설정 가능한 규칙 구조, 판정 객체의 형태(코드·관측값·기준·근거), 진단 카드의 형태(관측 사실·가설·확인·검증·원인 미확정), 보고서와 검토 기록은 분석 종류와 무관하다.\n- 분석 종류마다 달라지는 것은 (1) 입력 필드, (2) 정량 모형, (3) QC 항목과 기준, (4) 진단 지식이다.\n\n## 2. 분석 종류 모듈(assay module) 인터페이스\n\n`src/assays/<이름>/`에 다음 네 가지를 둔다. 현재의 LC-MS/MS 코드를 첫 모듈로 옮기는 것이 1단계다.\n\n';
  t += table(['구성', '역할', 'LC-MS/MS에서의 현재 위치'], [['fields', '입력 필드 정의와 머리글 동의어, 시료 유형', 'parse.js의 FIELDS, TYPE_SYN'], ['quantify', '검량·정량 모형과 적합성 판정', 'calibration.js'], ['checks', 'QC 항목 계산과 판정', 'qc.js'], ['rules', '규칙 메타데이터, 예시 기준 묶음', 'rules.js'], ['knowledge', '오류 코드별 진단 카드 생성기', 'diagnose.js의 BUILDERS']]);
  t += '\n`analyze(records, settings, meta)`는 레코드의 분석 종류에 맞는 모듈을 불러 같은 형태의 결과를 돌려준다. 화면은 모듈이 내놓는 표와 그래프 정의를 그린다.\n\n## 3. GC-MS/MS 확장\n\n### 추가 입력 필드\n\n';
  t += table(['필드', '용도'], [['Qualifier Ion Area / Ion Ratio', '확인 이온과 정량 이온의 비로 피크 동정 확인'], ['Surrogate Name / Surrogate Area', '시료마다 넣는 대체표준물질의 회수율'], ['Tune Check 결과', '질량 축·분해능 점검(예: DFTPP, BFB 기준 충족 여부)'], ['Response Factor 관련(내부표준 농도)', '상대감응계수(RRF) 방식 검량'], ['Injection Port / Liner 교체 시점', '주입구 열화 진단의 문맥']]);
  t += '\n### 정량 모형\n\n- 평균 상대감응계수(RRF) 방식을 추가한다: 수준별 RRF의 RSD로 직선성을 판정하고, RSD가 기준을 넘으면 회귀 방식으로 전환하도록 안내한다.\n- 현재의 가중 선형 회귀는 그대로 쓴다.\n\n### 추가 QC 항목(오류 코드 초안)\n\n';
  t += table(['코드', '내용', '필요 데이터'], [['ION_RATIO', '이온비가 검량 표준 평균에서 허용 범위를 벗어남', '확인 이온 면적'], ['SURR_RECOVERY', '대체표준물질 회수율 이상', '대체표준 면적·농도'], ['CCV_DRIFT', '연속 검량 검증 표준의 응답이 초기 검량에서 벗어남', 'CCV로 표시된 주입'], ['RRF_RSD', '수준별 감응계수의 RSD 초과', '내부표준 농도'], ['TUNE_FAIL', '튠 점검 미통과', '튠 결과'], ['BREAKDOWN', '열분해 지표 화합물의 분해율 초과(주입구 활성)', '분해 점검 주입']]);
  t += '\n### 진단 지식의 차이\n\n- 머무름 시간 이동: 컬럼 절단·교체, 운반기체 유량·누설이 주요 후보가 된다.\n- 응답 저하: 주입구 라이너 오염, 격막 누설, 이온원 오염을 후보에 넣고, 고비점 화합물만 낮아지는지(주입구 차별)로 구별 근거를 만든다.\n- 매질 효과: GC에서는 매질에 의한 응답 증강이 흔하므로 회수율이 높은 경우의 가설 순서를 바꾼다.\n\n## 4. 미생물 분석 확장\n\n정량 모형이 검량선이 아니라 계수(count)이므로 `quantify`와 `checks`를 새로 만든다.\n\n### 입력 필드\n\n';
  t += table(['필드', '용도'], [['Dilution(10⁻ⁿ), Plated Volume', '집락 수를 CFU/mL(또는 /g)로 환산'], ['Colony Count, Plate Replicate', '평판별 집락 수'], ['Medium / Lot, Incubation Temp·Time', '배지와 배양 조건 기록'], ['Control Type(양성·음성·무균·배지 성능)', '대조군 판정'], ['MPN Tube Pattern', '최확수법의 양성 시험관 조합'], ['Presence/Absence 결과', '정성 시험']]);
  t += '\n### 계산\n\n- 계수 가능 범위 안의 평판만 써서 가중 평균으로 CFU를 계산한다(범위와 가중 방식은 적용 표준에서 확인해 규칙으로 둔다).\n- 범위 밖 평판만 있을 때는 "추정값"으로 표시하고 정량값처럼 다루지 않는다.\n- 최확수는 표준 표 또는 최대우도 계산으로 구하고 신뢰구간을 함께 낸다.\n- 결과는 로그 변환 값으로 정밀도를 평가한다.\n\n### QC 항목(오류 코드 초안)\n\n';
  t += table(['코드', '내용'], [['NEG_CONTROL_GROWTH', '음성·무균 대조에서 집락 검출'], ['POS_CONTROL_FAIL', '양성 대조 또는 배지 성능 시험 미충족'], ['DUP_PLATE_DISPERSION', '중복 평판의 차이가 포아송 분포로 설명되는 범위를 넘음'], ['DILUTION_INCONSISTENT', '연속 희석 단계 사이의 집락 수 비가 희석배수와 맞지 않음'], ['COUNT_OUT_OF_RANGE', '계수 가능 범위 밖의 평판만 있음'], ['INCUBATION_DEVIATION', '배양 온도·시간이 허용 범위를 벗어남'], ['HOLD_TIME', '시료 채취에서 분석까지의 시간 초과']]);
  t += '\n### 진단 지식의 예\n\n- 희석 단계 불일치: 희석 조작 오류, 혼합 부족, 집락 뭉침, 억제 물질의 희석 효과를 후보로 두고, 낮은 희석에서만 억제되는지로 구별 근거를 만든다.\n- 음성 대조 오염: 배지·희석액 오염, 작업 환경, 교차 오염을 후보로 두고, 같은 배지 lot의 다른 대조 결과로 근거를 만든다.\n\n## 5. 단계별 계획\n\n1. **모듈 분리**: 현재 코드를 `assays/lcmsms/`로 옮기고 인터페이스를 고정한다. 기존 시험 112개가 그대로 통과해야 한다.\n2. **GC-MS/MS**: 필드와 규칙 추가, RRF 정량, 이온비·대체표준·CCV 판정. 합성 시나리오와 정답표를 같은 방식으로 만든다.\n3. **미생물**: 계수 모형과 대조군 판정. 포아송 분산 검정을 `stats.js`에 추가한다.\n4. **공통**: 배치 간 추세(관리도), 장비·분석법별 규칙 묶음 저장, 감사 추적이 필요한 환경을 위한 서명·잠금.\n\n## 6. 구현 전에 확인할 것\n\n- 각 분석법의 기준 수치는 원문에서 확인한 뒤 "예시 기준"으로 넣는다. 이 문서에는 일부러 수치를 적지 않았다.\n- 실제 사용자의 내보내기 파일 형식(넓은 형식, 분석물별 시트)을 받아 매핑 기능을 넓힌다. 지금은 긴 형식만 지원한다.\n- 전자 기록 규제(감사 추적, 접근 통제)가 적용되는 환경에서는 브라우저 단독 도구로는 부족하다. 서버 저장과 사용자 인증이 필요하다.\n';
  out('확장-설계.md', t);
}
