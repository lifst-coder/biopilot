// BIOPILOT — 파일 읽기(CSV·XLSX), 컬럼 매핑, 레코드 검증. 값을 임의로 채우지 않는다: 읽을 수 없는 값은 null로 두고 문제 목록에 남긴다.
import { isNum } from './stats.js';

// ───────────── 필드 정의 ─────────────
// required: 분석에 반드시 필요한 열. constantOk: 열이 없으면 사용자가 고정값을 직접 입력할 수 있음.
export const FIELDS = [
  { key: 'sampleId', label: 'Sample ID', ko: '시료 ID', required: true, syn: ['sample id', 'sampleid', 'sample name', 'samplename', 'sample', 'name', 'id', '시료 id', '시료id', '시료명', '시료', '시료 이름'] },
  { key: 'sampleType', label: 'Sample Type', ko: '시료 유형', required: true, syn: ['sample type', 'sampletype', 'type', '시료 유형', '시료유형', '유형', '종류', '시료 종류'] },
  { key: 'analyte', label: 'Analyte', ko: '분석물', required: true, constantOk: true, syn: ['analyte', 'analyte name', 'compound', 'compound name', 'component', 'component name', 'target', '분석물', '분석 항목', '분석항목', '성분', '항목', '물질'] },
  { key: 'level', label: 'Concentration Level', ko: '농도 수준', required: false, syn: ['concentration level', 'conc level', 'level', 'cal level', 'std level', '농도 수준', '농도수준', '수준', '레벨'] },
  { key: 'nominal', label: 'Nominal Concentration', ko: '명목 농도', required: true, syn: ['nominal concentration', 'nominal conc', 'nominal', 'actual concentration', 'expected concentration', 'expected conc', 'theoretical concentration', 'theoretical conc', 'target concentration', 'spiked concentration', 'std conc', 'standard concentration', 'concentration', 'conc', '명목 농도', '명목농도', '표준 농도', '표준농도', '이론 농도', '이론농도', '첨가 농도', '농도'] },
  { key: 'area', label: 'Peak Area', ko: '피크 면적', required: true, syn: ['peak area', 'peakarea', 'area', 'analyte area', 'analyte peak area', 'response', '피크 면적', '피크면적', '면적', '분석물 면적'] },
  { key: 'isArea', label: 'Internal Standard Area', ko: '내부표준 면적', required: false, syn: ['internal standard area', 'internal standard peak area', 'is area', 'isarea', 'istd area', 'is peak area', 'istd peak area', 'is response', 'istd response', '내부표준 면적', '내부표준면적', '내부표준물질 면적', 'is 면적', 'istd 면적'] },
  { key: 'rt', label: 'Retention Time', ko: '머무름 시간', required: false, syn: ['retention time', 'retentiontime', 'rt', 'ret time', 'analyte retention time', 'rt min', '머무름 시간', '머무름시간', '유지 시간', '유지시간'] },
  { key: 'dilution', label: 'Dilution Factor', ko: '희석배수', required: false, syn: ['dilution factor', 'dilutionfactor', 'dilution', 'df', 'dil factor', '희석배수', '희석 배수', '희석'] },
  { key: 'replicate', label: 'Replicate', ko: '반복', required: false, syn: ['replicate', 'rep', 'replicate number', 'replicate no', 'injection', 'inj', '반복', '반복 번호', '반복수'] },
  { key: 'batchId', label: 'Batch ID', ko: '배치 ID', required: true, constantOk: true, syn: ['batch id', 'batchid', 'batch', 'run id', 'run', 'sequence', 'sequence id', 'batch name', '배치 id', '배치id', '배치', '시퀀스'] },
  { key: 'injectionOrder', label: 'Injection Order', ko: '주입 순서', required: false, extra: true, syn: ['injection order', 'inj order', 'acquisition order', 'order', 'index', 'run order', 'injection number', '주입 순서', '주입순서', '순서'] },
  { key: 'parentId', label: 'Parent Sample ID', ko: '원시료 ID', required: false, extra: true, syn: ['parent sample id', 'parent sample', 'parent id', 'parent', 'source sample', '원시료 id', '원시료', '모시료'] },
];
export const FIELD = {}; for (const f of FIELDS) FIELD[f.key] = f;
const NUMERIC = ['nominal', 'area', 'isArea', 'rt', 'dilution', 'injectionOrder'];

