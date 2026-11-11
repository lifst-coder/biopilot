// QC 엔진 시험: 설정된 기준이 경계값에서 정확히 적용되는지, 평가 불가를 정직하게 보고하는지
import test from 'node:test';
import assert from 'node:assert/strict';
import { batch, run, has, codes, close } from './helpers.mjs';
import { defaultRules, profileRules, setRule, getRule, RULE_META, PROFILES } from '../src/rules.js';

const A = c => 100 * c;        // 기본 배치의 응답: 면적 = 100 × 농도 (외부표준법)
const grp = (r, a) => r.result.groups.find(g => g.analyte === (a || 'A'));
const x = (o) => batch({ extra: o });
const finding = (r, code) => r.result.findings.find(f => f.code === code);

test('기본 배치(오류 없음)는 경고가 없다', () => { const r = run(batch()); assert.deepEqual(codes(r), []); assert.equal(r.result.dashboard.qcWarnings, 0); assert.equal(r.result.dashboard.reviewSamples, 0); });

test('QC 정확도 경계: +15.0% 적합, +15.1% 부적합, LLOQ 수준은 ±20%', () => {
  const q = (nom, pct) => { const r = run(x([{ id: 'QX', type: 'QC', nominal: nom, area: A(nom) * (1 + pct / 100) }])); return grp(r).tables.qcItems.find(i => i.sampleId === 'QX'); };
  assert.equal(q(75, 15).pass, true); assert.equal(q(75, 15.1).pass, false); assert.equal(q(75, -15).pass, true); assert.equal(q(75, -15.1).pass, false);
  assert.equal(q(1, 19.9).pass, true); assert.equal(q(1, 20.1).pass, false); assert.ok(close(q(75, 15.1).rePct, 15.1, 1e-8));
});
test('QC 배치 기준: 전체의 2/3 미만 또는 한 수준의 50% 미만이면 미달', () => {
  const two = run(x([{ id: 'QM-3', type: 'QC', nominal: 75, area: A(75) * 1.3 }]));                        // 7개 중 1개 실패(86%): 개별만 실패
  assert.ok(has(two, 'QC_ACCURACY')); assert.ok(!has(two, 'QC_BATCH_FAIL'));
  const rows = batch(); rows.filter(r => r[1].startsWith('QC-L')).forEach(r => { r[6] = A(3) * 1.4; });  // 저농도 2개 모두 실패 → 수준 0%
  const lvl = run(rows); assert.ok(has(lvl, 'QC_BATCH_FAIL')); assert.match(finding(lvl, 'QC_BATCH_FAIL').observed, /수준별 미달: 3 \(0\/2\)/);
  const rows2 = batch(); rows2.filter(r => r[2] === 'QC').slice(0, 3).forEach(r => { r[6] = r[6] * 1.4; });  // 6개 중 3개 실패(50%) → 전체 기준 미달
  assert.ok(has(run(rows2), 'QC_BATCH_FAIL')); assert.ok(!has(run(rows2, { rules: R => { R.qc.minPassPctAll = 50; R.qc.minPassPctLevel = 0; } }), 'QC_BATCH_FAIL'));
});
test('QC 통계: 평균·표준편차·RSD·평균 상대오차', () => {
  const rows = batch(); const m = rows.filter(r => r[1].startsWith('QC-M')); m[0][6] = A(70); m[1][6] = A(80);
  const lv = grp(run(rows)).tables.qcLevels.find(l => l.nominal === 75); assert.ok(close(lv.mean, 75, 1e-8)); assert.ok(close(lv.sd, Math.sqrt(50), 1e-8)); assert.ok(close(lv.rsd, Math.sqrt(50) / 75 * 100, 1e-8)); assert.ok(close(lv.meanRePct, 0, 1e-8)); assert.equal(lv.n, 2);
});
test('QC 정밀도: RSD가 기준을 넘으면 보고', () => {
  const rows = batch(); const m = rows.filter(r => r[1].startsWith('QC-M')); m[0][6] = A(66); m[1][6] = A(84);   // RSD 17%
  const r = run(rows); assert.ok(has(r, 'QC_PRECISION')); assert.ok(!has(run(rows, { rules: R => { R.qc.rsdPct = 20; } }), 'QC_PRECISION'));
});
test('바탕 시료 경계(응답 방식): LLOQ 응답의 20% 이하 적합, 초과 부적합', () => {
  const mb = area => { const rows = batch(); rows.find(r => r[1] === 'MB-1')[6] = area; return run(rows); };
  assert.ok(!has(mb(20), 'MB_CONTAM')); assert.ok(has(mb(20.5), 'MB_CONTAM')); assert.ok(close(grp(mb(60)).tables.blanks.find(b => b.sampleId === 'MB-1').pctOfLloq, 60, 1e-9));
  const cb = batch(); cb.find(r => r[1] === 'CB-1')[6] = 50; const r = run(cb); assert.ok(has(r, 'CB_CONTAM')); assert.ok(!has(r, 'MB_CONTAM'));
});
test('바탕 시료(농도 방식): LLOQ 농도의 1/3 미만이어야 함', () => {
  const mb = area => { const rows = batch(); rows.find(r => r[1] === 'MB-1')[6] = area; return run(rows, { rules: R => { R.blank.mode = 'conc'; } }); };
  assert.ok(!has(mb(30), 'MB_CONTAM')); assert.ok(has(mb(40), 'MB_CONTAM'));     // 농도 0.30 대 0.40, 한계 0.333
});
test('바탕 진단용 문맥: 직전 주입이 고농도인지 기록한다', () => {
  const r = run(batch({ extra: [{ id: 'HI', type: 'Sample', area: A(480) }, { id: 'MB-2', type: 'Method Blank', area: 90 }] }));
  const b = grp(r).tables.blanks.find(i => i.sampleId === 'MB-2'); assert.equal(b.prev.sampleId, 'HI'); assert.equal(b.prev.aboveHalfUloq, true); assert.equal(b.pass, false);
});
test('첨가 회수율 경계: 70%·130%는 적합, 그 밖은 부적합', () => {
  const sp = pct => { const rows = batch(); rows.find(r => r[1] === 'LCS-1')[6] = A(50) * pct / 100; return run(rows); };
  assert.ok(!has(sp(70), 'SPIKE_LOW')); assert.ok(has(sp(69.9), 'SPIKE_LOW')); assert.ok(!has(sp(130), 'SPIKE_HIGH')); assert.ok(has(sp(130.1), 'SPIKE_HIGH'));
  assert.ok(close(grp(sp(45)).tables.spikes[0].recoveryPct, 45, 1e-8)); assert.ok(!has(run(batch({}), { rules: R => { R.spike.minPct = 40; } }), 'SPIKE_LOW'));
});
test('매질 첨가: 원시료 농도를 빼고 계산하며, 원시료가 없으면 바탕 첨가 방식으로 계산했음을 밝힌다', () => {
  const r = run(x([{ id: 'P1', type: 'Sample', area: A(30) }, { id: 'P1-MS', type: 'Spike', nominal: 50, area: A(75) }, { id: 'ZZ', type: 'Spike', nominal: 50, area: A(48), parent: 'P1' }, { id: 'LONE-MS', type: 'Spike', nominal: 50, area: A(50) }]));
  const s = id => grp(r).tables.spikes.find(i => i.sampleId === id);
  assert.equal(s('P1-MS').kind, 'matrix'); assert.ok(close(s('P1-MS').recoveryPct, 90, 1e-8)); assert.equal(s('ZZ').parentId, 'P1'); assert.ok(close(s('ZZ').recoveryPct, 36, 1e-8)); assert.equal(s('LONE-MS').kind, 'blank'); assert.ok(close(s('LONE-MS').recoveryPct, 100, 1e-8));
  assert.ok(has(r, 'SPIKE_LOW')); assert.match(finding(r, 'SPIKE_LOW').basis, /원시료가 연결되지 않은/);
});
test('중복 시료: RPD 경계 20%, 연결 방식 세 가지(원시료 ID, 같은 ID, -DUP 접미사)', () => {
  const d = (a, b) => run(x([{ id: 'D1', type: 'Sample', area: A(a) }, { id: 'D1-DUP', type: 'Duplicate', area: A(b) }]));
  assert.ok(!has(d(110, 90), 'DUP_RPD')); assert.ok(has(d(110.1, 89.9), 'DUP_RPD')); assert.ok(close(grp(d(110, 90)).tables.dups.find(i => i.sampleId === 'D1').rpd, 20, 1e-8));
  const byParent = run(x([{ id: 'K7', type: 'Sample', area: A(100) }, { id: 'whatever', type: 'Duplicate', area: A(60), parent: 'K7' }])); assert.ok(has(byParent, 'DUP_RPD'));
  const sameId = run(x([{ id: 'K8', type: 'Sample', area: A(100), rep: 1 }, { id: 'K8', type: 'Sample', area: A(60), rep: 2 }])); assert.ok(has(sameId, 'DUP_RPD'));
  const orphan = run(x([{ id: 'NOPE-DUP', type: 'Duplicate', area: A(60) }])); assert.ok(orphan.result.findings.some(f => f.code === 'DUP_NO_PARENT'));
});
test('3회 이상 반복: RSD로 평가', () => {
  const r = run(x([100, 130, 70].map((v, i) => ({ id: 'R1', type: 'Sample', area: A(v), rep: i + 1 })))); assert.ok(has(r, 'REP_RSD')); assert.ok(close(grp(r).tables.reps[0].rsd, 30, 1e-8));
  assert.ok(!has(run(x([100, 104, 96].map((v, i) => ({ id: 'R1', type: 'Sample', area: A(v), rep: i + 1 })))), 'REP_RSD'));
});
test('정량한계 미만의 중복은 평가하지 않고 그 사실을 보고한다', () => {
  const r = run(x([{ id: 'L1', type: 'Sample', area: A(0.4) }, { id: 'L1-DUP', type: 'Duplicate', area: A(0.8) }])); assert.ok(!has(r, 'DUP_RPD'));
  assert.ok(r.result.findings.some(f => f.code === 'NOT_EVALUATED' && /정량한계 미만/.test(f.observed)));
});
test('내부표준 응답 경계: 검량 표준 평균의 50–150%', () => {
  const is = v => run(x([{ id: 'I1', type: 'Sample', area: A(20), is: v }]), { method: 'internal' });
  assert.ok(!has(is(500), 'IS_RESPONSE')); assert.ok(has(is(499), 'IS_RESPONSE')); assert.ok(!has(is(1500), 'IS_RESPONSE')); assert.ok(has(is(1501), 'IS_RESPONSE'));
  assert.ok(!has(run(x([{ id: 'I1', type: 'Sample', area: A(20), is: 400 }]), { method: 'internal', rules: R => { R.is.minPct = 30; } }), 'IS_RESPONSE'));
  assert.ok(close(grp(is(300)).tables.isItems.find(i => i.sampleId === 'I1').pct, 30, 1e-9));
});
test('내부표준 표류: 주입 순서에 따른 유의한 추세를 보고', () => {
  const rows = batch(); rows.forEach((r, i) => { r[7] = 1000 * (1 - 0.5 * i / (rows.length - 1)); r[6] = r[6] * r[7] / 1000; });   // 분석물도 같은 비율로 감소 → 면적비 유지
  const r = run(rows, { method: 'internal' }); assert.ok(has(r, 'IS_DRIFT')); assert.ok(finding(r, 'IS_DRIFT').details.trend.changePct < -40); assert.equal(grp(r).cal.verdict, 'pass');
});
test('머무름 시간 경계: ±0.100분 적합, 0.101분 부적합, 상대 방식 전환', () => {
  const rt = (v, f) => run(x([{ id: 'T1', type: 'Sample', area: A(20), rt: v }]), { rules: f });
  assert.ok(!has(rt(3.1), 'RT_SHIFT')); assert.ok(has(rt(3.101), 'RT_SHIFT')); assert.ok(has(rt(2.899), 'RT_SHIFT')); assert.ok(!has(rt(2.9), 'RT_SHIFT'));
  assert.ok(!has(rt(3.14, R => { R.rt.mode = 'rel'; R.rt.relPct = 5; }), 'RT_SHIFT')); assert.ok(has(rt(3.16, R => { R.rt.mode = 'rel'; R.rt.relPct = 5; }), 'RT_SHIFT'));
});
test('필수 QC 누락: 무엇이 몇 개 부족한지 보고하고, 요구 수를 0으로 두면 보고하지 않는다', () => {
  const r = run(batch({ full: false })); const f = finding(r, 'QC_MISSING'); assert.ok(f); assert.deepEqual(f.details.missing.map(m => m.what), ['방법 바탕', '검량 바탕', 'QC 농도 수준', '첨가 시료', '중복 시료 쌍']);
  const off = run(batch({ full: false }), { rules: R => { for (const k of Object.keys(R.required)) R.required[k] = 0; } }); assert.ok(!has(off, 'QC_MISSING'));
  const rows = batch().filter(r => r[1] !== 'QC-H-2'); assert.match(finding(run(rows), 'QC_MISSING').observed, /QC 수준별 반복\(400\)/);
});
test('희석배수가 없는 QC·첨가 시료는 평가 불가로 보고하고 1을 넣지 않는다', () => {
  const rows = batch(); rows.filter(r => r[2] === 'QC' || r[2] === 'Spike').forEach(r => { r[9] = ''; });
  const r = run(rows); assert.ok(!has(r, 'QC_ACCURACY')); const ne = r.result.findings.filter(f => f.code === 'NOT_EVALUATED').map(f => f.observed).join(' | '); assert.match(ne, /QC 6개/); assert.match(ne, /희석배수 없음/); assert.match(ne, /첨가 시료 1개/);
  const on = run(rows, { options: { assumeDilutionOne: true } }); assert.deepEqual(codes(on), []); assert.equal(grp(on).tables.qcItems.filter(i => i.pass).length, 6);
});
test('희석한 QC는 희석배수를 반영해 명목값과 비교한다', () => {
  const r = run(x([{ id: 'DQC', type: 'QC', nominal: 2000, area: A(200), dil: 10 }])); const q = grp(r).tables.qcItems.find(i => i.sampleId === 'DQC'); assert.ok(close(q.measured, 2000, 1e-6)); assert.equal(q.pass, true);
});
test('분석 항목별 분리: 한 분석물의 QC 문제는 그 분석물에만 보고된다', () => {
  const a = batch({ analyte: 'A' }); a.find(r => r[1] === 'LCS-1')[6] = A(50) * 0.4; a.find(r => r[1] === 'MB-1')[6] = 80;
  const r = run(a.concat(batch({ analyte: 'B', slope: 55 }), batch({ analyte: 'C', slope: 7 })));
  assert.deepEqual(codes(r, 'A').sort(), ['MB_CONTAM', 'SPIKE_LOW']); assert.deepEqual(codes(r, 'B'), []); assert.deepEqual(codes(r, 'C'), []); assert.equal(r.result.dashboard.analytes, 3);
});
test('검토 필요 시료: 시료 수준 사유와 배치 수준 사유를 구분해 센다', () => {
  const r = run(x([{ id: 'U1', type: 'Sample', area: A(20), rt: 3.5 }, { id: 'U2', type: 'Sample', area: A(30) }])); assert.deepEqual(r.result.review.map(v => v.sampleId), ['U1']);
  const rows = batch({ extra: [{ id: 'U2', type: 'Sample', area: A(30) }] }); rows.find(q => q[1] === 'MB-1')[6] = 90;
  const b = run(rows); assert.deepEqual(b.result.review.map(v => v.sampleId).sort(), ['S01', 'U2']); assert.ok(b.result.review.every(v => v.reasons[0].level === 'batch'));
});
test('규칙 설정: 잘못된 값은 거부하고 기존 값을 유지한다', () => {
  const R = defaultRules(); assert.ok(setRule(R, 'qc.devPct', 'abc').error); assert.ok(setRule(R, 'qc.devPct', '').error); assert.ok(setRule(R, 'qc.devPct', -5).error); assert.ok(setRule(R, 'qc.devPct', 1e6).error); assert.ok(setRule(R, 'cal.minLevels', 5.5).error); assert.ok(setRule(R, 'nope.x', 1).error); assert.ok(setRule(R, 'rt.mode', 'weird').error);
  assert.equal(R.qc.devPct, 15); assert.equal(R.profile, 'example-default');
  assert.ok(setRule(R, 'qc.devPct', '12.5').ok); assert.equal(getRule(R, 'qc.devPct'), 12.5); assert.equal(R.profile, 'custom'); assert.ok(setRule(R, 'cal.useR2', true).ok); assert.equal(R.cal.useR2, true);
  assert.ok(setRule(R, 'spike.minPct', 150).warning);
});
test('규칙 메타데이터: 모든 규칙에 기본값과 출처가 있고, 프로파일은 예시임을 밝힌다', () => {
  const R = defaultRules(); for (const m of RULE_META) { assert.notEqual(getRule(R, m.path), undefined, m.path); assert.ok(m.source && m.source.length > 5, m.path); }
  for (const id of Object.keys(PROFILES)) { assert.match(PROFILES[id].name, /예시/); const p = profileRules(id); assert.equal(p.profile, id); }
  assert.equal(profileRules('example-sante').cal.devPct, 20); assert.equal(profileRules('example-epa537').blank.mode, 'conc'); assert.equal(profileRules('nope').profile, 'example-default');
});
