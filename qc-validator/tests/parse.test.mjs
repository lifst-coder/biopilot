// 파일 파싱·결측치 처리 시험
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCsv, decodeText, readTableFile, readXlsx, toTable, autoMap, parseNumber, buildRecords, classifyType, toCsv } from '../src/parse.js';
import { runRows } from '../src/pipeline.js';

const data = join(dirname(fileURLToPath(import.meta.url)), '..', 'data'); const f = p => readFileSync(join(data, p));
const tableOf = async p => { const r = await readTableFile(p, f(p)); return { file: r, table: toTable(r.sheets[0]) }; };
const analyzeFile = async p => { const r = await readTableFile(p, f(p)); return runRows(r.sheets[0].rows); };

test('CSV: 따옴표, 셀 안의 쉼표·줄바꿈·이스케이프 따옴표', () => {
  const r = parseCsv('a,b,c\r\n"x, y","line1\nline2","he said ""hi"""\r\n1,2,3\r\n');
  assert.deepEqual(r.rows, [['a', 'b', 'c'], ['x, y', 'line1\nline2', 'he said "hi"'], ['1', '2', '3']]);
});
test('CSV: 구분자 자동 판별(쉼표·세미콜론·탭)과 빈 줄 제거', () => {
  assert.equal(parseCsv('a;b;c\n1;2;3\n\n').rows.length, 2); assert.deepEqual(parseCsv('a\tb\n1\t2').rows[1], ['1', '2']); assert.equal(parseCsv('a\tb\n1\t2').delimiter, '탭');
});
test('CSV: BOM 제거, 마지막 줄바꿈 없음, 앞뒤 공백 제거', () => {
  assert.deepEqual(parseCsv('﻿a, b \n 1 ,2').rows, [['a', 'b'], ['1', '2']]);
});
test('CSV: 빈 파일과 닫히지 않은 따옴표는 오류', () => {
  assert.throws(() => parseCsv(''), /비어/); assert.throws(() => parseCsv('   \n  '), /비어/); assert.throws(() => parseCsv('a,b\n"x,1'), /따옴표/);
});
test('인코딩: UTF-8, UTF-8 BOM, CP949(한국어 Excel 기본), UTF-16LE', () => {
  assert.equal(decodeText(f('test_inputs/korean_headers_utf8.csv')).encoding, 'UTF-8');
  const cp = decodeText(f('test_inputs/korean_headers_cp949.csv')); assert.match(cp.encoding, /CP949/); assert.ok(cp.text.startsWith('배치,시료명'));
  const u16 = new Uint8Array([0xFF, 0xFE, 0x41, 0x00, 0x2C, 0x00, 0x42, 0x00]); assert.equal(decodeText(u16).text, 'A,B');
});
test('파일 형식: 세미콜론·탭·BOM 파일도 같은 분석 결과', async () => {
  const base = await analyzeFile('scenarios/S0_B00-NORMAL.csv');
  for (const p of ['test_inputs/semicolon_delimited.csv', 'test_inputs/tab_delimited.tsv', 'test_inputs/utf8_bom_quoted.csv']) {
    const r = await analyzeFile(p); assert.equal(r.built.records.length, base.built.records.length, p);
    assert.deepEqual(r.result.groups.map(g => g.cal.fit.slope), base.result.groups.map(g => g.cal.fit.slope), p);
  }
});
test('XLSX: openpyxl이 만든 파일(압축, 공유 문자열, 여러 시트)을 읽고 CSV와 같은 결과', async () => {
  const x = await readTableFile('synthetic_all_batches.xlsx', f('synthetic_all_batches.xlsx'));
  assert.equal(x.format, 'XLSX'); assert.deepEqual(x.sheets.map(s => s.name), ['LCMS Results', 'Notes']); assert.equal(x.sheets[1].rows[0][0], '이 시트는 메모입니다');
  const a = runRows(x.sheets[0].rows), b = await analyzeFile('synthetic_all_batches.csv');
  assert.equal(a.built.records.length, b.built.records.length);
  assert.deepEqual(a.result.findings.map(v => v.id + v.observed), b.result.findings.map(v => v.id + v.observed));
});
test('XLSX: Microsoft Excel이 저장한 파일을 읽고 CSV와 같은 결과', async () => {
  const a = await analyzeFile('test_inputs/excel_saved_S2.xlsx'), b = await analyzeFile('scenarios/S2_B02-OUTLIER.csv');
  assert.deepEqual(a.result.groups.map(g => [g.analyte, g.cal.fit.slope, g.cal.fit.intercept]), b.result.groups.map(g => [g.analyte, g.cal.fit.slope, g.cal.fit.intercept]));
});
test('XLSX: 한글 머리글, 수식 셀(캐시 값 없음)은 빈 값으로', async () => {
  const { table } = await tableOf('test_inputs/korean_headers.xlsx'); assert.equal(table.headers[0], '배치'); assert.equal(table.headers[13], '면적비(수식)'); assert.equal(table.rows[0][13], '');
  const m = autoMap(table.headers).mapping; assert.equal(m.sampleId, 1); assert.equal(m.nominal, 5); assert.equal(m.isArea, 7); assert.equal(m.parentId, 12);
});
test('지원하지 않는 형식은 오류를 내고 내용을 추측하지 않는다', async () => {
  await assert.rejects(readTableFile('legacy_format.xls', f('test_inputs/legacy_format.xls')), /지원하지 않는 형식.*\.xls/);
  await assert.rejects(readTableFile('data.json', f('test_inputs/unsupported.json')), /지원하지 않는 형식/);
  await assert.rejects(readTableFile('renamed_text.xlsx', f('test_inputs/renamed_text.xlsx')), /XLSX 형식이 아닙니다/);
  await assert.rejects(readTableFile('x.xlsx', f('test_inputs/legacy_format.xls')), /구형 \.xls|암호/);
  await assert.rejects(readTableFile('x.csv', f('synthetic_all_batches.xlsx')), /Excel 통합 문서/);
  await assert.rejects(readTableFile('empty.csv', f('test_inputs/empty.csv')), /비어/);
  await assert.rejects(readTableFile('noext', new Uint8Array([1, 2, 3])), /지원하지 않는 형식/);
  await assert.rejects(readXlsx(new Uint8Array([0x50, 0x4B, 3, 4, 0, 0, 0, 0, 0, 0])), /ZIP|손상/);
});
test('머리글만 있는 파일, 표가 아닌 텍스트', async () => {
  const h = await readTableFile('header_only.csv', f('test_inputs/header_only.csv')); assert.throws(() => toTable(h.sheets[0]), /데이터 행이 없습니다/);
  const t = await readTableFile('not_a_table.txt', f('test_inputs/not_a_table.txt')); const r = runRows(t.sheets[0].rows);
  assert.equal(r.built.blocked, true); assert.equal(r.result, null); assert.ok(r.built.issues.filter(i => i.code === 'MISSING_COLUMN').length >= 5);
});
test('컬럼 매핑: 영문 표준 머리글, 장비 내보내기식 이름, 모호한 이름 표시', () => {
  const a = autoMap(['Sample Name', 'Sample Type', 'Component Name', 'Actual Concentration', 'Area', 'IS Area', 'RT', 'Dilution Factor', 'Batch', 'Calculated Concentration']);
  assert.deepEqual([a.mapping.sampleId, a.mapping.sampleType, a.mapping.analyte, a.mapping.nominal, a.mapping.area, a.mapping.isArea, a.mapping.rt, a.mapping.dilution, a.mapping.batchId], [0, 1, 2, 3, 4, 5, 6, 7, 8]);
  const b = autoMap(['ID', 'Type', 'Compound', 'Conc', 'Peak Area (counts)', 'ISTD_Area', 'Ret. Time']);
  assert.equal(b.mapping.area, 4); assert.equal(b.mapping.isArea, 5); assert.equal(b.mapping.nominal, 3); assert.equal(b.confidence.nominal, 'guess'); assert.equal(b.confidence.sampleId, 'guess'); assert.equal(b.confidence.area, 'exact');
  assert.equal(autoMap(['foo', 'bar']).mapping.area, -1);
});
test('필수 열이 없으면 분석을 막고 어떤 열인지 알려 준다', async () => {
  const r = await analyzeFile('test_inputs/missing_required_column.csv'); assert.equal(r.built.blocked, true); assert.equal(r.result, null);
  const miss = r.built.issues.filter(i => i.code === 'MISSING_COLUMN'); assert.equal(miss.length, 1); assert.equal(miss[0].field, 'area');
});
test('선택 열(내부표준·머무름 시간)이 없으면 해당 평가만 "평가 불가"로 두고 나머지는 계산', async () => {
  const r = await analyzeFile('test_inputs/no_is_no_rt_columns.csv'); assert.equal(r.built.blocked, false);
  assert.ok(r.built.issues.some(i => i.code === 'NO_ISAREA_COLUMN')); assert.ok(r.built.issues.some(i => i.code === 'NO_RT_COLUMN'));
  const g = r.result.groups[0]; assert.equal(g.method, 'external'); assert.equal(g.cal.ok, true);
  const ne = g.findings.filter(x => x.code === 'NOT_EVALUATED').map(x => x.details.what); assert.ok(ne.includes('내부표준 응답')); assert.ok(ne.includes('머무름 시간'));
});
test('숫자 해석: 숫자 형태만 받아들이고 나머지는 바꾸지 않는다', () => {
  assert.deepEqual(parseNumber('12.5'), { value: 12.5 }); assert.deepEqual(parseNumber(' 1e3 '), { value: 1000 }); assert.deepEqual(parseNumber(-3), { value: -3 }); assert.deepEqual(parseNumber('.5'), { value: 0.5 });
  assert.deepEqual(parseNumber(''), { missing: true }); assert.deepEqual(parseNumber(null), { missing: true }); assert.deepEqual(parseNumber('  '), { missing: true });
  for (const s of ['N/A', '<LOQ', '1,234', '12 ng', 'abc', '1.2.3', '--5', 'NaN', 'Infinity']) assert.equal(parseNumber(s).invalid, s, s);
  assert.ok(parseNumber(NaN).invalid); assert.ok(parseNumber(Infinity).invalid);
});
test('결측·비정상 값: 값을 채우지 않고 null로 두며 문제 목록에 행 번호를 남긴다', async () => {
  const r = await analyzeFile('test_inputs/bad_values.csv'); const codes = r.built.issues.map(i => i.code); const rec = row => r.built.allRecords.find(x => x.row === row);
  for (const c of ['NOT_NUMERIC', 'MISSING_AREA', 'NEGATIVE_AREA', 'NONPOSITIVE_IS', 'NEGATIVE_NOMINAL', 'NONPOSITIVE_DILUTION', 'MISSING_DILUTION', 'UNKNOWN_TYPE', 'MISSING_KEY']) assert.ok(codes.includes(c), c);
  assert.equal(rec(4).area, null); assert.equal(rec(6).area, null); assert.equal(rec(9).area, null); assert.equal(rec(12).area, null);        // 'N/A', '<LOQ', '1,234', ''
  assert.equal(rec(15).area, -500); assert.equal(rec(27).dilution, null); assert.equal(rec(36).rt, null);
  const nn = r.built.issues.find(i => i.code === 'NOT_NUMERIC' && i.field === 'area'); assert.deepEqual(nn.rows, [4, 6, 9]);
  assert.ok(!r.built.records.some(x => x.row === 30)); assert.ok(!r.built.records.some(x => x.row === 33));   // 모르는 유형, 시료 ID 없음 → 분석에서 제외
  assert.equal(r.result.groups.length, 3);   // 그래도 나머지는 분석된다
});
test('희석배수 누락: 기본은 최종 농도를 계산하지 않고, 사용자가 선택했을 때만 1로 계산', () => {
  const rows = [['Batch ID', 'Sample ID', 'Sample Type', 'Analyte', 'Nominal Concentration', 'Peak Area', 'Dilution Factor']];
  [1, 2, 5, 10, 50, 100].forEach((c, i) => rows.push(['B', 'STD' + i, 'Standard', 'A', c, c * 100, '']));
  rows.push(['B', 'S1', 'Sample', 'A', '', 2000, '']); rows.push(['B', 'S2', 'Sample', 'A', '', 2000, 4]);
  const off = runRows(rows), on = runRows(rows, { assumeDilutionOne: true });
  const q = (r, id) => r.result.groups[0].rows.find(x => x.rec.sampleId === id).q;
  assert.equal(q(off, 'S1').final, null); assert.ok(Math.abs(q(off, 'S1').conc - 20) < 1e-9); assert.ok(Math.abs(q(off, 'S2').final - 80) < 1e-9);
  assert.ok(Math.abs(q(on, 'S1').final - 20) < 1e-9); assert.ok(off.built.issues.some(i => i.code === 'MISSING_DILUTION'));
});
test('시료 유형: 동의어·한글·대소문자 인식, 모르는 값은 null, 사용자 지정이 우선', () => {
  assert.equal(classifyType('Calibration Standard'), 'STD'); assert.equal(classifyType('std'), 'STD'); assert.equal(classifyType('표준용액'), 'STD'); assert.equal(classifyType('QC'), 'QC');
  assert.equal(classifyType('Method_Blank'), 'METHOD_BLANK'); assert.equal(classifyType('방법바탕'), 'METHOD_BLANK'); assert.equal(classifyType('Blank'), 'CAL_BLANK'); assert.equal(classifyType('LCS'), 'SPIKE'); assert.equal(classifyType('Unknown'), 'SAMPLE');
  assert.equal(classifyType('Mystery'), null); assert.equal(classifyType(''), null); assert.equal(classifyType('Mystery', { Mystery: 'QC' }), 'QC'); assert.equal(classifyType('Blank', { Blank: 'METHOD_BLANK' }), 'METHOD_BLANK');
});
test('고정값: 분석물·배치 열이 없으면 사용자가 입력한 값을 쓴다(없으면 차단)', () => {
  const table = { headers: ['Sample ID', 'Sample Type', 'Nominal', 'Area'], rows: [['S1', 'Standard', 1, 100], ['S2', 'Standard', 2, 200]] }; const m = autoMap(table.headers).mapping;
  assert.equal(buildRecords(table, m, {}).blocked, true);
  const ok = buildRecords(table, m, { constants: { analyte: 'Caffeine', batchId: 'Run-7' } }); assert.equal(ok.blocked, false); assert.equal(ok.records[0].analyte, 'Caffeine'); assert.equal(ok.records[1].batchId, 'Run-7');
});
test('CSV 내보내기는 다시 읽으면 같은 값', () => {
  const rows = [['a', 'b'], ['x,y', 'q"r'], ['줄\n바꿈', 3]]; assert.deepEqual(parseCsv(toCsv(rows)).rows, [['a', 'b'], ['x,y', 'q"r'], ['줄\n바꿈', '3']]);
});