// ───────────── 시료 유형 ─────────────
export const TYPES = {
  STD: '검량 표준', CAL_BLANK: '검량 바탕', METHOD_BLANK: '방법 바탕', QC: 'QC 시료', SPIKE: '첨가 시료', DUP: '중복 시료', SAMPLE: '미지 시료',
};
const TYPE_SYN = {
  STD: ['calibration standard', 'cal standard', 'calibration', 'calibrator', 'standard', 'std', 'cal', 'cal std', '검량 표준', '검량표준', '표준용액', '표준 용액', '표준', '검량'],
  CAL_BLANK: ['calibration blank', 'cal blank', 'solvent blank', 'reagent blank', 'instrument blank', 'zero', 'zero sample', 'blank', 'double blank', '검량 바탕', '검량바탕', '용매 바탕', '용매바탕', '바탕'],
  METHOD_BLANK: ['method blank', 'mb', 'procedural blank', 'preparation blank', 'prep blank', 'matrix blank', 'lab blank', 'laboratory reagent blank', 'lrb', '방법 바탕', '방법바탕', '방법바탕시료', '바탕시료', '전처리 바탕'],
  QC: ['qc', 'qc sample', 'quality control', 'quality control sample', 'ccv', 'continuing calibration verification', 'icv', '정도관리', '정도관리 시료', 'qc 시료'],
  SPIKE: ['spike', 'spiked sample', 'spike recovery', 'matrix spike', 'ms', 'lcs', 'laboratory control sample', 'lfb', 'laboratory fortified blank', 'lfm', 'blank spike', 'fortified', '첨가', '첨가 시료', '첨가시료', '회수율', '매질첨가', '매질 첨가'],
  DUP: ['duplicate', 'dup', 'sample duplicate', 'lab duplicate', 'msd', 'matrix spike duplicate', '중복', '중복 시료', '중복시료', '이중'],
  SAMPLE: ['sample', 'unknown', 'unk', 'test sample', 'study sample', 'analyte', '시료', '미지', '미지 시료', '미지시료', '분석 시료'],
};
const norm = s => String(s == null ? '' : s).normalize('NFKC').toLowerCase().replace(/\([^)]*\)/g, ' ').replace(/[_\-./#:]+/g, ' ').replace(/\s+/g, ' ').trim();
const TYPE_LOOKUP = {}; for (const k of Object.keys(TYPE_SYN)) for (const s of TYPE_SYN[k]) TYPE_LOOKUP[norm(s)] = k;
export function classifyType(raw, typeMap) {
  const key = String(raw == null ? '' : raw).trim();
  if (typeMap && Object.prototype.hasOwnProperty.call(typeMap, key)) return typeMap[key] || null;
  return TYPE_LOOKUP[norm(key)] || null;
}

// ───────────── 텍스트 해석 ─────────────
export function decodeText(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length >= 2 && b[0] === 0xFF && b[1] === 0xFE) return { text: new TextDecoder('utf-16le').decode(b.subarray(2)), encoding: 'UTF-16LE' };
  if (b.length >= 2 && b[0] === 0xFE && b[1] === 0xFF) return { text: new TextDecoder('utf-16be').decode(b.subarray(2)), encoding: 'UTF-16BE' };
  try { return { text: new TextDecoder('utf-8', { fatal: true }).decode(b).replace(/^﻿/, ''), encoding: 'UTF-8' }; }
  catch (e) { /* UTF-8이 아니면 한국어 Excel의 기본 CSV 인코딩으로 다시 시도 */ }
  try { return { text: new TextDecoder('euc-kr', { fatal: true }).decode(b), encoding: 'EUC-KR (CP949)' }; }
  catch (e) { throw new Error('파일의 문자 인코딩을 해석할 수 없습니다. UTF-8 CSV로 다시 저장해 주세요.'); }
}

// RFC 4180 방식 CSV. 구분자는 첫 줄에서 쉼표·세미콜론·탭 중 가장 많은 것으로 정한다.
export function parseCsv(text) {
  if (typeof text !== 'string') throw new Error('CSV 내용이 문자열이 아닙니다.');
  const src = text.replace(/^﻿/, '');
  if (!src.trim()) throw new Error('파일이 비어 있습니다.');
  let firstLine = '', inQ = false;
  for (let i = 0; i < src.length; i++) { const c = src[i]; if (c === '"') inQ = !inQ; if ((c === '\n' || c === '\r') && !inQ) break; firstLine += c; }
  const count = d => { let n = 0, q = false; for (const c of firstLine) { if (c === '"') q = !q; else if (c === d && !q) n++; } return n; };
  const cands = [',', ';', '\t']; let delim = ','; let best = -1;
  for (const d of cands) { const n = count(d); if (n > best) { best = n; delim = d; } }
  const rows = []; let row = [], cell = '', q = false, i = 0, quoted = false;
  const pushCell = () => { row.push(quoted ? cell : cell.trim()); cell = ''; quoted = false; };
  while (i < src.length) {
    const c = src[i];
    if (q) {
      if (c === '"') { if (src[i + 1] === '"') { cell += '"'; i += 2; continue; } q = false; i++; continue; }
      cell += c; i++; continue;
    }
    if (c === '"' && cell.trim() === '') { q = true; quoted = true; cell = ''; i++; continue; }
    if (c === delim) { pushCell(); i++; continue; }
    if (c === '\r' || c === '\n') { pushCell(); rows.push(row); row = []; if (c === '\r' && src[i + 1] === '\n') i++; i++; continue; }
    cell += c; i++;
  }
  if (q) throw new Error('CSV의 따옴표가 닫히지 않았습니다.');
  if (cell !== '' || row.length) { pushCell(); rows.push(row); }
  return { rows: rows.filter(r => r.some(v => v !== '')), delimiter: delim === '\t' ? '탭' : delim };
}

// ───────────── XLSX (의존성 없는 최소 판독기) ─────────────
const u16 = (b, o) => b[o] | (b[o + 1] << 8);
const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
async function inflateRaw(data) {
  if (typeof DecompressionStream === 'undefined') throw new Error('이 브라우저는 XLSX 압축 해제를 지원하지 않습니다. 최신 브라우저를 쓰거나 CSV로 저장해 주세요.');
  const ds = new DecompressionStream('deflate-raw');
  const writer = ds.writable.getWriter(); writer.write(data).catch(() => {}); writer.close().catch(() => {});
  const reader = ds.readable.getReader(); const chunks = []; let total = 0;
  for (;;) { const r = await reader.read(); if (r.done) break; chunks.push(r.value); total += r.value.length; }
  const out = new Uint8Array(total); let p = 0; for (const c of chunks) { out.set(c, p); p += c.length; }
  return out;
}
async function unzip(bytes) {
  const b = bytes; let eocd = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 65557); i--) if (u32(b, i) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('XLSX 파일 구조를 읽을 수 없습니다(ZIP 끝 레코드 없음). 파일이 손상되었을 수 있습니다.');
  const count = u16(b, eocd + 10); let p = u32(b, eocd + 16); const entries = {};
  for (let n = 0; n < count; n++) {
    if (u32(b, p) !== 0x02014b50) throw new Error('XLSX 파일 구조가 손상되었습니다(중앙 디렉터리).');
    const flags = u16(b, p + 8), method = u16(b, p + 10), csize = u32(b, p + 20), nlen = u16(b, p + 28), elen = u16(b, p + 30), clen = u16(b, p + 32), off = u32(b, p + 42);
    const name = new TextDecoder('utf-8').decode(b.subarray(p + 46, p + 46 + nlen));
    entries[name] = { flags, method, csize, off };
    p += 46 + nlen + elen + clen;
  }
  return {
    names: Object.keys(entries),
    async read(name) {
      const e = entries[name]; if (!e) return null;
      if (e.flags & 1) throw new Error('암호로 보호된 XLSX는 열 수 없습니다. 암호를 해제한 뒤 다시 올려 주세요.');
      if (u32(b, e.off) !== 0x04034b50) throw new Error('XLSX 파일 구조가 손상되었습니다(로컬 헤더).');
      const start = e.off + 30 + u16(b, e.off + 26) + u16(b, e.off + 28); const data = b.subarray(start, start + e.csize);
      if (e.method === 0) return data;
      if (e.method === 8) return inflateRaw(data);
      throw new Error('지원하지 않는 압축 방식입니다(' + e.method + ').');
    },
  };
}
const xmlDecode = s => s.replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16))).replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');
const attr = (tag, name) => { const m = new RegExp('(?:^|\\s)' + name + '="([^"]*)"').exec(tag); return m ? xmlDecode(m[1]) : null; };
function textRuns(xml) {   // <t>…</t>를 이어 붙인다. 후리가나(<rPh>)는 제외.
  const clean = xml.replace(/<rPh[\s\S]*?<\/rPh>/g, ''); let out = ''; const re = /<t(?:\s[^>]*)?>([\s\S]*?)<\/t>|<t(?:\s[^>]*)?\/>/g; let m;
  while ((m = re.exec(clean))) out += m[1] ? xmlDecode(m[1]) : '';
  return out;
}
function colIndex(ref) { let n = 0; for (const ch of ref) { const c = ch.charCodeAt(0); if (c >= 65 && c <= 90) n = n * 26 + (c - 64); else break; } return n - 1; }
// XLSX → { sheets: [{ name, rows }] }. 셀 값은 숫자 또는 문자열, 빈 셀은 ''.
export async function readXlsx(input) {
  const b = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (b.length >= 8 && b[0] === 0xD0 && b[1] === 0xCF && b[2] === 0x11 && b[3] === 0xE0) throw new Error('구형 .xls 형식이거나 암호로 보호된 파일입니다. Excel에서 .xlsx 또는 CSV로 다시 저장해 주세요.');
  if (!(b.length >= 4 && b[0] === 0x50 && b[1] === 0x4B)) throw new Error('XLSX 형식이 아닙니다. 확장자와 실제 내용이 다릅니다.');
  const zip = await unzip(b); const dec = new TextDecoder('utf-8');
  const text = async name => { const d = await zip.read(name); return d ? dec.decode(d) : null; };
  const wb = await text('xl/workbook.xml'); if (!wb) throw new Error('XLSX 안에 통합 문서 정보(xl/workbook.xml)가 없습니다.');
  const rels = (await text('xl/_rels/workbook.xml.rels')) || ''; const relMap = {};
  for (const m of rels.match(/<Relationship\s[^>]*>/g) || []) relMap[attr(m, 'Id')] = attr(m, 'Target');
  const ssXml = await text('xl/sharedStrings.xml'); const shared = [];
  if (ssXml) for (const m of ssXml.match(/<si>[\s\S]*?<\/si>|<si\/>/g) || []) shared.push(textRuns(m));
  const sheets = [];
  for (const tag of wb.match(/<sheet\s[^>]*>/g) || []) {
    const name = attr(tag, 'name'); const rid = attr(tag, 'r:id'); let target = relMap[rid]; if (!target) continue;
    target = target.replace(/^\/+/, ''); if (!target.startsWith('xl/')) target = 'xl/' + target;
    const xml = await text(target); if (xml == null) continue;
    const rows = []; const rowRe = /<row(\s[^>]*)?>([\s\S]*?)<\/row>/g; let rm;
    while ((rm = rowRe.exec(xml))) {
      const row = []; let seq = 0; const cellRe = /<c(\s[^>]*?)?(?:\/>|>([\s\S]*?)<\/c>)/g; let cm;
      while ((cm = cellRe.exec(rm[2]))) {
        const at = cm[1] || ''; const ref = attr(at, 'r'); const idx = ref ? colIndex(ref) : seq; seq = idx + 1;
        const t = attr(at, 't'); const inner = cm[2] || ''; const vm = /<v>([\s\S]*?)<\/v>/.exec(inner); let val = '';
        if (t === 's') val = vm ? (shared[Number(vm[1])] ?? '') : '';
        else if (t === 'inlineStr') val = textRuns(inner);
        else if (t === 'str' || t === 'e') val = vm ? xmlDecode(vm[1]) : '';
        else if (t === 'b') val = vm ? (vm[1] === '1' ? 'TRUE' : 'FALSE') : '';
        else if (vm) { const n = Number(vm[1]); val = Number.isFinite(n) ? n : xmlDecode(vm[1]); }
        while (row.length < idx) row.push('');
        row[idx] = typeof val === 'string' ? val.trim() : val;
      }
      rows.push(row);
    }
    sheets.push({ name, rows: rows.filter(r => r.some(v => v !== '' && v != null)) });
  }
  if (!sheets.length) throw new Error('XLSX에서 읽을 수 있는 시트를 찾지 못했습니다.');
  return { sheets };
}

