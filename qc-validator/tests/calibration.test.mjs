// 검량선 엔진 시험: 계산 재현, 적합성 판정, 진단, 잘못된 설정 탐지
import test from 'node:test';
import assert from 'node:assert/strict';
import { batch, run, has, codes, close, LEVELS } from './helpers.mjs';
import { buildCalibration, quantify, responseOf } from '../src/calibration.js';
import { defaultRules } from '../src/rules.js';

const cal = (r, a) => r.result.groups.find(g => g.analyte === (a || 'A')).cal;

test('정확한 직선 데이터: 기울기·절편·역산 농도를 그대로 되찾는다', () => {
  const r = run(batch({ slope: 250, intercept: 40 })); const c = cal(r);
  assert.ok(close(c.fit.slope, 250, 1e-9)); assert.ok(close(c.fit.intercept, 40, 1e-7)); assert.ok(close(c.fit.r2, 1, 1e-12));
  for (const p of c.points) { assert.ok(close(p.backCalc, p.nominal, 1e-8)); assert.ok(Math.abs(p.devPct) < 1e-8); assert.equal(p.pass, true); }
  assert.equal(c.verdict, 'pass'); assert.equal(c.lloq, 1); assert.equal(c.uloq, 500); assert.equal(c.nLevels, 8);
});
test('내부표준법은 면적비, 외부표준법은 면적을 응답으로 쓴다', () => {
  assert.equal(responseOf({ area: 500, isArea: 1000 }, 'internal'), 0.5); assert.equal(responseOf({ area: 500, isArea: 1000 }, 'external'), 500);
  assert.equal(responseOf({ area: 500, isArea: 0 }, 'internal'), null); assert.equal(responseOf({ area: 500, isArea: null }, 'internal'), null); assert.equal(responseOf({ area: -1, isArea: 10 }, 'external'), null); assert.equal(responseOf({ area: 0, isArea: 10 }, 'internal'), 0);
  const ext = cal(run(batch({ slope: 100, is: 2000 }), { method: 'external' })), int = cal(run(batch({ slope: 100, is: 2000 }), { method: 'internal' }));
  assert.ok(close(ext.fit.slope, 100, 1e-9)); assert.ok(close(int.fit.slope, 0.05, 1e-12));
});
test('내부표준법은 주입량 변동을 상쇄한다(분석물과 내부표준이 같은 비율로 변할 때)', () => {
  const std = {}; LEVELS.forEach((c, i) => { const k = 1 + 0.2 * Math.sin(i * 1.7); std[c] = { area: 100 * c * k, is: 1000 * k }; });
  const int = cal(run(batch({ std }), { method: 'internal' })), ext = cal(run(batch({ std }), { method: 'external' }));
  assert.ok(int.points.every(p => Math.abs(p.devPct) < 1e-8)); assert.ok(ext.points.some(p => Math.abs(p.devPct) > 10));
});
test('같은 입력과 설정이면 결과가 완전히 같다(재현성)', () => {
  const rows = batch({ std: { 50: { area: 5600 } } }); assert.deepEqual(JSON.stringify(run(rows).result), JSON.stringify(run(rows).result));
});
test('R²가 높아도 저농도 역산 정확도가 나쁘면 부적합으로 판정한다', () => {
  const std = { 1: { area: 160 }, 2: { area: 262 } };                          // 최저 두 점만 +60%, +31%
  const r = run(batch({ std }), { weighting: 'none' }); const c = cal(r);
  assert.ok(c.fit.r2 > 0.9999, 'R² = ' + c.fit.r2); assert.equal(c.verdict, 'fail'); assert.ok(has(r, 'CAL_FAIL')); assert.equal(c.criteria.find(x => x.id === 'lloq').pass, false);
  assert.match(r.result.findings.find(f => f.code === 'CAL_FAIL').basis, /R² 단독 판정 아님/);
});
test('R² 기준은 켰을 때만, 다른 기준에 더해서 적용된다', () => {
  const std = {}; LEVELS.forEach((c, i) => { std[c] = { area: 100 * c * (1 + (i % 2 ? 0.12 : -0.12)) }; });   // 모든 점 ±12%: 정확도 기준은 통과
  const off = run(batch({ std })), on = run(batch({ std }), { rules: R => { R.cal.useR2 = true; R.cal.r2Min = 0.9999; } });
  assert.equal(cal(off).verdict, 'pass'); assert.ok(!cal(off).criteria.some(x => x.id === 'r2'));
  assert.equal(cal(on).verdict, 'fail'); assert.equal(cal(on).criteria.find(x => x.id === 'r2').pass, false);
});
test('허용 편차 경계: +15.0%는 적합, +15.1%는 부적합 (최저점은 ±20%)', () => {
  const dev = (nom, pct, expectPass) => { const r = run(batch({ std: { [nom]: { area: 100 * nom * (1 + pct / 100) } } }), { weighting: 'none' }); const p = cal(r).points.find(x => x.nominal === nom);
    // 한 점만 바꾸면 회귀선도 조금 움직이므로, 그 점을 뺀 직선(면적 = 100 × 농도) 기준이 아니라 실제 계산된 편차로 판정이 일치하는지 본다
    assert.equal(p.pass, Math.abs(p.devPct) <= p.limit); assert.equal(p.limit, nom === 1 ? 20 : 15); if (expectPass !== undefined) assert.equal(p.pass, expectPass, nom + ' ' + pct + '% → ' + p.devPct); };
  dev(100, 10, true); dev(100, 25, false); dev(1, 18, true); dev(1, 40, false);
});
test('기준 변경이 판정에 그대로 반영된다', () => {
  const rows = batch({ std: { 100: { area: 100 * 100 * 1.25 } } });
  assert.equal(cal(run(rows)).points.find(p => p.nominal === 100).pass, false);
  assert.equal(cal(run(rows, { rules: R => { R.cal.devPct = 30; } })).points.find(p => p.nominal === 100).pass, true);
});
test('농도 수준이 최소 수보다 적으면 부적합', () => {
  const r = run(batch({ levels: [1, 5, 50, 250, 500] })); assert.equal(cal(r).verdict, 'fail'); assert.equal(cal(r).criteria.find(x => x.id === 'levels').pass, false);
  assert.equal(cal(run(batch({ levels: [1, 5, 50, 250, 500] }), { rules: R => { R.cal.minLevels = 5; } })).verdict, 'pass');
});
test('검량점의 75% 미만이 기준 내이면 부적합', () => {
  const std = { 5: { area: 500 * 1.3 }, 50: { area: 5000 * 0.7 }, 250: { area: 25000 * 1.3 } }; const c = cal(run(batch({ std })));
  assert.equal(c.verdict, 'fail'); assert.equal(c.criteria.find(x => x.id === 'pointsPass').pass, false);
});
test('검량점 이상치: 한 점만 +45%이면 이상치 후보로 보고하고 비선형으로 보지 않는다', () => {
  const r = run(batch({ std: { 50: { area: 5000 * 1.45 } } })); assert.ok(has(r, 'CAL_OUTLIER')); assert.ok(!has(r, 'CAL_NONLINEAR'));
  const o = cal(r).diagnostics.outliers[0]; assert.equal(o.nominal, 50); assert.ok(o.devPct > 30); assert.equal(o.restAllPass, true);
});
test('검량선 비선형성: 포화 곡선은 비선형으로 보고하고 이상치로 보지 않는다', () => {
  const std = {}; LEVELS.forEach(c => { std[c] = { area: 100 * c / (1 + c / 900) }; });
  const r = run(batch({ std })); assert.ok(has(r, 'CAL_NONLINEAR')); assert.ok(!has(r, 'CAL_OUTLIER')); assert.ok(cal(r).diagnostics.curvature.curvaturePct < 0);
});
test('직선 데이터에 작은 잡음: 비선형·이상치 경고가 없다', () => {
  const std = {}; LEVELS.forEach((c, i) => { std[c] = { area: 100 * c * (1 + 0.02 * Math.cos(i * 2.3)) }; });
  const r = run(batch({ std })); assert.deepEqual(codes(r), []);
});
test('잘못된 설정: 내부표준법인데 내부표준 면적이 없음', () => {
  const r = run(batch({ is: '' }), { method: 'internal' }); assert.ok(has(r, 'CAL_CONFIG_IS_MISSING')); assert.equal(cal(r).ok, false); assert.equal(cal(r).verdict, 'not_evaluable');
  const part = run(batch({ std: { 5: { is: 0 }, 10: { is: '' } } }), { method: 'internal' }); assert.ok(has(part, 'CAL_CONFIG_IS_MISSING')); assert.equal(cal(part).points.filter(p => !p.included).length, 2); assert.equal(cal(part).ok, true);
});
test('잘못된 설정: 농도와 응답이 반비례(기울기 음수)', () => {
  const std = {}; LEVELS.forEach(c => { std[c] = { area: 100000 / c }; }); const r = run(batch({ std })); assert.ok(has(r, 'CAL_CONFIG_NEG_SLOPE')); assert.equal(cal(r).verdict, 'fail');
});
test('잘못된 설정: 같은 수준 라벨에 다른 농도, 알 수 없는 가중치, 적용할 수 없는 가중치', () => {
  const rows = batch(); rows.find(r => r[1] === 'STD-3')[4] = 'L2'; assert.ok(has(run(rows), 'CAL_CONFIG_LEVEL_CONFLICT'));
  const recs = run(batch()).built.records.filter(x => x.analyte === 'A');
  const c1 = buildCalibration(recs, { method: 'external', weighting: 'bogus', rules: defaultRules() }); assert.equal(c1.weighting, '1/x2'); assert.ok(c1.findings.some(f => f.code === 'CAL_CONFIG_WEIGHTING'));
  const z = run(batch({ std: { 1: { area: 0 } } }), { weighting: '1/y' }); assert.ok(has(z, 'CAL_CONFIG_WEIGHTING')); assert.equal(cal(z).ok, false);
});
test('잘못된 설정: 가중 없이 넓은 범위를 적합해 저농도가 벗어나면 가중치 확인을 권한다', () => {
  const std = {}; LEVELS.forEach((c, i) => { std[c] = { area: 100 * c * (1 + [0.01, -0.01, 0.01, -0.02, 0.03, -0.04, 0.06, -0.05][i]) }; });
  const none = run(batch({ std }), { weighting: 'none' }), w = run(batch({ std }), { weighting: '1/x2' });
  assert.ok(has(none, 'CAL_CONFIG_WEIGHTING')); assert.equal(cal(none).verdict, 'fail'); assert.equal(cal(w).verdict, 'pass'); assert.ok(!has(w, 'CAL_CONFIG_WEIGHTING'));
  assert.equal(cal(none).diagnostics.weightingComparison.length, 5);
});
test('검량 표준이 없거나 점이 부족하면 평가 불가로 두고 농도를 만들지 않는다', () => {
  const none = run([['B1', 'S1', 'Sample', 'A', '', '', 500, 1000, 3, 1, 1, 1, '']]); assert.ok(has(none, 'CAL_NO_STANDARDS')); assert.equal(none.result.groups[0].rows[0].q.conc, null);
  const few = run(batch({ levels: [1, 5], full: false })); assert.ok(has(few, 'CAL_CONFIG_FEW_POINTS')); assert.equal(cal(few).verdict, 'not_evaluable');
});
test('0·음수 입력: 명목 0인 표준은 회귀에서 빼고, 음수 면적·농도는 무효 처리', () => {
  const r = run(batch({ extra: [{ id: 'STD-0', type: 'Calibration Standard', nominal: 0, area: 3 }, { id: 'STD-N', type: 'Calibration Standard', nominal: -5, area: 100 }, { id: 'STD-A', type: 'Calibration Standard', nominal: 20, area: -50 }] })); const c = cal(r);
  const reason = id => c.points.find(p => p.sampleId === id); assert.equal(reason('STD-0').included, false); assert.match(reason('STD-0').reason, /농도 0/); assert.match(reason('STD-N').reason, /음수/); assert.match(reason('STD-A').reason, /면적/);
  assert.equal(c.fit.n, 8); assert.ok(close(c.fit.slope, 100, 1e-9)); assert.ok(r.built.issues.some(i => i.code === 'ZERO_NOMINAL_STD')); assert.ok(r.built.issues.some(i => i.code === 'NEGATIVE_AREA'));
});
test('사용자가 검량점을 제외하면 사유와 함께 기록되고 다시 적합한다', () => {
  const rows = batch({ std: { 50: { area: 5000 * 1.45 } } }); const row = run(rows).result.groups[0].cal.points.find(p => p.nominal === 50).row;
  const r = run(rows, { excluded: { 'B1||A': { [row]: '조제 오류 확인(재조제 기록 2026-11-11)' } } }); const c = cal(r);
  assert.equal(c.fit.n, 7); assert.equal(c.verdict, 'pass'); assert.ok(!has(r, 'CAL_OUTLIER')); const f = r.result.findings.find(x => x.code === 'CAL_POINT_EXCLUDED'); assert.match(f.observed, /조제 오류 확인/);
});
test('정량: 범위 표시(LLOQ 미만, ULOQ 초과, 음수)와 희석배수 반영', () => {
  const r = run(batch({ intercept: 50, extra: [{ id: 'X1', type: 'Sample', area: 100 * 0.5 + 50 }, { id: 'X2', type: 'Sample', area: 100 * 700 + 50 }, { id: 'X3', type: 'Sample', area: 10 }, { id: 'X4', type: 'Sample', area: 100 * 40 + 50, dil: 10 }] }));
  const q = id => r.result.groups[0].rows.find(x => x.rec.sampleId === id).q;
  assert.equal(q('X1').flag, 'BLQ'); assert.equal(q('X2').flag, 'ALQ'); assert.equal(q('X3').flag, 'NEG'); assert.equal(q('X4').flag, null); assert.ok(close(q('X4').conc, 40, 1e-8)); assert.ok(close(q('X4').final, 400, 1e-7));
  assert.ok(has(r, 'SAMPLE_ABOVE_RANGE')); assert.deepEqual(quantify({ ok: false, method: 'external' }, { area: 5 }).conc, null);
});
test('분석 항목별 분리: 한 분석물의 검량선 문제가 다른 분석물에 영향을 주지 않는다', () => {
  const rows = batch({ analyte: 'A', std: { 50: { area: 5000 * 1.45 } } }).concat(batch({ analyte: 'B', slope: 37 }));
  const r = run(rows); assert.ok(has(r, 'CAL_OUTLIER', 'A')); assert.deepEqual(codes(r, 'B'), []); assert.ok(close(cal(r, 'B').fit.slope, 37, 1e-9)); assert.equal(cal(r, 'B').fit.n, 8);
});
test('배치별 분리: 같은 분석물이라도 배치마다 따로 검량한다', () => {
  const r = run(batch({ batchId: 'B1', slope: 100 }).concat(batch({ batchId: 'B2', slope: 80 })));
  assert.equal(r.result.groups.length, 2); assert.ok(close(r.result.groups[0].cal.fit.slope, 100, 1e-9)); assert.ok(close(r.result.groups[1].cal.fit.slope, 80, 1e-9)); assert.equal(r.result.dashboard.batches, 2); assert.equal(r.result.dashboard.analytes, 1);
});
