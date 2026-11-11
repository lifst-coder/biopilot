// 시험용 데이터 조립 도구. 잡음 없는 정확한 값으로 배치를 만들어 기준 경계값을 시험한다.
import { HEADER } from '../src/synth.js';
import { runRows, defaultSettings } from '../src/pipeline.js';

export const LEVELS = [1, 2, 5, 10, 50, 100, 250, 500];
// 한 분석물의 완전한 배치. 면적 = slope × 농도, 내부표준 = 1000, 머무름 시간 = 3.000
export function batch(o) {
  const p = Object.assign({ batchId: 'B1', analyte: 'A', slope: 100, intercept: 0, levels: LEVELS, is: 1000, rt: 3, full: true, extra: [], std: {} }, o || {});
  const rows = []; let order = 0;
  const add = (id, type, x) => { const r = Object.assign({ level: '', nominal: '', area: 0, is: p.is, rt: p.rt, dil: 1, rep: 1, parent: '' }, x || {}); rows.push([p.batchId, id, type, p.analyte, r.level, r.nominal, r.area, r.is, r.rt, r.dil, r.rep, ++order, r.parent]); };
  const A = c => p.slope * c + p.intercept;
  if (p.full) add('CB-1', 'Calibration Blank', { area: 1 });
  p.levels.forEach((c, i) => add('STD-' + (i + 1), 'Calibration Standard', Object.assign({ level: 'L' + (i + 1), nominal: c, area: A(c) }, p.std[c] || {})));
  if (p.full) {
    add('MB-1', 'Method Blank', { area: 1 });
    for (const [lab, c] of [['QC-L', 3], ['QC-M', 75], ['QC-H', 400]]) for (const k of [1, 2]) add(lab + '-' + k, 'QC', { level: lab, nominal: c, area: A(c), rep: k });
    add('LCS-1', 'Spike', { nominal: 50, area: A(50) });
    add('S01', 'Sample', { area: A(20) }); add('S01-DUP', 'Duplicate', { area: A(20), parent: 'S01', rep: 2 });
  }
  for (const e of p.extra) add(e.id, e.type, e);
  return rows;
}
export const withHeader = rows => [HEADER].concat(rows);
export function run(rows, opt) {
  const o = opt || {}; const settings = defaultSettings(); settings.method = o.method || 'external'; settings.weighting = o.weighting || '1/x2';
  if (o.rules) o.rules(settings.rules); if (o.excluded) settings.excluded = o.excluded; if (o.perGroup) settings.perGroup = o.perGroup;
  return runRows(withHeader(rows), Object.assign({ settings }, o.options || {}));
}
export const codes = (res, analyte) => res.result.findings.filter(f => f.severity !== 'info' && (!analyte || f.analyte === analyte)).map(f => f.code);
export const has = (res, code, analyte) => codes(res, analyte).includes(code);
export const close = (a, b, tol) => Math.abs(a - b) <= (tol === undefined ? 1e-9 : tol);