// 파일 이름과 내용으로 형식을 판별해 표로 읽는다. 지원: .csv, .tsv, .txt(구분자 텍스트), .xlsx
export async function readTableFile(name, input) {
  const b = input instanceof Uint8Array ? input : new Uint8Array(input);
  const ext = (/\.([A-Za-z0-9]+)$/.exec(name || '') || [, ''])[1].toLowerCase();
  if (!b.length) throw new Error('파일이 비어 있습니다.');
  const isZip = b.length >= 4 && b[0] === 0x50 && b[1] === 0x4B, isOle = b.length >= 4 && b[0] === 0xD0 && b[1] === 0xCF;
  if (ext === 'xlsx') { const wb = await readXlsx(b); return { format: 'XLSX', sheets: wb.sheets }; }
  if (ext === 'csv' || ext === 'tsv' || ext === 'txt') {
    if (isZip || isOle) throw new Error('확장자는 .' + ext + '이지만 내용은 Excel 통합 문서입니다. 확장자를 .xlsx로 바꾸거나 CSV로 다시 저장해 주세요.');
    const d = decodeText(b); const p = parseCsv(d.text);
    return { format: 'CSV', encoding: d.encoding, delimiter: p.delimiter, sheets: [{ name: name || 'CSV', rows: p.rows }] };
  }
  throw new Error('지원하지 않는 형식입니다(.' + (ext || '확장자 없음') + '). CSV 또는 XLSX 파일을 올려 주세요.' + (ext === 'xls' ? ' 구형 .xls는 Excel에서 .xlsx로 다시 저장하면 됩니다.' : ''));
}

