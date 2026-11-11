// 합성 데이터 오탐·미탐 평가.  node scripts/evaluate.mjs [seed 수]
import { generateDataset, SCENARIOS } from '../src/synth.js';
import { runRows, scoreScenario } from '../src/pipeline.js';
export function evaluate(nSeeds) {
  const out = SCENARIOS.map(s => ({ id: s.id, name: s.name, runs: 0, detected: 0, clean: 0, missButFlagged: 0, fn: {}, fp: {} }));
  for (let seed = 1; seed <= nSeeds; seed++) for (const o of out) {
    const sc = scoreScenario(runRows(generateDataset([o.id], seed)).result, o.id); o.runs++;
    if (sc.detected) o.detected++; if (sc.clean) o.clean++;
    // 정답 유형으로는 못 잡았지만 같은 분석물에 다른 경고가 나온 경우(이상은 감지, 유형이 다름)
    const scn = SCENARIOS.find(x => x.id === o.id); const analytes = new Set(scn.expected.concat(scn.expectedAny || []).map(e => e[1]));
    if (!sc.detected && o.id !== 'S0' && sc.found.some(k => analytes.has(k.split('|')[1]))) o.missButFlagged++;
    for (const k of sc.fn) o.fn[k] = (o.fn[k] || 0) + 1; for (const k of sc.fp) o.fp[k] = (o.fp[k] || 0) + 1;
    if (sc.anyHit === false) o.fn['(정밀도 지표 중 하나)'] = (o.fn['(정밀도 지표 중 하나)'] || 0) + 1;
  }
  return out;
}
if (process.argv[1] && process.argv[1].endsWith('evaluate.mjs')) {
  const n = Number(process.argv[2] || 200); const t = Date.now(); const res = evaluate(n);
  for (const o of res) console.log(o.id.padEnd(3), o.name.padEnd(22), '탐지 ' + (o.id === 'S0' ? '  –  ' : (o.detected + '/' + o.runs).padEnd(7)), '오탐 없는 실행 ' + o.clean + '/' + o.runs, Object.keys(o.fn).length ? ' 미탐 ' + JSON.stringify(o.fn) : '', Object.keys(o.fp).length ? ' 오탐 ' + JSON.stringify(o.fp) : '');
  console.log((Date.now() - t) + 'ms');
}
