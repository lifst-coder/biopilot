// 합성 오류 시나리오 시험: 정답표 대비 탐지, 오탐·미탐률, 진단의 사실/가설 분리
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCsv, decodeText } from '../src/parse.js';
import { runRows, scoreScenario } from '../src/pipeline.js';
import { generateDataset, SCENARIOS, allScenarioIds } from '../src/synth.js';
import { diagnose, summarize, STANDING } from '../src/diagnose.js';

const data = join(dirname(fileURLToPath(import.meta.url)), '..', 'data');
const key = JSON.parse(readFileSync(join(data, 'answer_key.json'), 'utf8'));
const load = p => runRows(parseCsv(decodeText(readFileSync(join(data, p))).text).rows);

test('정답표는 8개 오류 시나리오와 정상 배치를 포함하고 파일과 일치한다', () => {
  assert.equal(key.scenarios.length, 9); assert.deepEqual(key.scenarios.map(s => s.id), SCENARIOS.map(s => s.id));
  for (const s of key.scenarios) { assert.equal(s.expectedCauseStatus, '원인 미확정'); assert.ok(s.rootCause.length > 3); }
  const regenerated = generateDataset(['S4'], key.seed).map(r => r.join(',')).join('\n'); const onDisk = readFileSync(join(data, 'scenarios/S4_B04-SPIKE.csv'), 'utf8').trim().replace(/\r\n/g, '\n');
  assert.equal(regenerated, onDisk);
});
for (const s of key.scenarios) test('시나리오 ' + s.id + ' ' + s.name + ': 정답표의 항목을 탐지하고 그 밖의 경고는 없다', () => {
  const r = load(s.file); const sc = scoreScenario(r.result, s.id);
  assert.deepEqual(sc.fn, [], '미탐: ' + sc.fn.join(', ')); assert.deepEqual(sc.fp, [], '오탐: ' + sc.fp.join(', '));
  if (s.expectedAny.length) assert.equal(sc.anyHit, true);
  if (s.id === 'S0') assert.equal(r.result.findings.filter(f => f.severity !== 'info').length, 0); else assert.equal(sc.detected, true);
});
test('전체 배치 파일: 9개 배치가 서로 섞이지 않고 각각 같은 결과를 낸다', () => {
  const all = load('synthetic_all_batches.csv'); assert.equal(all.result.dashboard.batches, 9); assert.equal(all.result.dashboard.analytes, 3); assert.equal(all.result.groups.length, 27);
  for (const s of key.scenarios) { const one = load(s.file); const a = all.result.findings.filter(f => f.batchId === s.batch).map(f => f.id + '|' + f.observed).sort(), b = one.result.findings.map(f => f.id + '|' + f.observed).sort(); assert.deepEqual(a, b, s.id); }
});
test('오류를 넣지 않은 분석물은 깨끗하다(분석 항목별 분리)', () => {
  const clean = { S1: ['Carbamazepine', 'Sulfamethoxazole'], S2: ['Caffeine', 'Sulfamethoxazole'], S3: ['Carbamazepine', 'Sulfamethoxazole'], S4: ['Caffeine', 'Carbamazepine'], S5: ['Caffeine', 'Sulfamethoxazole'], S7: ['Carbamazepine', 'Sulfamethoxazole'] };
  for (const id of Object.keys(clean)) { const s = key.scenarios.find(x => x.id === id); const r = load(s.file); for (const a of clean[id]) assert.deepEqual(r.result.findings.filter(f => f.analyte === a && f.severity !== 'info').map(f => f.code), [], id + ' ' + a); }
});
test('오탐·미탐 평가(seed 60개): 시나리오별 탐지율 ≥ 95%, 오탐 없는 실행 ≥ 95%', () => {
  const N = 60; for (const s of SCENARIOS) { let det = 0, clean = 0; for (let seed = 101; seed <= 100 + N; seed++) { const sc = scoreScenario(runRows(generateDataset([s.id], seed)).result, s.id); if (sc.detected) det++; if (sc.clean) clean++; }
    if (s.id !== 'S0') assert.ok(det / N >= 0.95, s.id + ' 탐지율 ' + det + '/' + N); assert.ok(clean / N >= 0.95, s.id + ' 오탐 없는 실행 ' + clean + '/' + N); }
});
test('진단: 모든 카드가 관측 사실·가설·확인 항목·검증을 따로 갖고, 원인을 확정하지 않는다', () => {
  const all = load('synthetic_all_batches.csv'); const cards = diagnose(all.result); const nonInfo = all.result.findings.filter(f => f.severity !== 'info');
  assert.equal(cards.length, nonInfo.length);
  for (const c of cards) {
    assert.equal(c.causeStatus, '원인 미확정'); assert.ok(c.observations.length >= 1, c.code); assert.ok(typeof c.conclusion === 'string' && c.conclusion.length > 10);
    assert.ok(!/확정(된|됨|했|한다|합니다)(?!.*없)/.test(c.conclusion), c.conclusion);
    for (const h of c.hypotheses) { assert.ok(h.cause && Object.keys(STANDING).includes(h.standing)); assert.ok(Array.isArray(h.support) && Array.isArray(h.against)); assert.equal(typeof h.unknown, 'string'); }
    if (c.hypotheses.length) { assert.match(c.conclusion, /^원인 미확정/); assert.ok(c.hypotheses.length >= 2, c.code + ': 가설이 하나뿐이면 단정에 가깝다'); assert.ok(c.checks.length >= 2 && c.verifications.length >= 2); }
  }
  const causal = ['CAL_NONLINEAR', 'CAL_OUTLIER', 'MB_CONTAM', 'SPIKE_LOW', 'IS_RESPONSE', 'RT_SHIFT', 'QC_PRECISION', 'QC_ACCURACY'];
  for (const code of causal) assert.ok(cards.some(c => c.code === code && c.hypotheses.length >= 3), code);
});
test('진단: 관측 사실에는 엔진의 수치가 들어 있고, 가설의 근거는 데이터에서 계산된 문맥을 쓴다', () => {
  const s4 = load('scenarios/S4_B04-SPIKE.csv'); const c4 = diagnose(s4.result).find(c => c.code === 'SPIKE_LOW');
  assert.match(c4.observations.join(' '), /회수율은 4\d\.\d%/); assert.match(c4.observations.join(' '), /내부표준 면적은 검량 표준 평균의 \d+%/);
  const matrix = c4.hypotheses.find(h => /매질/.test(h.cause)); assert.ok(matrix.against.some(t => /바탕 첨가 시료/.test(t)), '매질이 없는 LCS도 낮다는 반대 근거가 있어야 한다');
  const s6 = load('scenarios/S6_B06-RT.csv'); const c6 = diagnose(s6.result).find(c => c.code === 'RT_SHIFT'); const sys = c6.hypotheses.find(h => /이동상/.test(h.cause)), mis = c6.hypotheses.find(h => /오인/.test(h.cause));
  assert.equal(sys.standing, 'supported'); assert.equal(mis.standing, 'weak'); assert.match(c6.conclusion, /구별되지 않는다/);
  const s5 = load('scenarios/S5_B05-IS.csv'); const c5 = diagnose(s5.result).find(c => c.code === 'IS_RESPONSE'); assert.match(c5.observations.join(' '), /농도를 모르는 시료라/);
  const s3 = load('scenarios/S3_B03-BLANK.csv'); const c3 = diagnose(s3.result).find(c => c.code === 'MB_CONTAM'); assert.ok(c3.hypotheses.find(h => /캐리오버/.test(h.cause)).against.length >= 1);
});
test('진단은 계산 결과를 바꾸지 않는다', () => {
  const r = load('synthetic_all_batches.csv'); const before = JSON.stringify(r.result); diagnose(r.result); summarize(r.result); assert.equal(JSON.stringify(r.result), before);
});
test('요약 문장의 숫자는 대시보드 값과 같다', () => {
  const r = load('synthetic_all_batches.csv'); const d = r.result.dashboard; const line = summarize(r.result)[0];
  assert.ok(line.includes('배치 ' + d.batches + '개') && line.includes('기준 미충족 ' + d.fail + '건') && line.includes('주의 ' + d.warn + '건') && line.includes('시료는 ' + d.reviewSamples + '개'));
  assert.equal(allScenarioIds().length, 9);
});
