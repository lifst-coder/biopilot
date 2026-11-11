// BIOPILOT — 분석 총괄. 레코드를 배치·분석물로 나눠 검량선 → 정량 → QC 순서로 실행하고 결과를 한 구조로 모은다.
// 이 파일과 stats/calibration/qc는 결정론적이다: 같은 입력과 설정이면 항상 같은 결과가 나온다.
import { isNum } from './stats.js';
import { buildCalibration, quantify } from './calibration.js';
import { runQc, CODES } from './qc.js';

export const ENGINE_VERSION = '1.0.0';
export const groupKey = (batchId, analyte) => batchId + '||' + analyte;
const BATCH_LEVEL = { CAL_FAIL: '검량선 부적합', CAL_NO_STANDARDS: '검량 표준 없음', CAL_CONFIG_FEW_POINTS: '검량점 부족', CAL_CONFIG_IS_MISSING: '내부표준 면적 없음', CAL_NONLINEAR: '검량선 비선형성', QC_BATCH_FAIL: 'QC 배치 기준 미달', QC_MISSING: '필수 QC 누락', MB_CONTAM: '방법 바탕 오염 신호', CB_CONTAM: '검량 바탕 오염 신호', IS_DRIFT: '내부표준 응답 표류' };
const SAMPLE_LEVEL = ['IS_RESPONSE', 'RT_SHIFT', 'DUP_RPD', 'REP_RSD', 'SAMPLE_ABOVE_RANGE'];

// settings: { rules, method, weighting, perGroup: {key: {method, weighting}}, excluded: {key: {행번호: 사유}} }
// meta: { hasIs, hasRt, hasOrder, hasDilution }
export function analyze(records, settings, meta) {
  const m = Object.assign({ hasIs: true, hasRt: true, hasOrder: false, hasDilution: true }, meta || {});
  const rules = settings.rules; const groupsMap = new Map();
  for (const r of records) { const k = groupKey(r.batchId, r.analyte); if (!groupsMap.has(k)) groupsMap.set(k, { key: k, batchId: r.batchId, analyte: r.analyte, recs: [] }); groupsMap.get(k).recs.push(r); }
  const groups = [], findings = [];
  for (const g of groupsMap.values()) {
    const over = (settings.perGroup && settings.perGroup[g.key]) || {};
    const method = over.method || settings.method || (m.hasIs ? 'internal' : 'external'); const weighting = over.weighting || settings.weighting || '1/x2';
    const recs = g.recs.slice().sort((a, b) => a.order - b.order || a.row - b.row);
    const cal = buildCalibration(recs, { method, weighting, rules, excluded: (settings.excluded && settings.excluded[g.key]) || {} });
    const rows = recs.map(rec => ({ rec, q: quantify(cal, rec) }));
    const qc = runQc(rows, cal, rules, m);
    const all = cal.findings.concat(qc.findings); const counter = {};
    const gf = all.map(f => { counter[f.code] = (counter[f.code] || 0) + 1; const ids = new Set(f.sampleIds || []); if (!f.sampleIds) for (const x of rows) if (f.rows.includes(x.rec.row)) ids.add(x.rec.sampleId);
      return Object.assign({}, f, { id: f.code + '|' + g.batchId + '|' + g.analyte + '|' + counter[f.code], label: CODES[f.code] || f.code, batchId: g.batchId, analyte: g.analyte, sampleIds: Array.from(ids) }); });
    const grp = { key: g.key, batchId: g.batchId, analyte: g.analyte, method, weighting, cal, rows, tables: qc.tables, findings: gf,
      counts: { STD: 0, CAL_BLANK: 0, METHOD_BLANK: 0, QC: 0, SPIKE: 0, DUP: 0, SAMPLE: 0 } };
    for (const x of rows) grp.counts[x.rec.type]++;
    groups.push(grp); for (const f of gf) findings.push(f);
  }
  groups.sort((a, b) => a.batchId.localeCompare(b.batchId, 'ko', { numeric: true }) || a.analyte.localeCompare(b.analyte, 'ko'));
  const order = { fail: 0, warn: 1, info: 2 };
  findings.sort((a, b) => order[a.severity] - order[b.severity] || a.batchId.localeCompare(b.batchId, 'ko', { numeric: true }) || a.analyte.localeCompare(b.analyte, 'ko') || a.code.localeCompare(b.code));

  // 검토가 필요한 시료: 시료에 직접 걸린 경고 + 배치 수준 사유
  const review = new Map();
  const flag = (batchId, sampleId, analyte, reason, level) => { const k = batchId + '||' + sampleId; if (!review.has(k)) review.set(k, { batchId, sampleId, reasons: [] }); const e = review.get(k); if (!e.reasons.some(r => r.analyte === analyte && r.reason === reason)) e.reasons.push({ analyte, reason, level }); };
  for (const g of groups) {
    const unknowns = g.rows.filter(x => x.rec.type === 'SAMPLE');   // 중복 시료는 원시료의 QC이므로 원시료 쪽에서 센다
    for (const f of g.findings) {
      if (f.severity === 'info') continue;
      if (BATCH_LEVEL[f.code]) for (const x of unknowns) flag(g.batchId, x.rec.sampleId, g.analyte, BATCH_LEVEL[f.code], 'batch');
      else if (SAMPLE_LEVEL.includes(f.code)) for (const x of unknowns) if (f.rows.includes(x.rec.row) || (f.details.items || []).some(i => (i.rowsAll || []).includes(x.rec.row))) flag(g.batchId, x.rec.sampleId, g.analyte, f.label, 'sample');
    }
  }
  const batches = Array.from(new Set(groups.map(g => g.batchId))), analytes = Array.from(new Set(groups.map(g => g.analyte)));
  const nFail = findings.filter(f => f.severity === 'fail').length, nWarn = findings.filter(f => f.severity === 'warn').length;
  return { engineVersion: ENGINE_VERSION, groups, findings, review: Array.from(review.values()), batches, analytes, meta: m,
    dashboard: { batches: batches.length, analytes: analytes.length, qcWarnings: nFail + nWarn, fail: nFail, warn: nWarn, info: findings.length - nFail - nWarn, reviewSamples: review.size, rows: records.length,
      samples: new Set(records.filter(r => r.type === 'SAMPLE').map(r => r.batchId + '||' + r.sampleId)).size } };
}
export function findGroup(result, batchId, analyte) { return result.groups.find(g => g.batchId === batchId && g.analyte === analyte) || null; }
