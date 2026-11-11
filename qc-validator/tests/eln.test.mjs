// BioPilot 본편(ELN) 연결 시험과 빌드 산출물 일치 시험
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCsv, decodeText } from '../src/parse.js';
import { runRows } from '../src/pipeline.js';
import { elnExport, elnCsv, ELN_CONTRACT } from '../src/eln.js';
import { batch, run } from './helpers.mjs';
import { buildPages } from '../scripts/build.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = p => runRows(parseCsv(decodeText(readFileSync(join(root, 'data', p))).text).rows);

test('ELN 계약: 열 이름과 순서가 본편 DATASET_KIND_REGISTRY(calibration@1, recovery@1)와 같다', () => {
  assert.deepEqual(ELN_CONTRACT.calibration.columns, ['injection_id', 'level_ng_ml', 'analyte', 'analyte_area', 'is_area']);
  assert.deepEqual(ELN_CONTRACT.recovery.columns, ['injection_id', 'sample_id', 'analyte', 'spike_ng_g', 'analyte_area', 'is_area']);
});
test('ELN 내보내기: 검량 표준과 연결되지 않은 첨가 시료의 원자료를 그대로 옮긴다', () => {
  const r = load('scenarios/S0_B00-NORMAL.csv'); const ex = elnExport(r.result, 'B00-NORMAL');
  assert.deepEqual(ex.calibration.rows[0], ELN_CONTRACT.calibration.columns); assert.equal(ex.calibration.rows.length - 1, 24);        // 표준 8 × 분석물 3
  assert.deepEqual(ex.recovery.rows[0], ELN_CONTRACT.recovery.columns); assert.equal(ex.recovery.rows.length - 1, 3);                 // LCS-01 × 분석물 3
  const src = r.built.records.find(x => x.sampleId === 'STD-5' && x.analyte === 'Caffeine'); const row = ex.calibration.rows.find(x => x[0] === 'STD-5' && x[2] === 'Caffeine');
  assert.deepEqual(row, ['STD-5', src.nominal, 'Caffeine', src.area, src.isArea]);
  const lcs = r.built.records.find(x => x.sampleId === 'LCS-01' && x.analyte === 'Carbamazepine'); assert.deepEqual(ex.recovery.rows.find(x => x[2] === 'Carbamazepine'), ['LCS-01', 'LCS-01', 'Carbamazepine', lcs.nominal, lcs.area, lcs.isArea]);
});
test('ELN 내보내기: 원시료가 연결된 매질 첨가는 옮기지 않고 사유를 남긴다', () => {
  const ex = elnExport(load('scenarios/S0_B00-NORMAL.csv').result, 'B00-NORMAL');
  assert.equal(ex.recovery.skipped.length, 3); assert.ok(ex.recovery.skipped.every(s => s.sampleId === 'S05-MS' && /원시료\(S05\)/.test(s.reason)));
  assert.ok(ex.notes.some(n => /단위는 검량 ng\/mL, 첨가 ng\/g/.test(n)));
});
test('ELN 내보내기: 계산 결과(농도·회수율·판정)는 넣지 않고, 오류 시나리오의 원자료도 고치지 않는다', () => {
  const r = load('scenarios/S4_B04-SPIKE.csv'); const ex = elnExport(r.result, 'B04-SPIKE'); const csv = elnCsv(ex.recovery);
  assert.equal(parseCsv(csv).rows[0].length, 6); const low = r.built.records.find(x => x.sampleId === 'LCS-01' && x.analyte === 'Sulfamethoxazole');
  assert.equal(Number(parseCsv(csv).rows.find(x => x[2] === 'Sulfamethoxazole')[4]), low.area);      // 낮은 회수율의 원인이 된 면적 그대로
  assert.ok(!/회수율|recovery_pct|conc/i.test(csv.split('\n')[0]));
});
test('ELN 내보내기: 배치를 섞지 않는다', () => {
  const r = load('synthetic_all_batches.csv'); const a = elnExport(r.result, 'B02-OUTLIER'), b = elnExport(load('scenarios/S2_B02-OUTLIER.csv').result, 'B02-OUTLIER');
  assert.deepEqual(a.calibration.rows, b.calibration.rows); assert.deepEqual(a.recovery.rows, b.recovery.rows);
  assert.equal(elnExport(r.result, '없는 배치').calibration.rows.length, 1);
});
test('ELN 내보내기: 내부표준 면적이 없으면 옮기지 않는다(본편 계약의 필수 열)', () => {
  const r = run(batch({ is: '' }), { method: 'external' }); const ex = elnExport(r.result, 'B1');
  assert.equal(ex.calibration.rows.length, 1); assert.equal(ex.calibration.skipped.length, 8); assert.match(ex.calibration.skipped[0].reason, /내부표준 면적/); assert.ok(ex.notes.some(n => /외부표준법/.test(n)));
});
test('ELN 내보내기: 희석된 첨가 시료, 명목 농도 0인 표준은 옮기지 않는다', () => {
  const r = run(batch({ extra: [{ id: 'LCS-D', type: 'Spike', nominal: 500, area: 5000, dil: 10 }, { id: 'STD-0', type: 'Calibration Standard', nominal: 0, area: 2 }] })); const ex = elnExport(r.result, 'B1');
  assert.ok(ex.recovery.skipped.some(s => s.sampleId === 'LCS-D' && /희석배수 10/.test(s.reason))); assert.ok(ex.calibration.skipped.some(s => s.sampleId === 'STD-0'));
  assert.ok(!ex.calibration.rows.some(x => x[0] === 'STD-0'));
});
test('ELN 내보내기: 사용자가 제외한 검량점도 원본으로 옮기고 그 사실을 알린다', () => {
  const rows = batch({ std: { 50: { area: 5000 * 1.45 } } }); const row = run(rows).result.groups[0].cal.points.find(p => p.nominal === 50).row;
  const r = run(rows, { excluded: { 'B1||A': { [row]: '조제 오류' } } }); const ex = elnExport(r.result, 'B1');
  assert.ok(ex.calibration.rows.some(x => x[1] === 50 && Math.abs(x[3] - 7250) < 1e-6)); assert.ok(ex.notes.some(n => /제외한 검량점도 원본/.test(n) && /조제 오류/.test(n)));
});
test('ELN 내보내기는 분석 결과를 바꾸지 않고, CSV는 다시 읽으면 같은 값', () => {
  const r = load('scenarios/S0_B00-NORMAL.csv'); const before = JSON.stringify(r.result); const ex = elnExport(r.result, 'B00-NORMAL'); assert.equal(JSON.stringify(r.result), before);
  const back = parseCsv(elnCsv(ex.calibration)).rows; assert.equal(back.length, ex.calibration.rows.length); assert.deepEqual(back[1].map(String), ex.calibration.rows[1].map(String));
});
test('빌드: 커밋된 dist/index.html이 현재 소스로 만든 결과와 같다 (다르면 node scripts/build.mjs 실행)', () => {
  const committed = readFileSync(join(root, 'dist', 'index.html'), 'utf8'); const { full, artifact } = buildPages();
  assert.equal(committed, full); assert.ok(!artifact.includes('</body>') && !/<html/i.test(artifact), '게시용 조각에는 문서 뼈대 태그가 없어야 한다');
  assert.ok(full.includes('BioPilot 본편(ELN)으로 보내기'));
});
