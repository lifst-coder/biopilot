// BIOPILOT — QC 허용 기준. 모든 값은 설정 가능한 "예시 기준"이다. 실제 판정에는 해당 분석법·규격·SOP의 기준을 입력해야 한다.
// 출처 표기는 2026-11에 원문으로 확인한 조항이다(docs/QC-규칙-명세.md).

export const RULE_META = [
  // 검량선
  { path: 'cal.minLevels', group: '검량선', label: '최소 농도 수준 수', unit: '개', min: 2, max: 20, int: true, source: 'ICH M10 3.2.4: 바탕·영 시료 외 최소 6개 수준' },
  { path: 'cal.devPct', group: '검량선', label: '검량점 역산 농도 허용 편차', unit: '±%', min: 1, max: 100, source: 'ICH M10 3.2.4/3.3.2: 명목값의 ±15%' },
  { path: 'cal.devPctLloq', group: '검량선', label: '최저 검량점(LLOQ) 허용 편차', unit: '±%', min: 1, max: 100, source: 'ICH M10 3.2.4/3.3.2: LLOQ에서 ±20%' },
  { path: 'cal.minPassPct', group: '검량선', label: '기준을 만족해야 하는 검량점 비율', unit: '% 이상', min: 1, max: 100, source: 'ICH M10 3.3.2: 검량점의 75% 이상, 최소 6개 수준' },
  { path: 'cal.useR2', group: '검량선', label: 'R² 기준도 함께 적용', unit: '', bool: true, source: 'ICH M10과 SANTE/11312/2021에는 R² 기준이 없다. EPA 8000D 11.5.2.2는 r² ≥ 0.99를 둔다. R²만으로 적합을 판정하지 않는다.' },
  { path: 'cal.r2Min', group: '검량선', label: 'R² 하한 (위 항목을 켰을 때)', unit: '이상', min: 0.5, max: 1, source: 'EPA SW-846 8000D 11.5.2.2: r² ≥ 0.99' },
  { path: 'cal.curvatureMinPct', group: '검량선', label: '비선형으로 볼 곡률 크기(최고 농도에서 2차 항 / 1차 항)', unit: '% 이상', min: 1, max: 100, source: '출처 없음: 이 도구의 진단용 예시값. 2차 항 F 검정이 유의하고 이 크기를 넘을 때만 경고한다.' },
  { path: 'cal.alpha', group: '검량선', label: '곡률·이상점 검정의 유의수준', unit: '', min: 0.0001, max: 0.2, source: '출처 없음: 통계 관행의 예시값' },
  // 바탕
  { path: 'blank.mode', group: '바탕 시료', label: '바탕 판정 방식', unit: '', options: [['response', 'LLOQ 표준 응답 대비 %'], ['conc', 'LLOQ 농도 대비 비율']], source: 'ICH M10 3.2.1/3.2.6은 응답 기준, EPA 537.1 9.3.1은 농도 기준(MRL의 1/3 미만)' },
  { path: 'blank.maxPctOfLloqResponse', group: '바탕 시료', label: '바탕 시료의 분석물 응답 상한(LLOQ 표준 응답 대비)', unit: '% 이하', min: 0.1, max: 100, source: 'ICH M10 3.2.1(선택성)·3.2.6(캐리오버): LLOQ 응답의 20% 이하' },
  { path: 'blank.maxFractionOfLloqConc', group: '바탕 시료', label: '바탕 시료 농도 상한(LLOQ 농도 대비 비율)', unit: '배 미만', min: 0.01, max: 1, source: 'EPA 537.1 9.3.1: MRL의 1/3 미만. EPA 8000D 9.2.6.9: LLOQ의 1/2 미만' },
  // QC 시료
  { path: 'qc.devPct', group: 'QC 시료', label: 'QC 정확도 허용 상대오차', unit: '±%', min: 1, max: 100, source: 'ICH M10 3.3.2: 명목값의 ±15%' },
  { path: 'qc.devPctLloq', group: 'QC 시료', label: 'LLOQ 수준 QC 허용 상대오차', unit: '±%', min: 1, max: 100, source: 'ICH M10 3.2.5.2: LLOQ에서 ±20%' },
  { path: 'qc.minPassPctAll', group: 'QC 시료', label: '전체 QC 중 기준을 만족해야 하는 비율', unit: '% 이상', min: 1, max: 100, source: 'ICH M10 3.3.2: 전체 QC의 2/3 이상' },
  { path: 'qc.minPassPctLevel', group: 'QC 시료', label: '각 농도 수준에서 기준을 만족해야 하는 비율', unit: '% 이상', min: 1, max: 100, source: 'ICH M10 3.3.2: 각 수준의 50% 이상' },
  { path: 'qc.rsdPct', group: 'QC 시료', label: 'QC 반복 정밀도 RSD 상한', unit: '% 이하', min: 1, max: 100, source: 'ICH M10 3.2.5.2: %CV 15% 이하(LLOQ 20%)' },
  // 반복·중복
  { path: 'dup.rpdPct', group: '반복·중복', label: '중복 시료 상대 백분율 차이(RPD) 상한', unit: '% 이하', min: 1, max: 200, source: '실무 예시값. EPA 537.1 9.3.7은 30% 이하(MRL의 2배 이내는 50%)' },
  { path: 'rep.rsdPct', group: '반복·중복', label: '3회 이상 반복 측정 RSD 상한', unit: '% 이하', min: 1, max: 100, source: 'ICH M10 3.2.5.2의 정밀도 15%를 준용한 예시값. SANTE/11312/2021은 RSD 20% 이하' },
  // 첨가 회수율
  { path: 'spike.minPct', group: '첨가 회수율', label: '회수율 하한', unit: '% 이상', min: 0, max: 200, source: 'EPA 537.1 9.3.3: 70–130%(저농도 50–150%). SANTE/11312/2021: 평균 70–120%, 개별 60–140%' },
  { path: 'spike.maxPct', group: '첨가 회수율', label: '회수율 상한', unit: '% 이하', min: 50, max: 500, source: 'EPA 537.1 9.3.3: 70–130%(저농도 50–150%). SANTE/11312/2021: 평균 70–120%, 개별 60–140%' },
  // 내부표준
  { path: 'is.minPct', group: '내부표준 응답', label: '내부표준 면적 하한(검량 표준 평균 대비)', unit: '% 이상', min: 1, max: 100, source: 'EPA 537.1 9.3.4: 초기 검량 평균에서 50% 넘게 벗어나지 않을 것. ICH M10은 수치 없이 SOP로 정하도록 한다.' },
  { path: 'is.maxPct', group: '내부표준 응답', label: '내부표준 면적 상한(검량 표준 평균 대비)', unit: '% 이하', min: 100, max: 1000, source: 'EPA 537.1 9.3.4(50–150%). EPA 8000D 11.4.3의 통상 범위는 50–200%' },
  { path: 'is.driftPct', group: '내부표준 응답', label: '주입 순서에 따른 내부표준 표류 경고 크기', unit: '% 이상', min: 1, max: 100, source: '출처 없음: 이 도구의 진단용 예시값(추세가 유의하고 이 크기를 넘을 때 경고)' },
  // 머무름 시간
  { path: 'rt.mode', group: '머무름 시간', label: '머무름 시간 허용 방식', unit: '', options: [['abs', '절대값(분)'], ['rel', '상대값(%)']], source: 'SANTE/11312/2021 D2: ±0.1분' },
  { path: 'rt.absMin', group: '머무름 시간', label: '허용 편차(검량 표준 평균 대비)', unit: '±분', min: 0.001, max: 5, source: 'SANTE/11312/2021 D2, 표 4: LC·GC 모두 ±0.1분' },
  { path: 'rt.relPct', group: '머무름 시간', label: '허용 상대 편차', unit: '±%', min: 0.1, max: 50, source: '출처 없음: 상대값 방식을 쓰는 실험실을 위한 예시값' },
  // 필수 QC 구성
  { path: 'required.methodBlank', group: '배치 필수 QC', label: '방법 바탕 최소 개수', unit: '개', min: 0, max: 20, int: true, source: '예시값. 배치마다 방법 바탕을 두는 구성이 일반적이다. 필요한 개수와 빈도는 분석법에서 확인' },
  { path: 'required.calBlank', group: '배치 필수 QC', label: '검량 바탕 최소 개수', unit: '개', min: 0, max: 20, int: true, source: 'ICH M10 3.2.4: 검량선은 바탕 시료와 영 시료를 포함해 작성' },
  { path: 'required.qcLevels', group: '배치 필수 QC', label: 'QC 농도 수준 최소 수', unit: '개', min: 0, max: 10, int: true, source: 'ICH M10 3.3.1: 저·중·고 3개 수준 이상' },
  { path: 'required.qcRepsPerLevel', group: '배치 필수 QC', label: 'QC 수준별 최소 반복 수', unit: '개', min: 0, max: 10, int: true, source: 'ICH M10 3.3.1: 수준별 2개 이상(또는 시료 수의 5%)' },
  { path: 'required.spike', group: '배치 필수 QC', label: '첨가 시료 최소 개수', unit: '개', min: 0, max: 20, int: true, source: '예시값. 첨가 시료(LFB·LCS·매질 첨가)의 빈도는 분석법에서 확인' },
  { path: 'required.duplicate', group: '배치 필수 QC', label: '중복 시료 최소 쌍 수', unit: '쌍', min: 0, max: 20, int: true, source: '예시값. 중복 시료의 빈도는 분석법에서 확인' },
];

