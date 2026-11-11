// BIOPILOT — 합성 LC-MS/MS 정량 배치 생성기와 오류 시나리오 정답표. 실제 기관 데이터가 아니다.
// 같은 seed면 같은 파일이 나온다. 오류는 한 분석물에만 주입해 분석물 간 분리를 시험한다.
import { rng } from './stats.js';

export const ANALYTES = [
  { name: 'Caffeine', is: 'Caffeine-13C3', rt: 2.85, sens: 4200, isArea: 520000 },
  { name: 'Carbamazepine', is: 'Carbamazepine-d10', rt: 5.42, sens: 9800, isArea: 760000 },
  { name: 'Sulfamethoxazole', is: 'Sulfamethoxazole-d4', rt: 4.10, sens: 2600, isArea: 410000 },
];
export const CAL_LEVELS = [1, 2, 5, 10, 50, 100, 250, 500];      // ng/mL
export const QC_LEVELS = [['QC-L', 3], ['QC-M', 75], ['QC-H', 400]];
export const HEADER = ['Batch ID', 'Sample ID', 'Sample Type', 'Analyte', 'Concentration Level', 'Nominal Concentration', 'Peak Area', 'Internal Standard Area', 'Retention Time', 'Dilution Factor', 'Replicate', 'Injection Order', 'Parent Sample ID'];

// 시나리오 정의. expected: 반드시 탐지해야 하는 [코드, 분석물]. allowed: 그 오류의 직접적인 결과로 함께 나와도 되는 [코드, 분석물].
// 이 밖의 fail/warn은 오탐으로 센다. rootCause는 합성 시 실제로 주입한 원인이며, 도구가 이를 "확정"해서는 안 된다.
export const SCENARIOS = [
  { id: 'S0', batch: 'B00-NORMAL', name: '정상 배치', rootCause: '오류 없음', expected: [], allowed: [] },
  { id: 'S1', batch: 'B01-NONLINEAR', name: '검량선 비선형성', rootCause: 'Caffeine 응답을 고농도에서 포화시킴(500에서 약 −28%)',
    expected: [['CAL_NONLINEAR', 'Caffeine']], allowed: [['CAL_POINT_DEV', 'Caffeine'], ['CAL_FAIL', 'Caffeine'], ['QC_ACCURACY', 'Caffeine'], ['QC_BATCH_FAIL', 'Caffeine'], ['SAMPLE_ABOVE_RANGE', 'Caffeine'], ['SPIKE_LOW', 'Caffeine'], ['SPIKE_HIGH', 'Caffeine'], ['DUP_RPD', 'Caffeine']] },
  { id: 'S2', batch: 'B02-OUTLIER', name: '검량점 이상치', rootCause: 'Carbamazepine 50 ng/mL 표준의 분석물 면적을 1.45배로 만듦',
    expected: [['CAL_OUTLIER', 'Carbamazepine']], allowed: [['CAL_POINT_DEV', 'Carbamazepine'], ['CAL_FAIL', 'Carbamazepine'], ['QC_ACCURACY', 'Carbamazepine'], ['QC_BATCH_FAIL', 'Carbamazepine'], ['SPIKE_LOW', 'Carbamazepine'], ['SPIKE_HIGH', 'Carbamazepine']] },   // 이상점이 기울기를 끌어당겨 QC가 함께 벗어날 수 있다
  { id: 'S3', batch: 'B03-BLANK', name: 'Blank 오염 신호', rootCause: 'Caffeine 방법 바탕에 LLOQ 응답의 약 60%에 해당하는 신호를 넣음',
    expected: [['MB_CONTAM', 'Caffeine']], allowed: [] },
  { id: 'S4', batch: 'B04-SPIKE', name: '낮은 Spike Recovery', rootCause: 'Sulfamethoxazole 첨가 시료의 분석물 면적을 0.45배로 만듦(내부표준은 그대로)',
    expected: [['SPIKE_LOW', 'Sulfamethoxazole']], allowed: [] },
  { id: 'S5', batch: 'B05-IS', name: '내부표준 응답 이상', rootCause: 'Carbamazepine의 미지 시료 3개에서 분석물과 내부표준 면적을 함께 0.3배로 만듦',
    expected: [['IS_RESPONSE', 'Carbamazepine']], allowed: [] },
  { id: 'S6', batch: 'B06-RT', name: 'Retention Time Shift', rootCause: '배치 후반으로 갈수록 모든 분석물의 머무름 시간이 최대 +0.28분 늦어짐',
    expected: [['RT_SHIFT', 'Caffeine'], ['RT_SHIFT', 'Carbamazepine'], ['RT_SHIFT', 'Sulfamethoxazole']], allowed: [] },
  { id: 'S7', batch: 'B07-PRECISION', name: '반복 측정 변동 증가', rootCause: 'Caffeine의 QC·중복 시료에 CV 약 28%의 추가 변동을 넣음(내부표준은 그대로)',
    expected: [], expectedAny: [['QC_PRECISION', 'Caffeine'], ['DUP_RPD', 'Caffeine']], allowed: [['QC_PRECISION', 'Caffeine'], ['QC_ACCURACY', 'Caffeine'], ['QC_BATCH_FAIL', 'Caffeine'], ['DUP_RPD', 'Caffeine'], ['SPIKE_LOW', 'Caffeine'], ['SPIKE_HIGH', 'Caffeine'], ['SAMPLE_ABOVE_RANGE', 'Caffeine']] },
  { id: 'S8', batch: 'B08-MISSINGQC', name: '누락된 QC', rootCause: '방법 바탕, 고농도 QC, 첨가 시료를 배치에서 뺌',
    expected: [['QC_MISSING', 'Caffeine'], ['QC_MISSING', 'Carbamazepine'], ['QC_MISSING', 'Sulfamethoxazole']], allowed: [] },
];

