// BIOPILOT — 테스트용 합성 데이터와 정답표 생성.  node scripts/gen-data.mjs
// XLSX와 CP949 파일은 scripts/gen-fixtures.py가 이 CSV에서 만든다(독립 구현으로 판독기를 시험하기 위해).
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generateDataset, SCENARIOS, HEADER, allScenarioIds } from '../src/synth.js';
import { toCsv } from '../src/parse.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..'); const SEED = 1;
const w = (p, s) => { mkdirSync(dirname(join(root, p)), { recursive: true }); writeFileSync(join(root, p), s); console.log(p); };

w('data/synthetic_all_batches.csv', toCsv(generateDataset(allScenarioIds(), SEED)));
for (const s of SCENARIOS) w('data/scenarios/' + s.id + '_' + s.batch + '.csv', toCsv(generateDataset([s.id], SEED)));
w('data/answer_key.json', JSON.stringify({ note: '합성 데이터 정답표. expected는 반드시 탐지해야 하는 (오류 코드, 분석물), expectedAny는 그중 하나 이상, allowed는 주입한 오류의 직접적 결과로 함께 나와도 되는 항목. rootCause는 합성 시 실제로 넣은 원인이며 도구는 이를 확정하지 않아야 한다(모든 진단의 원인 상태는 "원인 미확정").', seed: SEED, header: HEADER,
  scenarios: SCENARIOS.map(s => ({ id: s.id, batch: s.batch, name: s.name, file: 'scenarios/' + s.id + '_' + s.batch + '.csv', rootCause: s.rootCause, expected: s.expected, expectedAny: s.expectedAny || [], allowed: s.allowed, expectedCauseStatus: '원인 미확정' })) }, null, 1));

// ── 파일 판독·검증 시험용 입력 ──
const normal = generateDataset(['S0'], SEED);
w('data/test_inputs/semicolon_delimited.csv', normal.map(r => r.join(';')).join('\n') + '\n');
w('data/test_inputs/tab_delimited.tsv', normal.map(r => r.join('\t')).join('\r\n') + '\r\n');
w('data/test_inputs/utf8_bom_quoted.csv', '﻿' + normal.map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\r\n') + '\r\n');
const ko = ['배치', '시료명', '시료 유형', '분석물', '농도 수준', '표준 농도', '피크 면적', '내부표준 면적', '머무름 시간', '희석배수', '반복', '주입 순서', '원시료'];
const koType = { 'Calibration Blank': '검량 바탕', 'Calibration Standard': '표준용액', 'Method Blank': '방법바탕', 'QC': '정도관리', 'Spike': '첨가 시료', 'Sample': '시료', 'Duplicate': '중복 시료' };
w('data/test_inputs/korean_headers_utf8.csv', toCsv([ko].concat(normal.slice(1).map(r => { const c = r.slice(); c[2] = koType[c[2]]; return c; }))));
w('data/test_inputs/missing_required_column.csv', toCsv(normal.map(r => r.filter((_, i) => i !== 6))));           // Peak Area 열 없음
w('data/test_inputs/no_is_no_rt_columns.csv', toCsv(normal.map(r => r.filter((_, i) => i !== 7 && i !== 8))));
const bad = normal.map(r => r.slice());
bad[3][6] = 'N/A'; bad[5][6] = '<LOQ'; bad[8][6] = '1,234'; bad[11][6] = ''; bad[14][6] = -500; bad[17][7] = 0; bad[20][5] = -10; bad[23][9] = 0; bad[26][9] = ''; bad[29][2] = 'Mystery'; bad[32][1] = ''; bad[35][8] = 'abc';
w('data/test_inputs/bad_values.csv', toCsv(bad));
w('data/test_inputs/empty.csv', '');
w('data/test_inputs/header_only.csv', HEADER.join(',') + '\n');
w('data/test_inputs/not_a_table.txt', '이 파일은 표가 아닙니다.\n그냥 메모입니다.\n');
writeFileSync(join(root, 'data/test_inputs/legacy_format.xls'), Buffer.from([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1, 0, 0, 0, 0, 0, 0, 0, 0])); console.log('data/test_inputs/legacy_format.xls');
writeFileSync(join(root, 'data/test_inputs/renamed_text.xlsx'), 'Batch ID,Sample ID\nB1,S1\n'); console.log('data/test_inputs/renamed_text.xlsx');
w('data/test_inputs/unsupported.json', '{"rows": []}');