export const PROFILES = {
  'example-default': { name: '예시 기본값 (ICH M10 중심)', note: '생체시료 정량 분석의 ICH M10 기준을 중심으로, ICH에 수치가 없는 항목은 EPA 537.1·SANTE/11312/2021의 값을 예시로 채웠다.',
    rules: { cal: { minLevels: 6, devPct: 15, devPctLloq: 20, minPassPct: 75, useR2: false, r2Min: 0.99, curvatureMinPct: 10, alpha: 0.01 },
      blank: { mode: 'response', maxPctOfLloqResponse: 20, maxFractionOfLloqConc: 0.333 },
      qc: { devPct: 15, devPctLloq: 20, minPassPctAll: 66.7, minPassPctLevel: 50, rsdPct: 15 },
      dup: { rpdPct: 20 }, rep: { rsdPct: 15 }, spike: { minPct: 70, maxPct: 130 },
      is: { minPct: 50, maxPct: 150, driftPct: 30 }, rt: { mode: 'abs', absMin: 0.1, relPct: 2.5 },
      required: { methodBlank: 1, calBlank: 1, qcLevels: 3, qcRepsPerLevel: 2, spike: 1, duplicate: 1 } } },
  'example-sante': { name: '예시: 잔류농약 계열 (SANTE/11312/2021)', note: '역산 편차 ±20%, 회수율 70–120%, RSD 20%, 머무름 시간 ±0.1분. 이 문서에서 확인하지 않은 항목은 기본값을 유지했다.',
    patch: { cal: { devPct: 20, devPctLloq: 20 }, qc: { devPct: 20, devPctLloq: 20, rsdPct: 20 }, rep: { rsdPct: 20 }, spike: { minPct: 70, maxPct: 120 } } },
  'example-epa537': { name: '예시: 먹는물 PFAS 계열 (EPA 537.1)', note: '검량점 ±30%(최저 ±50%), 바탕 MRL의 1/3 미만, 회수율 70–130%, RPD 30%, 내부표준 50–150%. 최근 CCC 대비 70–140% 조건은 구현하지 않았다.',
    patch: { cal: { devPct: 30, devPctLloq: 50, minPassPct: 100, minLevels: 5 }, blank: { mode: 'conc', maxFractionOfLloqConc: 0.333 }, qc: { devPct: 30, devPctLloq: 50, rsdPct: 20 }, dup: { rpdPct: 30 }, spike: { minPct: 70, maxPct: 130 }, is: { minPct: 50, maxPct: 150 } } },
};