// 한 배치의 주입 순서(시료 설계)
function design(scn) {
  const inj = []; const push = (id, type, o) => inj.push(Object.assign({ id, type, level: '', nominal: '', dil: 1, rep: 1, parent: '' }, o || {}));
  push('CB-01', 'Calibration Blank');
  CAL_LEVELS.forEach((c, i) => push('STD-' + (i + 1), 'Calibration Standard', { level: 'L' + (i + 1), nominal: c }));
  push('CB-02', 'Calibration Blank');
  if (scn !== 'S8') push('MB-01', 'Method Blank');
  for (const [lab, c] of QC_LEVELS) { if (scn === 'S8' && lab === 'QC-H') continue; push(lab + '-1', 'QC', { level: lab, nominal: c }); }
  if (scn !== 'S8') push('LCS-01', 'Spike', { level: 'LCS', nominal: 50 });
  for (let s = 1; s <= 5; s++) push('S' + String(s).padStart(2, '0'), 'Sample', { dil: s === 4 ? 5 : 1 });
  push('S03-DUP', 'Duplicate', { parent: 'S03', rep: 2 });
  if (scn !== 'S8') push('S05-MS', 'Spike', { level: 'MS', nominal: 50, parent: 'S05' });
  for (const [lab, c] of QC_LEVELS) { if (scn === 'S8' && lab === 'QC-H') continue; push(lab + '-2', 'QC', { level: lab, nominal: c, rep: 2 }); }
  for (let s = 6; s <= 10; s++) push('S' + String(s).padStart(2, '0'), 'Sample', { dil: s === 9 ? 10 : 1 });
  push('S08-DUP', 'Duplicate', { parent: 'S08', rep: 2 });
  for (const [lab, c] of QC_LEVELS) { if (scn === 'S8' && lab === 'QC-H') continue; push(lab + '-3', 'QC', { level: lab, nominal: c, rep: 3 }); }
  push('CB-03', 'Calibration Blank');
  return inj;
}

