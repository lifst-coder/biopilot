// BIOPILOT QC 검증 도구 — 명령줄에서 BioPilot 본편(ELN) 형식으로 내보내기.
//   node scripts/eln-export.mjs <입력.csv|.xlsx> [배치 ID] [출력 폴더]
// 출력: <배치>_calibration.csv, <배치>_recovery.csv (본편 계약 calibration@1, recovery@1)
//       <배치>_qc_reference.json (이 도구의 계산값. scripts/verify_eln_bridge.py가 본편 Python 계산과 대조하는 데 쓴다)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { basename, join } from 'node:path';
import { readTableFile } from '../src/parse.js';
import { runRows, defaultSettings } from '../src/pipeline.js';
import { elnExport, elnCsv } from '../src/eln.js';

const [input, batchArg, outArg] = process.argv.slice(2);
if (!input) { console.log('사용법: node scripts/eln-export.mjs <입력.csv|.xlsx> [배치 ID] [출력 폴더]'); process.exit(2); }
const file = await readTableFile(basename(input), new Uint8Array(readFileSync(input)));
const settings = defaultSettings(); settings.weighting = '1/x2';
const run = runRows(file.sheets[0].rows, { settings });
if (!run.result) { console.log('분석할 수 없습니다: ' + run.built.issues.filter(i => i.blocking).map(i => i.message).join(' ')); process.exit(1); }
const batch = batchArg || run.result.batches[0];
if (!run.result.batches.includes(batch)) { console.log('배치를 찾지 못했습니다: ' + batch + ' (있는 배치: ' + run.result.batches.join(', ') + ')'); process.exit(1); }
const out = outArg || '.'; mkdirSync(out, { recursive: true });
const ex = elnExport(run.result, batch); const safe = batch.replace(/[^A-Za-z0-9_-]+/g, '_');
writeFileSync(join(out, safe + '_calibration.csv'), elnCsv(ex.calibration).replace(/\r\n/g, '\n'));
writeFileSync(join(out, safe + '_recovery.csv'), elnCsv(ex.recovery).replace(/\r\n/g, '\n'));
const groups = run.result.groups.filter(g => g.batchId === batch);
const reference = { batch, weighting: '1/x2', method: 'internal',
  calibration: Object.fromEntries(groups.filter(g => g.cal.ok).map(g => [g.analyte, { slope: g.cal.fit.slope, intercept: g.cal.fit.intercept, r_squared: g.cal.fit.r2, n: g.cal.fit.n }])),
  recovery: groups.flatMap(g => (g.tables.spikes || []).filter(s => s.kind === 'blank' && s.pass !== undefined).map(s => ({ analyte: g.analyte, sample_id: s.sampleId, recovery_pct: s.recoveryPct }))) };
writeFileSync(join(out, safe + '_qc_reference.json'), JSON.stringify(reference, null, 1));
console.log(batch + ': calibration ' + (ex.calibration.rows.length - 1) + '행, recovery ' + (ex.recovery.rows.length - 1) + '행 → ' + out);
for (const [name, part] of [['calibration', ex.calibration], ['recovery', ex.recovery]]) if (part.skipped.length) console.log('  ' + name + ' 제외 ' + part.skipped.length + '행: ' + Array.from(new Set(part.skipped.map(s => s.reason))).join(' / '));