const clone = o => JSON.parse(JSON.stringify(o));
export function defaultRules() { return profileRules('example-default'); }
export function profileRules(id) {
  const base = clone(PROFILES['example-default'].rules); const p = PROFILES[id];
  if (p && p.patch) for (const g of Object.keys(p.patch)) Object.assign(base[g], p.patch[g]);
  base.profile = PROFILES[id] ? id : 'example-default';
  return base;
}
export function getRule(rules, path) { const [g, k] = path.split('.'); return rules[g] ? rules[g][k] : undefined; }
// 값을 검증한 뒤에만 반영한다. 잘못된 값이면 { error }를 돌려주고 규칙은 그대로 둔다.
export function setRule(rules, path, raw) {
  const meta = RULE_META.find(m => m.path === path); if (!meta) return { error: '알 수 없는 규칙: ' + path };
  const [g, k] = path.split('.'); let v;
  if (meta.bool) v = raw === true || raw === 'true' || raw === 'on';
  else if (meta.options) { if (!meta.options.some(o => o[0] === raw)) return { error: meta.label + ': 허용되지 않는 선택입니다.' }; v = raw; }
  else {
    v = typeof raw === 'number' ? raw : Number(String(raw).trim());
    if (String(raw).trim() === '' || !Number.isFinite(v)) return { error: meta.label + ': 숫자를 입력해 주세요.' };
    if (meta.int && !Number.isInteger(v)) return { error: meta.label + ': 정수를 입력해 주세요.' };
    if (v < meta.min || v > meta.max) return { error: meta.label + ': ' + meta.min + '–' + meta.max + ' 범위의 값을 입력해 주세요.' };
  }
  rules[g][k] = v; rules.profile = 'custom';
  if (rules.spike.minPct >= rules.spike.maxPct || rules.is.minPct >= rules.is.maxPct) return { warning: '하한이 상한보다 크거나 같습니다. 모든 값이 부적합으로 판정됩니다.' };
  return { ok: true };
}
export function ruleText(rules, path) {
  const meta = RULE_META.find(m => m.path === path); const v = getRule(rules, path);
  if (meta.bool) return v ? '적용' : '미적용';
  if (meta.options) return (meta.options.find(o => o[0] === v) || [, String(v)])[1];
  return String(v) + (meta.unit ? ' ' + meta.unit : '');
}