// 시트의 첫 행을 머리글로 본다.
export function toTable(sheet) {
  const rows = sheet.rows; if (!rows.length) throw new Error('시트에 데이터가 없습니다.');
  const width = Math.max.apply(null, rows.map(r => r.length));
  const seen = {}; const headers = [];
  for (let i = 0; i < width; i++) { let h = String(rows[0][i] == null ? '' : rows[0][i]).trim(); if (!h) h = '(열 ' + (i + 1) + ')'; if (seen[h]) { seen[h]++; h = h + ' [' + seen[h.replace(/ \[\d+\]$/, '')] + ']'; } else seen[h] = 1; headers.push(h); }
  const body = rows.slice(1).map(r => { const o = []; for (let i = 0; i < width; i++) o.push(r[i] == null ? '' : r[i]); return o; });
  if (!body.length) throw new Error('머리글만 있고 데이터 행이 없습니다.');
  return { headers, rows: body };
}

// 머리글 이름으로 필드를 자동 추정한다. 결과는 { field: 열 번호 | -1 }, confidence는 'exact'|'guess'.
export function autoMap(headers) {
  const mapping = {}, confidence = {}; const used = new Set(); const hn = headers.map(norm);
  for (const f of FIELDS) {
    mapping[f.key] = -1;
    for (const s of f.syn) { const i = hn.findIndex((h, k) => !used.has(k) && h === norm(s)); if (i >= 0) { mapping[f.key] = i; confidence[f.key] = (s === 'concentration' || s === 'conc' || s === '농도' || s === 'name' || s === 'id' || s === 'type' || s === 'order' || s === 'index' || s === 'response' || s === 'sample') ? 'guess' : 'exact'; used.add(i); break; } }
  }
  return { mapping, confidence };
}

