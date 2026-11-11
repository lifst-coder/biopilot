// BIOPILOT — 표 → 레코드 → 분석을 한 번에 실행하는 얇은 연결부. 웹앱, 시험, 스크립트가 같은 경로를 쓴다.
import { autoMap, buildRecords, toTable } from './parse.js';
import { analyze } from './analyze.js';
import { defaultRules } from './rules.js';
import { SCENARIOS } from './synth.js';

export function defaultSettings() { return { rules: defaultRules(), method: null, weighting: '1/x2', perGroup: {}, excluded: {} }; }
// rows: 머리글을 포함한 2차원 배열. options: { mapping, constants, typeMap, assumeDilutionOne, settings }
export function runRows(rows, options) {
  const opt = options || {}; const table = toTable({ rows });
  const am = autoMap(table.headers); const mapping = opt.mapping || am.mapping;
  const built = buildRecords(table, mapping, { constants: opt.constants, typeMap: opt.typeMap, assumeDilutionOne: opt.assumeDilutionOne });
  if (built.blocked) return { table, mapping, built, result: null };
  const settings = opt.settings || defaultSettings();
  const result = analyze(built.records, settings, { hasIs: built.stats.hasIs, hasRt: built.stats.hasRt, hasOrder: built.stats.hasOrder, hasDilution: built.stats.hasDilution });
  return { table, mapping, confidence: am.confidence, built, result, settings };
}

// 정답표와 비교. 탐지 단위는 (오류 코드, 분석물)이며 fail·warn만 센다.
export function scoreScenario(result, scenarioId) {
  const scn = SCENARIOS.find(s => s.id === scenarioId); const key = (c, a) => c + '|' + a;
  const found = new Set(result.findings.filter(f => f.batchId === scn.batch && f.severity !== 'info').map(f => key(f.code, f.analyte)));
  const expected = scn.expected.map(e => key(e[0], e[1])), any = (scn.expectedAny || []).map(e => key(e[0], e[1])), allowed = new Set(scn.allowed.map(e => key(e[0], e[1])).concat(expected, any));
  const tp = expected.filter(k => found.has(k)), fn = expected.filter(k => !found.has(k));
  const anyHit = any.length ? any.some(k => found.has(k)) : null;
  const fp = Array.from(found).filter(k => !allowed.has(k));
  const detected = fn.length === 0 && (anyHit === null || anyHit) && (expected.length + any.length > 0);
  return { scenario: scn.id, name: scn.name, tp, fn, fp, anyHit, anyOf: any, collateral: Array.from(found).filter(k => allowed.has(k) && !expected.includes(k) && !any.includes(k)), detected, clean: fp.length === 0, found: Array.from(found) };
}