// 시나리오 하나의 배치를 행 배열로 만든다(머리글 제외).
export function generateBatch(scnId, seed) {
  const scn = SCENARIOS.find(s => s.id === scnId); if (!scn) throw new Error('알 수 없는 시나리오: ' + scnId);
  const R = rng((seed === undefined ? 1 : seed) * 7919 + scnId.charCodeAt(1) * 104729);
  const inj = design(scnId); const rows = [];
  // 미지 시료의 참 농도(분석물별, 바이알 내 농도)
  const truth = {}; for (const a of ANALYTES) { truth[a.name] = {}; for (let s = 1; s <= 10; s++) truth[a.name]['S' + String(s).padStart(2, '0')] = s === 5 ? 5 + 15 * R.u() : Math.exp(Math.log(4) + R.u() * (Math.log(300) - Math.log(4))); }   // S05는 매질 첨가의 원시료라 낮은 농도로 둔다
  inj.forEach((x, order) => {
    const injFactor = 1 + 0.025 * R.normal();                      // 주입·이온화 공통 변동: 분석물과 내부표준에 같이 걸림
    for (const a of ANALYTES) {
      let conc = 0;
      if (x.type === 'Calibration Standard' || x.type === 'QC') conc = x.nominal;
      else if (x.type === 'Sample') conc = truth[a.name][x.id];
      else if (x.type === 'Duplicate') conc = truth[a.name][x.parent];
      else if (x.type === 'Spike') conc = x.nominal + (x.parent ? truth[a.name][x.parent] : 0);
      let area = a.sens * conc * (1 + 0.025 * R.normal()) * injFactor + Math.abs(60 * R.normal());   // 비례 잡음 + 작은 바탕 잡음
      let isArea = a.isArea * (1 + 0.025 * R.normal()) * injFactor;
      let rt = a.rt + 0.008 * R.normal();
      if (x.type === 'Calibration Blank' || x.type === 'Method Blank') area = Math.abs(a.sens * 0.04 * (1 + 0.5 * R.normal()));   // LLOQ 응답의 약 4%

      // ── 오류 주입 ──
      if (scnId === 'S1' && a.name === 'Caffeine') area = area / (1 + conc / 1300);
      if (scnId === 'S2' && a.name === 'Carbamazepine' && x.id === 'STD-5') area *= 1.45;
      if (scnId === 'S3' && a.name === 'Caffeine' && x.id === 'MB-01') area = a.sens * 1 * 0.6 * (1 + 0.05 * R.normal());
      if (scnId === 'S4' && a.name === 'Sulfamethoxazole' && x.type === 'Spike') area = (area - a.sens * (x.parent ? truth[a.name][x.parent] : 0)) * 0.45 + a.sens * (x.parent ? truth[a.name][x.parent] : 0);
      if (scnId === 'S5' && a.name === 'Carbamazepine' && ['S02', 'S06', 'S07'].includes(x.id)) { area *= 0.3; isArea *= 0.3; }
      if (scnId === 'S6') rt += 0.28 * Math.pow(order / (inj.length - 1), 1.5);
      if (scnId === 'S7' && a.name === 'Caffeine' && (x.type === 'QC' || x.type === 'Duplicate' || x.type === 'Sample')) area *= Math.exp(0.28 * R.normal());

      rows.push([scn.batch, x.id, x.type, a.name, x.level, x.nominal === '' ? '' : x.nominal, Math.round(area), Math.round(isArea), Number(rt.toFixed(3)), x.dil, x.rep, order + 1, x.parent]);
    }
  });
  return rows;
}
export function generateDataset(scnIds, seed) { let rows = []; for (const id of scnIds) rows = rows.concat(generateBatch(id, seed)); return [HEADER].concat(rows); }
export function allScenarioIds() { return SCENARIOS.map(s => s.id); }