// 숫자 해석: 숫자 또는 숫자 형태 문자열만 받는다. '<LOQ', 'N/A', '1,234' 같은 값은 숫자로 바꾸지 않는다.
const NUM_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
export function parseNumber(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? { value: v } : { invalid: String(v) };
  const s = String(v == null ? '' : v).trim(); if (s === '') return { missing: true };
  return NUM_RE.test(s) ? { value: Number(s) } : { invalid: s };
}

// 표 + 매핑 → 레코드. options: { constants: {analyte, batchId}, typeMap: {원래 값: 유형키}, assumeDilutionOne: bool }
export function buildRecords(table, mapping, options) {
  const opt = options || {}; const constants = opt.constants || {}; const issues = []; const records = [];
  const addIssue = (severity, code, message, extra) => issues.push(Object.assign({ severity, code, message }, extra || {}));
  for (const f of FIELDS) {
    const mapped = mapping[f.key] >= 0; const hasConst = f.constantOk && String(constants[f.key] || '').trim() !== '';
    if (f.required && !mapped && !hasConst) addIssue('error', 'MISSING_COLUMN', '필수 항목 "' + f.label + ' (' + f.ko + ')"에 해당하는 열이 없습니다.' + (f.constantOk ? ' 파일 전체가 한 값이면 고정값을 입력할 수 있습니다.' : ''), { field: f.key, blocking: true });
  }
  if (issues.some(i => i.blocking)) return { records: [], issues, blocked: true, stats: { rows: table.rows.length } };

  const cellStats = {}; for (const f of FIELDS) cellStats[f.key] = { missing: [], invalid: [] };
  const unknownTypes = {};
  table.rows.forEach((r, ri) => {
    const rowNo = ri + 2;   // 머리글이 1행
    const get = key => { const i = mapping[key]; return i >= 0 ? r[i] : undefined; };
    const str = key => { const v = get(key); const s = String(v == null ? '' : v).trim(); return s === '' ? null : s; };
    const rec = { row: rowNo, order: ri };
    rec.sampleId = str('sampleId');
    rec.sampleTypeRaw = str('sampleType');
    rec.analyte = mapping.analyte >= 0 ? str('analyte') : String(constants.analyte).trim();
    rec.batchId = mapping.batchId >= 0 ? str('batchId') : String(constants.batchId).trim();
    rec.level = str('level'); rec.replicate = str('replicate'); rec.parentId = str('parentId');
    for (const k of NUMERIC) {
      if (mapping[k] < 0) { rec[k] = null; continue; }
      const p = parseNumber(get(k));
      if (p.missing) { rec[k] = null; cellStats[k].missing.push(rowNo); }
      else if (p.invalid !== undefined) { rec[k] = null; cellStats[k].invalid.push({ row: rowNo, raw: p.invalid }); }
      else rec[k] = p.value;
    }
    for (const k of ['sampleId', 'sampleTypeRaw', 'analyte', 'batchId']) if (rec[k] == null || rec[k] === '') cellStats[k === 'sampleTypeRaw' ? 'sampleType' : k].missing.push(rowNo);
    rec.type = rec.sampleTypeRaw ? classifyType(rec.sampleTypeRaw, opt.typeMap) : null;
    if (rec.sampleTypeRaw && !rec.type) { (unknownTypes[rec.sampleTypeRaw] = unknownTypes[rec.sampleTypeRaw] || []).push(rowNo); }
    if (isNum(rec.injectionOrder)) rec.order = rec.injectionOrder;
    records.push(rec);
  });

  // 값 수준의 문제 정리
  for (const k of ['sampleId', 'sampleType', 'analyte', 'batchId']) if (cellStats[k].missing.length) addIssue('error', 'MISSING_KEY', FIELD[k].ko + ' 값이 비어 있는 행 ' + cellStats[k].missing.length + '개는 분석에서 제외됩니다.', { field: k, rows: cellStats[k].missing });
  for (const raw of Object.keys(unknownTypes)) addIssue('error', 'UNKNOWN_TYPE', '시료 유형 "' + raw + '"을(를) 인식하지 못했습니다(' + unknownTypes[raw].length + '행). 아래에서 유형을 지정하지 않으면 분석에서 제외됩니다.', { field: 'sampleType', rows: unknownTypes[raw], raw });
  for (const k of NUMERIC) {
    if (cellStats[k].invalid.length) addIssue('error', 'NOT_NUMERIC', FIELD[k].ko + '에 숫자가 아닌 값 ' + cellStats[k].invalid.length + '개: ' + cellStats[k].invalid.slice(0, 5).map(x => x.row + '행 "' + x.raw + '"').join(', ') + (cellStats[k].invalid.length > 5 ? ' 외' : '') + '. 값을 바꾸지 않고 해당 계산에서 제외합니다.', { field: k, rows: cellStats[k].invalid.map(x => x.row) });
  }
  const needNominal = records.filter(r => (r.type === 'STD' || r.type === 'QC' || r.type === 'SPIKE') && r.nominal == null).map(r => r.row);
  if (needNominal.length) addIssue('error', 'MISSING_NOMINAL', '검량 표준·QC·첨가 시료인데 명목 농도가 없는 행 ' + needNominal.length + '개. 이 행은 해당 평가에서 제외됩니다.', { field: 'nominal', rows: needNominal });
  const noArea = records.filter(r => r.area == null && mapping.area >= 0).map(r => r.row);
  if (noArea.length) addIssue('error', 'MISSING_AREA', '피크 면적이 없는 행 ' + noArea.length + '개. 이 행은 정량할 수 없습니다.', { field: 'area', rows: noArea });
  const check = (pred, code, sev, msg, field) => { const rows = records.filter(pred).map(r => r.row); if (rows.length) addIssue(sev, code, msg.replace('{n}', rows.length), { field, rows }); };
  check(r => isNum(r.area) && r.area < 0, 'NEGATIVE_AREA', 'error', '피크 면적이 음수인 행 {n}개. 유효하지 않은 값으로 보고 계산에서 제외합니다.', 'area');
  check(r => isNum(r.isArea) && r.isArea <= 0, 'NONPOSITIVE_IS', 'error', '내부표준 면적이 0 이하인 행 {n}개. 내부표준법 응답비를 계산할 수 없습니다.', 'isArea');
  check(r => isNum(r.nominal) && r.nominal < 0, 'NEGATIVE_NOMINAL', 'error', '명목 농도가 음수인 행 {n}개. 유효하지 않은 값으로 보고 제외합니다.', 'nominal');
  check(r => isNum(r.dilution) && r.dilution <= 0, 'NONPOSITIVE_DILUTION', 'error', '희석배수가 0 이하인 행 {n}개. 최종 농도를 계산할 수 없습니다.', 'dilution');
  check(r => isNum(r.rt) && r.rt <= 0, 'NONPOSITIVE_RT', 'warn', '머무름 시간이 0 이하인 행 {n}개. 머무름 시간 평가에서 제외합니다.', 'rt');
  check(r => r.type === 'STD' && r.nominal === 0, 'ZERO_NOMINAL_STD', 'warn', '명목 농도가 0인 검량 표준 {n}개. 회귀에는 넣지 않습니다(바탕으로 평가하려면 시료 유형을 바탕으로 지정).', 'nominal');
  check(r => isNum(r.area) && r.area === 0 && r.type === 'STD' && r.nominal > 0, 'ZERO_AREA_STD', 'warn', '피크 면적이 0인 검량 표준 {n}개. 피크가 검출되지 않은 것으로 보입니다.', 'area');
  if (mapping.dilution < 0) addIssue(opt.assumeDilutionOne ? 'warn' : 'warn', 'NO_DILUTION_COLUMN', opt.assumeDilutionOne ? '희석배수 열이 없어 사용자가 선택한 대로 모든 시료를 희석배수 1로 계산합니다.' : '희석배수 열이 없습니다. 최종 농도는 계산하지 않고 장비 측정 농도만 표시합니다. 모두 1배라면 "희석배수 누락 시 1로 간주"를 켜 주세요.', { field: 'dilution' });
  else if (cellStats.dilution.missing.length) addIssue('warn', 'MISSING_DILUTION', '희석배수가 비어 있는 행 ' + cellStats.dilution.missing.length + '개. ' + (opt.assumeDilutionOne ? '사용자 선택에 따라 1로 계산합니다.' : '해당 행의 최종 농도는 계산하지 않습니다.'), { field: 'dilution', rows: cellStats.dilution.missing });
  for (const k of ['isArea', 'rt']) {
    if (mapping[k] < 0) addIssue('warn', 'NO_' + k.toUpperCase() + '_COLUMN', FIELD[k].ko + ' 열이 없습니다. ' + (k === 'isArea' ? '내부표준법과 내부표준 응답 평가는 수행할 수 없습니다.' : '머무름 시간 평가는 수행할 수 없습니다.'), { field: k });
    else if (cellStats[k].missing.length) addIssue('warn', 'MISSING_' + k.toUpperCase(), FIELD[k].ko + '이(가) 비어 있는 행 ' + cellStats[k].missing.length + '개. 해당 평가에서 제외합니다.', { field: k, rows: cellStats[k].missing });
  }
  if (mapping.injectionOrder < 0) addIssue('info', 'ROW_ORDER_AS_INJECTION', '주입 순서 열이 없어 파일의 행 순서를 주입 순서로 봅니다. 표류와 직전 주입 판단은 이 가정에 의존합니다.', { field: 'injectionOrder' });

  const usable = records.filter(r => r.sampleId && r.type && r.analyte && r.batchId);
  for (const r of usable) { r.dilutionUsed = isNum(r.dilution) && r.dilution > 0 ? r.dilution : (opt.assumeDilutionOne && r.dilution == null ? 1 : null); }
  return { records: usable, allRecords: records, issues, blocked: false,
    stats: { rows: table.rows.length, usable: usable.length, excluded: records.length - usable.length, hasIs: mapping.isArea >= 0, hasRt: mapping.rt >= 0, hasDilution: mapping.dilution >= 0, hasOrder: mapping.injectionOrder >= 0,
      missing: Object.fromEntries(Object.keys(cellStats).map(k => [k, cellStats[k].missing.length])), invalid: Object.fromEntries(Object.keys(cellStats).map(k => [k, cellStats[k].invalid.length])) } };
}

// CSV 직렬화(내보내기용)
export function toCsv(rows) {
  const q = v => { const s = v == null ? '' : String(v); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  return rows.map(r => r.map(q).join(',')).join('\r\n') + '\r\n';
}
