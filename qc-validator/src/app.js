// BIOPILOT — 화면 로직. 화면의 모든 수치는 엔진(analyze) 결과에서 읽는다. 이 파일은 계산하지 않는다.
import { isNum } from './stats.js';
import { FIELDS, TYPES, readTableFile, toTable, autoMap, buildRecords } from './parse.js';
import { RULE_META, PROFILES, defaultRules, profileRules, getRule, setRule } from './rules.js';
import { WEIGHTINGS, WEIGHTING_LABEL } from './stats.js';
import { analyze, groupKey, ENGINE_VERSION } from './analyze.js';
import { diagnose, summarize } from './diagnose.js';
import { buildFacts, buildPrompt, parseLlmJson, guardNarrative } from './llm.js';
import { buildReport, reportHtml, findingsCsv, quantCsv, REVIEW_STATUS } from './report.js';
import { generateDataset, SCENARIOS, allScenarioIds } from './synth.js';
import { defaultSettings } from './pipeline.js';
import { pointChart } from './charts.js';
import { elnExport, elnCsv, ELN_CONTRACT } from './eln.js';

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const VIEWS = ['dashboard', 'import', 'calibration', 'qc', 'assistant', 'report'];
const SEV = { fail: '미충족', warn: '주의', info: '참고', pass: '적합' };
const n4 = v => isNum(v) ? (Math.abs(v) >= 1e9 ? v.toExponential(3) : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-US') : Number(v.toPrecision(4)).toString()) : '–';
const sg = (v, d) => isNum(v) ? (v >= 0 ? '+' : '') + v.toFixed(d === undefined ? 1 : d) : '–';
const now = () => { const d = new Date(); const p = n => String(n).padStart(2, '0'); return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds()); };
const pill = (sev, text) => '<span class="pill ' + sev + '">' + esc(text || SEV[sev]) + '</span>';

const S = { view: 'dashboard', source: null, sheets: null, sheetIndex: 0, table: null, mapping: null, confidence: {}, constants: { analyte: '', batchId: '' }, typeMap: {}, assumeDilutionOne: false,
  built: null, settings: defaultSettings(), result: null, cards: [], summary: [], reviews: {}, log: [], llm: null, llmBusy: false,
  cal: { batch: '', analyte: '', log: true, exRow: null }, qc: { batch: '', analyte: '', sev: '' }, as: { batch: '', analyte: '', onlyHyp: true }, elnBatch: '' };
const caps = { downloads: null, sample: null, ready: false, framed: !!(typeof window !== 'undefined' && window.claude && window.claude.use) };
function addLog(action, target, note) { S.log.push({ time: now(), action, target: target || '', note: note || '' }); }

// ───────────── 데이터 적재와 분석 ─────────────
function loadSheets(name, file, isExample) {
  S.source = { name, format: file.format, encoding: file.encoding || '', delimiter: file.delimiter || '', isExample: !!isExample }; S.sheets = file.sheets; S.sheetIndex = 0;
  S.constants = { analyte: '', batchId: '' }; S.typeMap = {}; S.reviews = {}; S.llm = null; S.settings.perGroup = {}; S.settings.excluded = {}; S.settings.method = null; S.cal = { batch: '', analyte: '', log: true, exRow: null }; S.qc = { batch: '', analyte: '', sev: '' }; S.as = { batch: '', analyte: '', onlyHyp: true };
  S.log = []; addLog('파일 불러오기', name, file.format + (file.encoding ? ', ' + file.encoding : '') + (isExample ? ', 합성 예시 데이터' : ''));
  setSheet(0);
}
function setSheet(i) { S.sheetIndex = i; S.table = toTable(S.sheets[i]); const am = autoMap(S.table.headers); S.mapping = am.mapping; S.confidence = am.confidence; rebuild(true); }
function rebuild(run) {
  S.built = buildRecords(S.table, S.mapping, { constants: S.constants, typeMap: S.typeMap, assumeDilutionOne: S.assumeDilutionOne });
  if (run) runAnalysis();
}
function runAnalysis() {
  if (!S.built || S.built.blocked || !S.built.records.length) { S.result = null; S.cards = []; S.summary = []; return; }
  const st = S.built.stats; if (!S.settings.method) S.settings.method = st.hasIs ? 'internal' : 'external';
  S.result = analyze(S.built.records, S.settings, { hasIs: st.hasIs, hasRt: st.hasRt, hasOrder: st.hasOrder, hasDilution: st.hasDilution });
  S.cards = diagnose(S.result); S.summary = summarize(S.result); S.llm = null;
  const g0 = S.result.groups[0]; if (!S.result.groups.some(g => g.batchId === S.cal.batch && g.analyte === S.cal.analyte)) { S.cal.batch = g0.batchId; S.cal.analyte = g0.analyte; }
}
function rerun(action, target, note) { addLog(action, target, note); runAnalysis(); render(); }
function loadDemo(which) {
  const ids = which === 'all' ? allScenarioIds() : [which]; const rows = generateDataset(ids, 1);
  loadSheets(which === 'all' ? '합성 예시: 전체 9개 배치' : '합성 예시: ' + SCENARIOS.find(s => s.id === which).name, { format: '내장 합성 데이터', sheets: [{ name: 'synthetic', rows }] }, true);
}

// ───────────── 공통 표시 ─────────────
function renderSource() {
  const s = S.source; if (!s) { $('source-strip').innerHTML = '<span>불러온 데이터가 없습니다.</span>'; return; }
  const st = S.built ? S.built.stats : null;
  $('source-strip').innerHTML = '<span><b>' + esc(s.name) + '</b></span>' + (s.isExample ? '<span class="tag">합성 예시 데이터 · 실제 측정값 아님</span>' : '') + '<span>' + esc(s.format) + (s.encoding ? ' · ' + esc(s.encoding) : '') + '</span>' +
    (st ? '<span>' + st.rows + '행 중 ' + (st.usable || 0) + '행 분석' + (st.excluded ? ', ' + st.excluded + '행 제외' : '') + '</span>' : '') + (S.result ? '<span>엔진 v' + ENGINE_VERSION + '</span>' : '<span class="pill fail">분석 불가: Data Import 확인</span>');
  const c = $('tab-qc-count'); const n = S.result ? S.result.dashboard.qcWarnings : 0; c.hidden = !n; c.textContent = n;
}
function needResult(id, msg) { if (S.result) return false; $(id).innerHTML = '<div class="banner err"><span class="ico">✕</span><span>' + (msg || '분석 결과가 없습니다. Data Import에서 파일과 컬럼 매핑을 확인하세요.') + '</span></div>'; return true; }
function opt(value, label, sel) { return '<option value="' + esc(value) + '"' + (String(value) === String(sel) ? ' selected' : '') + '>' + esc(label) + '</option>'; }
function batchAnalyteSelects(prefix, st, allowAll) {
  const r = S.result; return '<label class="inline" for="' + prefix + '-batch">배치 <select id="' + prefix + '-batch">' + (allowAll ? opt('', '전체', st.batch) : '') + r.batches.map(b => opt(b, b, st.batch)).join('') + '</select></label>' +
    '<label class="inline" for="' + prefix + '-analyte">분석물 <select id="' + prefix + '-analyte">' + (allowAll ? opt('', '전체', st.analyte) : '') + r.analytes.map(a => opt(a, a, st.analyte)).join('') + '</select></label>';
}

// ───────────── Dashboard ─────────────
function renderDashboard() {
  if (!S.result) { $('dash-lead').textContent = ''; $('dash-tiles').innerHTML = ''; $('dash-matrix').innerHTML = ''; $('dash-top').innerHTML = ''; $('dash-review').innerHTML = ''; needResult('dash-banners'); return; }
  const r = S.result, d = r.dashboard;
  $('dash-lead').textContent = S.summary[0];
  const tile = (label, val, sub) => '<div class="tile"><span class="t-label">' + label + '</span><span class="t-val">' + val + '</span><span class="t-sub">' + sub + '</span></div>';
  $('dash-tiles').innerHTML = tile('전체 배치 수', d.batches, '데이터 ' + d.rows + '행') + tile('분석 항목 수', d.analytes, r.analytes.map(esc).join(', ')) + tile('QC 경고 수', d.qcWarnings, '기준 미충족 ' + d.fail + ' · 주의 ' + d.warn + ' · 참고 ' + d.info) + tile('검토 필요 시료 수', d.reviewSamples, '미지 시료 ' + d.samples + '개 중');
  let b = ''; const errs = S.built.issues.filter(i => i.severity === 'error'); const guess = Object.keys(S.confidence).filter(k => S.confidence[k] === 'guess' && S.mapping[k] >= 0);
  if (S.source.isExample) b += '<div class="banner plain"><span class="ico">i</span><span>지금 보이는 것은 합성 예시 데이터입니다. 자신의 파일은 <b>Data Import</b>에서 올립니다.</span></div>';
  if (errs.length) b += '<div class="banner"><span class="ico">!</span><span>입력 데이터에 문제 ' + errs.length + '건이 있습니다. 해당 값은 채우지 않고 계산에서 제외했습니다. <button class="btn small" data-go="import">Data Import에서 보기</button></span></div>';
  if (guess.length) b += '<div class="banner"><span class="ico">!</span><span>컬럼 매핑 일부는 이름으로 추정했습니다(' + guess.map(k => FIELDS.find(f => f.key === k).label).join(', ') + '). <button class="btn small" data-go="import">매핑 확인</button></span></div>';
  $('dash-banners').innerHTML = b;
  let t = '<table class="matrix"><thead><tr><th>배치</th>' + r.analytes.map(a => '<th>' + esc(a) + '</th>').join('') + '</tr></thead><tbody>';
  for (const batch of r.batches) { t += '<tr><td>' + esc(batch) + '</td>';
    for (const a of r.analytes) { const g = r.groups.find(x => x.batchId === batch && x.analyte === a); if (!g) { t += '<td class="note">–</td>'; continue; }
      const f = g.findings.filter(x => x.severity === 'fail').length, w = g.findings.filter(x => x.severity === 'warn').length; const sev = f ? 'fail' : w ? 'warn' : 'pass';
      t += '<td><button data-cell="' + esc(batch) + '||' + esc(a) + '" aria-label="' + esc(batch + ' ' + a + ' QC 검토') + '">' + pill(sev, sev === 'pass' ? '적합' : (f ? '미충족 ' + f : '') + (f && w ? ' · ' : '') + (w ? '주의 ' + w : '')) + '</button></td>'; }
    t += '</tr>'; }
  $('dash-matrix').innerHTML = t + '</tbody></table>';
  const top = r.findings.filter(f => f.severity !== 'info').slice(0, 8);
  $('dash-top').innerHTML = top.length ? '<div class="table-wrap"><table><tbody>' + top.map(f => '<tr class="clickable" data-cell="' + esc(f.batchId) + '||' + esc(f.analyte) + '"><td>' + pill(f.severity) + '</td><td style="min-width:150px"><b>' + esc(f.label) + '</b><span class="sub">' + esc(f.batchId) + '<br>' + esc(f.analyte) + '</span></td><td>' + esc(f.observed.length > 110 ? f.observed.slice(0, 110) + '…' : f.observed) + '</td></tr>').join('') + '</tbody></table></div>' : '<div class="banner ok"><span class="ico">✓</span><span>설정된 기준을 벗어난 항목이 없습니다.</span></div>';
  $('dash-review-count').textContent = r.review.length + '개';
  $('dash-review').innerHTML = r.review.length ? '<table><thead><tr><th>배치</th><th>시료</th><th>사유</th></tr></thead><tbody>' + r.review.map(s => '<tr><td>' + esc(s.batchId) + '</td><td class="mono">' + esc(s.sampleId) + '</td><td>' + s.reasons.map(x => esc(x.analyte) + ': ' + esc(x.reason) + (x.level === 'batch' ? ' <span class="tag">배치 수준</span>' : '')).join('<br>') + '</td></tr>').join('') + '</tbody></table>' : '<p class="note" style="padding:10px">검토가 필요한 시료가 없습니다.</p>';
}

// ───────────── Data Import ─────────────
function renderImport() {
  if (!S.table) { $('import-body').innerHTML = ''; return; }
  const t = S.table, b = S.built, src = S.source; let h = '';
  h += '<div class="panel"><h2>파일 정보</h2><dl class="kv"><dt>파일</dt><dd>' + esc(src.name) + '</dd><dt>형식</dt><dd>' + esc(src.format) + (src.encoding ? ' · 인코딩 ' + esc(src.encoding) : '') + (src.delimiter ? ' · 구분자 ' + esc(src.delimiter) : '') + '</dd><dt>크기</dt><dd>' + t.rows.length + '행 × ' + t.headers.length + '열</dd></dl>' +
    (S.sheets.length > 1 ? '<label class="inline" for="sheet-select">시트 <select id="sheet-select">' + S.sheets.map((s, i) => opt(i, s.name + ' (' + s.rows.length + '행)', S.sheetIndex)).join('') + '</select></label>' : '') + '</div>';
  // 매핑
  h += '<div class="panel"><h2>컬럼 매핑 <small>파일의 열을 분석 항목에 연결</small></h2><div class="table-wrap"><table><thead><tr><th>분석 항목</th><th>파일의 열</th><th>첫 값 예</th><th>상태</th></tr></thead><tbody>';
  for (const f of FIELDS) {
    const i = S.mapping[f.key]; const sample = i >= 0 ? t.rows.slice(0, 3).map(r => r[i]).filter(v => v !== '').slice(0, 3).join(', ') : '';
    let status = i >= 0 ? (S.confidence[f.key] === 'guess' ? pill('warn', '추정: 확인 필요') : pill('pass', '연결됨')) : (f.required ? (f.constantOk && String(S.constants[f.key] || '').trim() ? pill('pass', '고정값 사용') : pill('fail', '필수 항목 없음')) : pill('info', '없음(선택 항목)'));
    h += '<tr class="maprow"><td><b>' + esc(f.label) + '</b><span class="sub">' + esc(f.ko) + (f.required ? ' · 필수' : ' · 선택') + '</span></td><td><select id="map-' + f.key + '" data-map="' + f.key + '" aria-label="' + esc(f.label) + ' 열">' + opt(-1, '(없음)', i) + t.headers.map((hd, k) => opt(k, hd, i)).join('') + '</select>' +
      (f.constantOk && i < 0 ? ' <input type="text" id="const-' + f.key + '" data-const="' + f.key + '" value="' + esc(S.constants[f.key] || '') + '" placeholder="파일 전체에 쓸 고정값" style="width:170px" aria-label="' + esc(f.label) + ' 고정값">' : '') + '</td><td class="mono">' + esc(sample) + '</td><td>' + status + '</td></tr>';
  }
  h += '</tbody></table></div><div class="toolbar"><label class="inline" for="assume-dil"><input type="checkbox" id="assume-dil"' + (S.assumeDilutionOne ? ' checked' : '') + '> 희석배수 누락 시 1로 간주 <span class="note">(끄면 해당 행의 최종 농도를 계산하지 않습니다)</span></label></div></div>';
  // 인식하지 못한 유형
  const unk = b.issues.filter(i => i.code === 'UNKNOWN_TYPE'); const mapped = Object.keys(S.typeMap);
  if (unk.length || mapped.length) { const raws = Array.from(new Set(unk.map(u => u.raw).concat(mapped)));
    h += '<div class="panel"><h2>시료 유형 지정 <small>인식하지 못한 값</small></h2><div class="table-wrap"><table><thead><tr><th>파일의 값</th><th>유형</th></tr></thead><tbody>' + raws.map((raw, k) => '<tr><td class="mono">' + esc(raw) + '</td><td><select id="type-' + k + '" data-type="' + esc(raw) + '" aria-label="' + esc(raw) + ' 유형">' + opt('', '(분석에서 제외)', S.typeMap[raw] || '') + Object.keys(TYPES).map(tk => opt(tk, TYPES[tk], S.typeMap[raw] || '')).join('') + '</select></td></tr>').join('') + '</tbody></table></div></div>'; }
  // 누락·문제
  const order = { error: 0, warn: 1, info: 2 }; const iss = b.issues.slice().sort((x, y) => order[x.severity] - order[y.severity]);
  h += '<div class="panel"><h2>누락 항목과 데이터 문제 <small>' + iss.filter(i => i.severity === 'error').length + '건 오류 · ' + iss.filter(i => i.severity === 'warn').length + '건 주의</small></h2>' +
    (iss.length ? '<div class="table-wrap"><table><tbody>' + iss.map(i => '<tr><td style="width:80px">' + pill(i.severity === 'error' ? 'fail' : i.severity === 'warn' ? 'warn' : 'info', i.severity === 'error' ? '오류' : i.severity === 'warn' ? '주의' : '참고') + '</td><td>' + esc(i.message) + (i.rows && i.rows.length ? '<span class="sub">행 번호: ' + i.rows.slice(0, 20).join(', ') + (i.rows.length > 20 ? ' 외 ' + (i.rows.length - 20) + '개' : '') + '</span>' : '') + '</td></tr>').join('') + '</tbody></table></div>' : '<div class="banner ok"><span class="ico">✓</span><span>누락되거나 잘못된 값이 없습니다.</span></div>') +
    (b.blocked ? '<div class="banner err"><span class="ico">✕</span><span>필수 항목이 연결되지 않아 분석할 수 없습니다. 위 매핑에서 열을 지정하세요.</span></div>' : '<div class="toolbar"><button class="btn primary" data-go="dashboard">분석 결과 보기</button><span class="note">' + (S.result ? b.stats.usable + '행을 분석했습니다. 매핑을 바꾸면 즉시 다시 분석합니다.' : '분석할 수 있는 행이 없습니다.') + '</span></div>') + '</div>';
  // 미리보기
  const rev = {}; for (const f of FIELDS) if (S.mapping[f.key] >= 0) rev[S.mapping[f.key]] = f.label;
  h += '<div class="panel"><h2>데이터 미리보기 <small>처음 15행 · 파일 값 그대로</small></h2><div class="table-wrap"><table><thead><tr><th class="n">행</th>' + t.headers.map((hd, k) => '<th>' + esc(hd) + (rev[k] ? '<span class="sub">→ ' + esc(rev[k]) + '</span>' : '<span class="sub">사용 안 함</span>') + '</th>').join('') + '</tr></thead><tbody>' +
    t.rows.slice(0, 15).map((r, i) => '<tr><td class="n">' + (i + 2) + '</td>' + r.map(v => '<td class="mono">' + esc(v) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div></div>';
  $('import-body').innerHTML = h;
}
async function handleFile(file) {
  $('import-error').innerHTML = '';
  try { const buf = new Uint8Array(await file.arrayBuffer()); const res = await readTableFile(file.name, buf); toTable(res.sheets[0]); loadSheets(file.name, res, false); show('import'); }
  catch (e) { $('import-error').innerHTML = '<div class="banner err"><span class="ico">✕</span><span><b>' + esc(file.name) + '</b>을(를) 읽지 못했습니다. ' + esc(e && e.message ? e.message : String(e)) + ' 기존에 불러온 데이터는 그대로 둡니다.</span></div>'; }
}

// ───────────── Calibration ─────────────
function renderCalibration() {
  if (needResult('cal-body')) { $('cal-toolbar').innerHTML = ''; return; }
  const r = S.result; let g = r.groups.find(x => x.batchId === S.cal.batch && x.analyte === S.cal.analyte); if (!g) { g = r.groups.find(x => x.batchId === S.cal.batch) || r.groups[0]; S.cal.batch = g.batchId; S.cal.analyte = g.analyte; }
  const c = g.cal; const key = g.key;
  $('cal-toolbar').innerHTML = batchAnalyteSelects('cal', S.cal, false) + '<label class="inline" for="cal-method">정량 방식 <select id="cal-method">' + opt('internal', '내부표준법 (면적비)', g.method) + opt('external', '외부표준법 (면적)', g.method) + '</select></label>' +
    '<label class="inline" for="cal-weight">가중치 <select id="cal-weight">' + WEIGHTINGS.map(w => opt(w, WEIGHTING_LABEL[w], g.weighting)).join('') + '</select></label><label class="inline" for="cal-log"><input type="checkbox" id="cal-log"' + (S.cal.log ? ' checked' : '') + '> 로그 축</label>';
  let h = ''; const cfg = g.findings.filter(f => f.code.startsWith('CAL_CONFIG') || f.code === 'CAL_NO_STANDARDS');
  h += '<div class="banner ' + (c.verdict === 'pass' ? 'ok' : 'err') + '"><span class="ico">' + (c.verdict === 'pass' ? '✓' : '✕') + '</span><span><b>' + esc(g.batchId) + ' / ' + esc(g.analyte) + ': 검량선 ' + (c.verdict === 'pass' ? '적합' : c.verdict === 'fail' ? '부적합' : '평가 불가') + '</b>' + (c.error ? ' — ' + esc(c.error) : '') + (c.verdict === 'fail' ? ' 이 검량선으로 계산한 농도는 참고값입니다.' : '') + '</span></div>';
  for (const f of cfg) h += '<div class="banner' + (f.severity === 'fail' ? ' err' : '') + '"><span class="ico">' + (f.severity === 'fail' ? '✕' : '!') + '</span><span><b>' + esc(f.label) + '</b> ' + esc(f.observed) + '</span></div>';
  if (c.ok) {
    const unit = c.method === 'internal' ? '면적비 (분석물 / 내부표준)' : '피크 면적';
    h += '<div class="grid2"><div class="panel"><h3>검량선 그래프</h3><div class="legend"><span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="var(--s1)"/></svg>기준 내 검량점</span><span><svg width="14" height="14"><path d="M7 1L13 7L7 13L1 7Z" fill="var(--bad)"/></svg>기준 밖</span><span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="none" stroke="var(--muted)" stroke-width="1.5"/></svg>회귀에서 제외</span><span><svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke="var(--fit)" stroke-width="1.5"/></svg>회귀선</span></div><div id="cal-plot"></div></div>' +
      '<div class="panel"><h3>잔차 그래프 <small>검량점별 역산 편차 (%)</small></h3><div class="legend"><span><svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke="var(--bad)"/></svg>허용 편차 ±' + S.settings.rules.cal.devPct + '% (최저점 ±' + S.settings.rules.cal.devPctLloq + '%)</span></div><div id="dev-plot"></div></div></div>';
    h += '<div class="grid2"><div class="panel"><h3>회귀식</h3><p class="eqn">' + esc(c.equation) + '</p><dl class="kv"><dt>기울기</dt><dd>' + n4(c.fit.slope) + ' ± ' + n4(c.fit.seSlope) + '</dd><dt>절편</dt><dd>' + n4(c.fit.intercept) + ' ± ' + n4(c.fit.seIntercept) + '</dd><dt>R² (참고)</dt><dd>' + c.fit.r2.toFixed(5) + '</dd><dt>가중치</dt><dd>' + WEIGHTING_LABEL[c.weighting] + '</dd><dt>사용한 점</dt><dd>' + c.fit.n + '개, ' + c.nLevels + '개 수준</dd><dt>정량 범위</dt><dd>' + n4(c.lloq) + ' – ' + n4(c.uloq) + '</dd></dl></div>' +
      '<div class="panel"><h3>적합성 기준 <span class="tag">예시 기준</span></h3><div class="crit">' + c.criteria.map(x => '<div>' + pill(x.pass ? 'pass' : 'fail', x.pass ? '충족' : '미충족') + '<span><b>' + esc(x.label) + '</b>: ' + esc(x.observed) + ' <span class="note">(기준 ' + esc(x.limit) + ')</span></span></div>').join('') + '</div>' +
      '<h4 style="margin-top:6px">진단</h4><ul class="plain">' + (c.diagnostics.curvature ? '<li>곡률: 2차 항 F 검정 p = ' + c.diagnostics.curvature.p.toExponential(2) + ', 최고 농도에서 ' + sg(c.diagnostics.curvature.curvaturePct) + '% → ' + (c.nonlinear ? '<b>비선형성 경고</b>' : '경고 없음') + '</li>' : '<li>곡률: 점이 부족해 검정하지 않음</li>') +
      '<li>이상점 후보: ' + (c.diagnostics.outliers.length ? c.diagnostics.outliers.map(o => '<b>' + n4(o.nominal) + '</b> (' + esc(o.basis) + ')').join(', ') : '없음') + '</li></ul></div></div>';
    h += '<div class="panel"><h3>역산 결과 <small>역산 농도 = (응답 − 절편) / 기울기</small></h3><div class="table-wrap"><table><thead><tr><th>표준</th><th class="n">명목 농도</th><th class="n">피크 면적</th><th class="n">내부표준 면적</th><th class="n">응답</th><th class="n">역산 농도</th><th class="n">편차</th><th class="n">허용</th><th>판정</th><th class="no-print">회귀에서</th></tr></thead><tbody>';
    for (const p of c.points) {
      const ex = S.cal.exRow === p.row;
      h += '<tr class="' + (p.included ? '' : 'off') + '"><td class="mono">' + esc(p.sampleId) + (p.level ? '<span class="sub">' + esc(p.level) + '</span>' : '') + '</td><td class="n">' + n4(p.nominal) + '</td><td class="n">' + n4(p.area) + '</td><td class="n">' + n4(p.isArea) + '</td><td class="n">' + n4(p.response) + '</td><td class="n">' + (p.included ? n4(p.backCalc) : '–') + '</td><td class="n' + (p.included && !p.pass ? ' cell-bad' : '') + '">' + (p.included ? sg(p.devPct) + '%' : '–') + '</td><td class="n">' + (p.included ? '±' + p.limit + '%' : '–') + '</td><td>' + (p.included ? pill(p.pass ? 'pass' : 'fail', p.pass ? '기준 내' : '기준 밖') : pill('info', '제외') + '<span class="sub">' + esc(p.reason) + '</span>') + '</td><td class="no-print">' +
        (p.excludedBy === 'user' ? '<button class="btn small" data-restore="' + p.row + '">되돌리기</button>' : p.included ? (ex ? '<input type="text" id="ex-reason" placeholder="제외 사유(필수)" style="width:170px" aria-label="제외 사유"> <button class="btn small primary" data-exok="' + p.row + '">제외</button> <button class="btn small" data-excancel="1">취소</button>' : '<button class="btn small" data-ex="' + p.row + '">제외…</button>') : '') + '</td></tr>';
    }
    h += '</tbody></table></div><p class="note">검량점 제외는 사용자만 할 수 있고 사유와 함께 검토 기록에 남습니다. 도구가 스스로 점을 빼지 않습니다.</p></div>';
    h += '<div class="panel"><h3>가중치 비교 <small>같은 검량점에 가중치만 바꿔 적합한 결과</small></h3><div class="table-wrap"><table><thead><tr><th>가중치</th><th class="n">|편차| 합</th><th class="n">최대 |편차|</th><th class="n">기준 내 점</th><th class="n">R²</th></tr></thead><tbody>' + c.diagnostics.weightingComparison.map(w => w.error ? '<tr class="off"><td>' + WEIGHTING_LABEL[w.scheme] + '</td><td colspan="4">' + esc(w.error) + '</td></tr>' : '<tr><td>' + WEIGHTING_LABEL[w.scheme] + (w.selected ? ' <span class="tag">선택됨</span>' : '') + '</td><td class="n">' + w.sumAbsRE.toFixed(1) + '%</td><td class="n">' + w.maxAbsRE.toFixed(1) + '%</td><td class="n">' + w.nPass + '/' + w.n + '</td><td class="n">' + w.r2.toFixed(5) + '</td></tr>').join('') + '</tbody></table></div><p class="note">R²는 가중 없음에서 가장 높게 나오기 쉽지만 저농도 편차는 커질 수 있습니다. 가중치는 분석법 밸리데이션에서 정한 것을 써야 합니다(ICH M10 3.2.4).</p></div>';
  }
  $('cal-body').innerHTML = h;
  if (c.ok) {
    const inc = c.points.filter(p => isNum(p.nominal) && p.nominal > 0 && isNum(p.response));
    pointChart($('cal-plot'), { xLog: S.cal.log, yLog: S.cal.log, xZero: true, yZero: true, xLabel: '명목 농도', yLabel: c.method === 'internal' ? '면적비' : '피크 면적', ariaLabel: '검량선', fn: { f: x => c.fit.slope * x + c.fit.intercept, cls: 'fit' },
      points: inc.map(p => ({ x: p.nominal, y: p.response, state: !p.included ? 'off' : p.pass ? 'ok' : 'bad', tip: '<b>' + esc(p.sampleId) + '</b><br>명목 ' + n4(p.nominal) + ' · 응답 ' + n4(p.response) + (p.included ? '<br>역산 ' + n4(p.backCalc) + ' (' + sg(p.devPct) + '%)' : '<br>제외: ' + esc(p.reason)) })) });
    const ip = c.points.filter(p => p.included); const R = S.settings.rules.cal; const lo = c.lloq;
    pointChart($('dev-plot'), { xLog: true, xLabel: '명목 농도 (로그 축)', yLabel: '역산 편차 (%)', ariaLabel: '역산 편차', yPad: 0.15, hlines: [{ y: 0, cls: 'zero' }, { y: R.devPct, cls: 'limit', label: '+' + R.devPct + '%' }, { y: -R.devPct, cls: 'limit', label: '−' + R.devPct + '%' }],
      steps: R.devPctLloq !== R.devPct ? [{ x1: lo * 0.8, x2: lo * 1.25, y: R.devPctLloq }, { x1: lo * 0.8, x2: lo * 1.25, y: -R.devPctLloq }] : [],
      points: ip.map(p => ({ x: p.nominal, y: p.devPct, state: p.pass ? 'ok' : 'bad', tip: '<b>' + esc(p.sampleId) + '</b><br>명목 ' + n4(p.nominal) + '<br>편차 ' + sg(p.devPct) + '% (허용 ±' + p.limit + '%)' })) });
  }
}

// ───────────── QC Review ─────────────
function renderQc() {
  buildRulesPanel();
  if (needResult('qc-table')) { $('qc-toolbar').innerHTML = ''; $('qc-detail').innerHTML = ''; return; }
  const r = S.result; const list = r.findings.filter(f => (!S.qc.batch || f.batchId === S.qc.batch) && (!S.qc.analyte || f.analyte === S.qc.analyte) && (!S.qc.sev || f.severity === S.qc.sev));
  $('qc-toolbar').innerHTML = batchAnalyteSelects('qc', S.qc, true) + '<label class="inline" for="qc-sev">판정 <select id="qc-sev">' + opt('', '전체', S.qc.sev) + opt('fail', '기준 미충족', S.qc.sev) + opt('warn', '주의', S.qc.sev) + opt('info', '참고·평가 불가', S.qc.sev) + '</select></label><span class="note">' + list.length + '건 표시 / 전체 ' + r.findings.length + '건</span>';
  let t = '<table><thead><tr><th>판정</th><th>오류 유형</th><th>배치 / 분석물</th><th>관측값</th><th>기준 및 근거</th><th class="no-print">검토</th></tr></thead><tbody>';
  if (!list.length) t += '<tr><td colspan="6" class="note">조건에 맞는 항목이 없습니다.</td></tr>';
  for (const f of list) {
    const meta = f.ruleKey ? RULE_META.find(m => m.path === f.ruleKey) : null; const rv = S.reviews[f.id] || { status: 'open', note: '' };
    t += '<tr><td>' + pill(f.severity) + '</td><td><b>' + esc(f.label) + '</b><span class="sub mono">' + esc(f.code) + '</span>' + (f.code.startsWith('CAL') ? '<button class="btn small no-print" data-tocal="' + esc(f.batchId) + '||' + esc(f.analyte) + '">검량선 보기</button>' : '') + '</td><td>' + esc(f.batchId) + '<span class="sub">' + esc(f.analyte) + '</span></td><td>' + esc(f.observed) + (f.sampleIds.length && f.sampleIds.length <= 12 ? '<span class="sub">대상: ' + esc(f.sampleIds.join(', ')) + '</span>' : '') + '</td>' +
      '<td>' + esc(f.criterion) + (meta ? ' <span class="tag">예시 기준</span><span class="sub">출처: ' + esc(meta.source) + '</span>' : '') + '<span class="sub">계산: ' + esc(f.basis) + '</span></td>' +
      '<td class="no-print" style="min-width:170px">' + (f.severity === 'info' ? '<span class="note">–</span>' : '<select data-review="' + esc(f.id) + '" aria-label="검토 상태">' + Object.keys(REVIEW_STATUS).map(k => opt(k, REVIEW_STATUS[k], rv.status)).join('') + '</select><input type="text" data-note="' + esc(f.id) + '" value="' + esc(rv.note || '') + '" placeholder="메모" style="width:100%;margin-top:4px" aria-label="검토 메모">') + '</td></tr>';
  }
  $('qc-table').innerHTML = t + '</tbody></table>';
  const g = S.qc.batch && S.qc.analyte ? r.groups.find(x => x.batchId === S.qc.batch && x.analyte === S.qc.analyte) : null;
  if (!g) { $('qc-detail').innerHTML = '<p class="note">배치와 분석물을 모두 고르면 QC 통계 표와 내부표준·머무름 시간 그래프가 나옵니다.</p>'; return; }
  const T = g.tables; const R = S.settings.rules; let h = ''; const pf = i => i.status === 'not_evaluated' ? pill('info', '평가 불가') + '<span class="sub">' + esc(i.note) + '</span>' : pill(i.pass ? 'pass' : 'fail', i.pass ? '기준 내' : '기준 밖');
  h += '<div class="grid2"><div class="panel"><h3>QC 시료 통계 <small>수준별 평균·표준편차·RSD</small></h3>' + (T.qcLevels.length ? '<div class="table-wrap"><table><thead><tr><th class="n">명목</th><th class="n">n</th><th class="n">평균</th><th class="n">표준편차</th><th class="n">RSD</th><th class="n">평균 상대오차</th><th class="n">기준 내</th></tr></thead><tbody>' + T.qcLevels.map(l => '<tr><td class="n">' + n4(l.nominal) + '</td><td class="n">' + l.n + '</td><td class="n">' + n4(l.mean) + '</td><td class="n">' + n4(l.sd) + '</td><td class="n' + (isNum(l.rsd) && l.rsd > l.rsdLimit ? ' cell-bad' : '') + '">' + (isNum(l.rsd) ? l.rsd.toFixed(1) + '%' : '–') + '</td><td class="n">' + sg(l.meanRePct) + '%</td><td class="n">' + l.nPass + '/' + l.n + '</td></tr>').join('') + '</tbody></table></div>' : '<p class="note">평가할 수 있는 QC 시료가 없습니다.</p>') +
    (T.qcItems.length ? '<details><summary>개별 QC ' + T.qcItems.length + '개</summary><div class="table-wrap"><table><thead><tr><th>시료</th><th class="n">명목</th><th class="n">측정</th><th class="n">상대오차</th><th>판정</th></tr></thead><tbody>' + T.qcItems.map(i => '<tr><td class="mono">' + esc(i.sampleId) + '</td><td class="n">' + n4(i.nominal) + '</td><td class="n">' + n4(i.measured) + '</td><td class="n">' + (isNum(i.rePct) ? sg(i.rePct) + '%' : '–') + '</td><td>' + pf(i) + '</td></tr>').join('') + '</tbody></table></div></details>' : '') + '</div>';
  h += '<div class="panel"><h3>바탕 · 첨가 · 중복</h3><div class="table-wrap"><table><thead><tr><th>항목</th><th>시료</th><th>값</th><th>기준</th><th>판정</th></tr></thead><tbody>' +
    T.blanks.map(i => '<tr><td>' + esc(TYPES[i.type]) + '</td><td class="mono">' + esc(i.sampleId) + '</td><td>' + (R.blank.mode === 'conc' ? '농도 ' + n4(i.value) : 'LLOQ 응답의 ' + (isNum(i.pctOfLloq) ? i.pctOfLloq.toFixed(1) + '%' : '–')) + '</td><td>' + (R.blank.mode === 'conc' ? '< ' + n4(i.limit) : '≤ ' + i.limit + '%') + '</td><td>' + pf(i) + '</td></tr>').join('') +
    T.spikes.map(i => '<tr><td>첨가 회수율</td><td class="mono">' + esc(i.sampleId) + (i.parentId ? '<span class="sub">원시료 ' + esc(i.parentId) + '</span>' : '<span class="sub">원시료 연결 없음</span>') + '</td><td>' + (isNum(i.recoveryPct) ? i.recoveryPct.toFixed(1) + '%' : '–') + '</td><td>' + i.min + '–' + i.max + '%</td><td>' + pf(i) + '</td></tr>').join('') +
    T.dups.concat(T.reps).map(i => '<tr><td>' + (i.n === 2 ? '중복 (RPD)' : '반복 (RSD, n=' + i.n + ')') + '</td><td class="mono">' + esc(i.sampleId) + '</td><td>' + (isNum(i.rpd) ? i.rpd.toFixed(1) + '%' : isNum(i.rsd) ? i.rsd.toFixed(1) + '%' : '–') + '<span class="sub">' + i.values.map(n4).join(' / ') + '</span></td><td>≤ ' + (i.limit !== undefined ? i.limit : (i.n === 2 ? R.dup.rpdPct : R.rep.rsdPct)) + '%</td><td>' + pf(i) + '</td></tr>').join('') +
    (T.blanks.length + T.spikes.length + T.dups.length + T.reps.length ? '' : '<tr><td colspan="5" class="note">해당 시료가 없습니다.</td></tr>') + '</tbody></table></div>' + (T.missing.length ? '<div class="banner err"><span class="ico">✕</span><span>필수 QC 누락: ' + T.missing.map(m => esc(m.what) + ' ' + m.have + '/' + m.need).join(', ') + '</span></div>' : '') + '</div></div>';
  h += '<div class="grid2"><div class="panel"><h3>내부표준 응답 <small>검량 표준 평균 대비 %, 주입 순서</small></h3><div id="is-plot"></div>' + (T.isTrend ? '<p class="note">선형 추세: 배치 전체에서 ' + sg(T.isTrend.changePct, 0) + '%, p = ' + T.isTrend.p.toExponential(1) + '</p>' : '') + '</div><div class="panel"><h3>머무름 시간 <small>검량 표준 평균과의 차이(분), 주입 순서</small></h3><div id="rt-plot"></div>' + (T.rtTrend ? '<p class="note">선형 추세: p = ' + T.rtTrend.p.toExponential(1) + '</p>' : '') + '</div></div>';
  $('qc-detail').innerHTML = h;
  if (T.isItems.length) pointChart($('is-plot'), { xLabel: '주입 순서' + (r.meta.hasOrder ? '' : ' (행 순서)'), yLabel: '내부표준 면적 (%)', ariaLabel: '내부표준 응답', height: 220, hlines: [{ y: 100, cls: 'refline' }, { y: R.is.minPct, cls: 'limit', label: R.is.minPct + '%' }, { y: R.is.maxPct, cls: 'limit', label: R.is.maxPct + '%' }], points: T.isItems.map(i => ({ x: i.order, y: i.pct, state: i.pass ? 'ok' : 'bad', tip: '<b>' + esc(i.sampleId) + '</b> (' + esc(TYPES[i.type]) + ')<br>내부표준 면적 ' + n4(i.isArea) + '<br>' + i.pct.toFixed(0) + '%' })) });
  else $('is-plot').innerHTML = '<p class="note">내부표준 면적이 없어 평가하지 않았습니다.</p>';
  if (T.rtItems.length) pointChart($('rt-plot'), { xLabel: '주입 순서' + (r.meta.hasOrder ? '' : ' (행 순서)'), yLabel: '머무름 시간 차이 (분)', ariaLabel: '머무름 시간', height: 220, hlines: [{ y: 0, cls: 'refline' }, { y: T.rtTol, cls: 'limit', label: '+' + T.rtTol.toFixed(2) }, { y: -T.rtTol, cls: 'limit', label: '−' + T.rtTol.toFixed(2) }], points: T.rtItems.map(i => ({ x: i.order, y: i.delta, state: i.pass ? 'ok' : 'bad', tip: '<b>' + esc(i.sampleId) + '</b> (' + esc(TYPES[i.type]) + ')<br>' + i.rt.toFixed(3) + '분 (' + sg(i.delta, 3) + ')' })) });
  else $('rt-plot').innerHTML = '<p class="note">머무름 시간이 없어 평가하지 않았습니다.</p>';
}
function buildRulesPanel() {
  const R = S.settings.rules; $('rules-state').textContent = R.profile === 'custom' ? '사용자 정의 값 적용 중' : (PROFILES[R.profile] || {}).name + ' 적용 중';
  $('rules-profile').innerHTML = Object.keys(PROFILES).map(k => opt(k, PROFILES[k].name, R.profile)).join('');
  $('rules-note').textContent = '모든 값은 예시입니다. 장비·분석법·규격에 따라 다르므로 실제 판정 전에 자신의 기준으로 바꾸세요. 값을 바꾸면 즉시 다시 판정하고 검토 기록에 남깁니다. ' + ((PROFILES[R.profile] || {}).note || '');
  let t = '<table><thead><tr><th>구분</th><th>항목</th><th>값</th><th>출처·비고</th></tr></thead><tbody>';
  for (const m of RULE_META) { const v = getRule(R, m.path); const id = 'rule-' + m.path.replace('.', '-');
    const input = m.bool ? '<input type="checkbox" id="' + id + '" data-rule="' + m.path + '"' + (v ? ' checked' : '') + ' aria-label="' + esc(m.label) + '">' : m.options ? '<select id="' + id + '" data-rule="' + m.path + '" aria-label="' + esc(m.label) + '">' + m.options.map(o => opt(o[0], o[1], v)).join('') + '</select>' : '<input type="number" id="' + id + '" data-rule="' + m.path + '" value="' + v + '" step="any" aria-label="' + esc(m.label) + '"> <span class="note">' + esc(m.unit) + '</span>';
    t += '<tr><td>' + esc(m.group) + '</td><td>' + esc(m.label) + '</td><td style="white-space:nowrap">' + input + '</td><td class="note">' + esc(m.source) + '</td></tr>'; }
  $('rules-table').innerHTML = t + '</tbody></table>';
}

// ───────────── AI Research Assistant ─────────────
function renderAssistant() {
  if (needResult('as-cards')) { $('as-summary').innerHTML = ''; $('as-toolbar').innerHTML = ''; return; }
  $('as-summary').innerHTML = S.summary.map(l => '<li>' + esc(l) + '</li>').join('');
  const cards = S.cards.filter(c => (!S.as.batch || c.batchId === S.as.batch) && (!S.as.analyte || c.analyte === S.as.analyte) && (!S.as.onlyHyp || c.hypotheses.length));
  $('as-toolbar').innerHTML = batchAnalyteSelects('as', S.as, true) + '<label class="inline" for="as-only"><input type="checkbox" id="as-only"' + (S.as.onlyHyp ? ' checked' : '') + '> 원인 가설이 있는 항목만</label><span class="note">' + cards.length + '건 표시 / 전체 ' + S.cards.length + '건</span>';
  let h = '';
  for (const c of cards) {
    h += '<article class="card"><div class="card-head">' + pill(c.severity) + '<h3>' + esc(c.title) + '</h3><span class="note">' + esc(c.batchId) + ' / ' + esc(c.analyte) + '</span><span class="tag">' + esc(c.causeStatus) + '</span></div>';
    h += '<div class="fact"><span class="sec-label">관측 사실</span><ul class="plain">' + c.observations.map(o => '<li>' + esc(o) + '</li>').join('') + '</ul></div>';
    if (c.hypotheses.length) {
      h += '<div class="hypo"><span class="sec-label">가능한 원인 (가설)</span>' + c.hypotheses.map(x => '<div class="hyp-item"><div><b>' + esc(x.cause) + '</b> <span class="stand">' + esc(x.standingLabel) + '</span></div>' +
        (x.support.length ? '<div class="ev"><b>이 데이터 안의 근거</b> ' + esc(x.support.join(' ')) + '</div>' : '') + (x.against.length ? '<div class="ev"><b>맞지 않는 점</b> ' + esc(x.against.join(' ')) + '</div>' : '') + (x.unknown ? '<div class="ev"><b>판단할 수 없는 부분</b> ' + esc(x.unknown) + '</div>' : '') + '</div>').join('') + '</div>';
      h += '<div class="grid2"><div><span class="sec-label">추가 확인 항목</span><ul class="plain">' + c.checks.map(o => '<li>' + esc(o) + '</li>').join('') + '</ul></div><div><span class="sec-label">권장 검증</span><ul class="plain">' + c.verifications.map(o => '<li>' + esc(o) + '</li>').join('') + '</ul></div></div>';
    } else if (c.checks.length || c.verifications.length) h += '<div><span class="sec-label">확인·조치</span><ul class="plain">' + c.checks.concat(c.verifications).map(o => '<li>' + esc(o) + '</li>').join('') + '</ul></div>';
    h += '<div class="conclusion"><b>결론</b> ' + esc(c.conclusion) + '</div></article>';
  }
  $('as-cards').innerHTML = h || '<p class="note">조건에 맞는 진단 항목이 없습니다.</p>';
  renderLlm();
}
function renderLlm() {
  const btn = $('llm-run'); btn.disabled = !caps.sample || S.llmBusy || !S.result || !S.result.findings.some(f => f.severity !== 'info');
  $('llm-state').textContent = !caps.ready ? '연결 확인 중…' : !caps.sample ? '이 환경에서는 LLM 연결을 쓸 수 없습니다(파일을 직접 열었거나 권한이 없음). 아래 규칙 기반 진단은 LLM 없이 동작합니다.' : S.llmBusy ? '응답을 기다리는 중…' : (S.result && !S.result.findings.some(f => f.severity !== 'info') ? '해석할 경고 항목이 없습니다.' : '요청하면 보는 사람의 Claude 사용량을 씁니다.');
  $('llm-stop').hidden = !S.llmBusy;
  if (!S.llm) { if (!S.llmBusy) $('llm-out').innerHTML = ''; return; }
  const L = S.llm, g = L.guard; let h = '<div class="llm-box"><div class="card-head"><span class="tag">LLM 생성 해석</span><span class="note">계산값은 엔진 결과이며 LLM이 수정하지 않았습니다. 아래는 가설과 요약입니다.</span></div>';
  h += g.ok ? '<div class="banner ok"><span class="ico">✓</span><span>자동 검사 통과: 인용한 수치 ' + g.citedCount + '개가 모두 계산 결과에 있고, 원인을 단정하는 표현이 없습니다.</span></div>' :
    '<div class="banner err"><span class="ico">✕</span><span><b>자동 검사에서 문제 발견.</b> ' + (g.unsupported.length ? '계산 결과에 없는 수치: ' + esc(g.unsupported.join(', ')) + '. ' : '') + (g.assertive.length ? '단정 표현: ' + esc(g.assertive.join(' / ')) + '. ' : '') + (g.unknownIds.length ? '존재하지 않는 항목 참조: ' + esc(g.unknownIds.join(', ')) + '. ' : '') + '이 해석은 그대로 믿지 말고 위 계산 결과와 대조하세요.</span></div>';
  if (L.data) { const o = L.data; const lab = id => { const f = S.result.findings.find(x => x.id === id); return f ? f.label + ' (' + f.batchId + ' / ' + f.analyte + ')' : id; };
    h += '<div><span class="sec-label">요약</span><p>' + esc(o.summary || '') + '</p></div>';
    if (Array.isArray(o.priorities) && o.priorities.length) h += '<div><span class="sec-label">먼저 확인할 항목</span><ul class="plain">' + o.priorities.map(p => '<li><b>' + esc(lab(p.finding_id)) + '</b> — ' + esc(p.why || '') + '</li>').join('') + '</ul></div>';
    if (Array.isArray(o.additional_hypotheses) && o.additional_hypotheses.length) h += '<div class="hypo"><span class="sec-label">추가 가설 (LLM 제안, 미확정)</span>' + o.additional_hypotheses.map(x => '<div class="hyp-item"><div><b>' + esc(x.hypothesis || '') + '</b> <span class="note">' + esc(lab(x.finding_id)) + '</span></div><div class="ev"><b>데이터 안의 근거</b> ' + esc(x.evidence_in_data || '') + '</div><div class="ev"><b>불확실성</b> ' + esc(x.uncertainty || '') + '</div><div class="ev"><b>확인 방법</b> ' + esc(x.how_to_test || '') + '</div></div>').join('') + '</div>';
    if (o.cross_findings) h += '<div><span class="sec-label">항목을 함께 볼 때</span><p>' + esc(o.cross_findings) + '</p></div>';
    if (o.caveats) h += '<div class="conclusion"><b>한계</b> ' + esc(o.caveats) + '</div>';
  } else h += '<div><span class="sec-label">원문 (형식을 해석하지 못함)</span><p style="white-space:pre-wrap">' + esc(L.raw) + '</p></div>';
  $('llm-out').innerHTML = h + '</div>';
}
let llmCtl = null;
async function runLlm() {
  if (!caps.sample || S.llmBusy) return; const facts = buildFacts(S.result, S.cards, S.summary); const prompt = buildPrompt(facts);
  S.llmBusy = true; S.llm = null; llmCtl = new AbortController(); renderLlm(); $('llm-out').innerHTML = '<p class="note">Claude가 생각하는 중…</p>';
  try { const res = await caps.sample(prompt, { signal: llmCtl.signal, cache: false, onText: ({ text }) => { $('llm-out').innerHTML = '<p class="note" style="white-space:pre-wrap">' + esc(text.slice(-600)) + '</p>'; } });
    const parsed = parseLlmJson(res.text); S.llm = Object.assign(parsed, { guard: guardNarrative(parsed, facts), time: now(), truncated: !!res.truncated }); addLog('LLM 해석 요청', '', '자동 검사 ' + (S.llm.guard.ok ? '통과' : '문제 발견')); }
  catch (e) { const code = e && e.code; $('llm-out').innerHTML = '<div class="banner"><span class="ico">!</span><span>' + (code === 'not_granted' ? 'Claude 사용을 허용하지 않아 요청하지 않았습니다.' : code === 'rate_limited' ? '요청이 많습니다. 잠시 뒤 다시 시도하세요.' : code === 'cancelled' ? '요청을 중지했습니다.' : 'LLM 응답을 받지 못했습니다' + (code ? ' (' + esc(code) + ')' : '') + '.') + ' 규칙 기반 진단은 그대로 사용할 수 있습니다.</span></div>'; }
  S.llmBusy = false; renderLlm();
}

// ───────────── Report ─────────────
function currentReport() { return buildReport(S.result, { fileName: S.source.name, format: S.source.format, generatedAt: now(), settings: S.settings, issues: S.built.issues, reviews: S.reviews, log: S.log, cards: S.cards, summary: S.summary, llm: S.llm, isExample: S.source.isExample }); }
function renderReport() {
  if (needResult('report-preview')) return; const r = currentReport(); const d = r.summary.dashboard; let h = '';
  h += '<h2>' + esc(r.title) + '</h2><p class="note">파일 ' + esc(r.source.fileName) + (r.source.isExample ? ' (합성 예시 데이터)' : '') + ' · 엔진 v' + esc(r.engineVersion) + ' · 기준 묶음: ' + esc(r.settings.profile) + '</p><div class="banner plain"><span class="ico">i</span><span>' + esc(r.notice) + '</span></div>';
  h += '<h3>분석 요약</h3><ul class="plain">' + r.summary.lines.map(l => '<li>' + esc(l) + '</li>').join('') + '</ul>';
  h += '<h3>검량선</h3><div class="table-wrap"><table><thead><tr><th>배치</th><th>분석물</th><th>회귀식</th><th class="n">R²</th><th>범위</th><th>판정</th></tr></thead><tbody>' + r.calibrations.map(c => '<tr><td>' + esc(c.batchId) + '</td><td>' + esc(c.analyte) + '</td><td class="mono">' + esc(c.equation || '–') + '</td><td class="n">' + (isNum(c.r2) ? c.r2.toFixed(5) : '–') + '</td><td class="mono">' + (c.lloq != null ? n4(c.lloq) + '–' + n4(c.uloq) : '–') + '</td><td>' + pill(c.verdict === 'pass' ? 'pass' : c.verdict === 'fail' ? 'fail' : 'info', c.verdict === 'pass' ? '적합' : c.verdict === 'fail' ? '부적합' : '평가 불가') + '</td></tr>').join('') + '</tbody></table></div>';
  const nf = r.findings.filter(f => f.severity !== 'info');
  h += '<h3>QC 결과 <small class="note">기준 미충족 ' + d.fail + ' · 주의 ' + d.warn + '</small></h3>' + (nf.length ? '<div class="table-wrap"><table><thead><tr><th>판정</th><th>오류 유형</th><th>배치 / 분석물</th><th>관측값</th><th>검토</th></tr></thead><tbody>' + nf.map(f => '<tr><td>' + pill(f.severity) + '</td><td>' + esc(f.label) + '</td><td>' + esc(f.batchId) + ' / ' + esc(f.analyte) + '</td><td>' + esc(f.observed.length > 140 ? f.observed.slice(0, 140) + '…' : f.observed) + '</td><td>' + esc(f.review.statusLabel) + (f.review.note ? '<span class="sub">' + esc(f.review.note) + '</span>' : '') + '</td></tr>').join('') + '</tbody></table></div>' : '<p class="note">경고 항목 없음</p>');
  h += '<h3>검토 기록 <small class="note">' + r.reviewLog.length + '건</small></h3><div class="table-wrap"><table><thead><tr><th>시각</th><th>작업</th><th>대상</th><th>내용</th></tr></thead><tbody>' + r.reviewLog.map(l => '<tr><td class="mono">' + esc(l.time) + '</td><td>' + esc(l.action) + '</td><td class="mono">' + esc(l.target) + '</td><td>' + esc(l.note) + '</td></tr>').join('') + '</tbody></table></div>';
  h += '<p class="note">내보낸 HTML 보고서에는 이상 원인 진단(가설), 검토 필요 시료, 적용한 QC 기준 전체가 함께 들어갑니다.</p>';
  $('report-preview').innerHTML = h; $('print-btn').hidden = caps.framed;
  renderEln();
}
function renderEln() {
  const r = S.result; if (!r.batches.includes(S.elnBatch)) S.elnBatch = r.batches[0];
  $('eln-batch').innerHTML = r.batches.map(b => opt(b, b, S.elnBatch)).join('');
  const ex = elnExport(r, S.elnBatch); const part = (name, p) => '<tr><td><b>' + name + '</b><span class="sub mono">' + ELN_CONTRACT[name].kind + ' · ' + ELN_CONTRACT[name].columns.join(', ') + '</span></td><td class="n">' + (p.rows.length - 1) + '</td><td>' + (p.skipped.length ? p.skipped.length + '행 제외<span class="sub">' + esc(Array.from(new Set(p.skipped.map(s => s.reason))).join(' / ')) + '</span>' : '없음') + '</td></tr>';
  $('eln-summary').innerHTML = '<div class="table-wrap"><table><thead><tr><th>데이터셋</th><th class="n">옮길 행</th><th>옮기지 않는 행</th></tr></thead><tbody>' + part('calibration', ex.calibration) + part('recovery', ex.recovery) + '</tbody></table></div><ul class="plain note" style="margin-top:8px">' + ex.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul>';
}
async function saveFile(filename, text) {
  const msg = $('export-msg');
  if (caps.framed) {
    if (!caps.downloads) { msg.textContent = caps.ready ? '이 보기에서는 파일 저장을 쓸 수 없습니다. 페이지를 다시 열거나 로컬 파일(dist/index.html)에서 내보내세요.' : '저장 기능을 확인하는 중입니다. 잠시 뒤 다시 누르세요.'; return; }
    try { await caps.downloads.save({ filename, data: text }); msg.textContent = filename + ' 저장을 요청했습니다.'; addLog('내보내기', filename, ''); }
    catch (e) { msg.textContent = e && e.code === 'declined' ? '저장을 취소했습니다.' : '저장하지 못했습니다' + (e && e.code ? ' (' + e.code + ')' : '') + '.'; }
    return;
  }
  const blob = new Blob([text], { type: 'application/octet-stream' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  msg.textContent = filename + ' 파일을 저장했습니다.'; addLog('내보내기', filename, '');
}
function doExport(kind) {
  if (!S.result) return; const stamp = now().replace(/[-: ]/g, '').slice(0, 12); const r = currentReport();
  if (kind === 'html') saveFile('biopilot_report_' + stamp + '.html', reportHtml(r));
  else if (kind === 'json') saveFile('biopilot_report_' + stamp + '.json', JSON.stringify(r, null, 1));
  else if (kind === 'findings') saveFile('biopilot_qc_findings_' + stamp + '.csv', findingsCsv(r));
  else if (kind === 'quant') saveFile('biopilot_quant_results_' + stamp + '.csv', quantCsv(S.result));
  if (S.view === 'report') renderReport();
}

// ───────────── 이벤트 ─────────────
const RENDER = { dashboard: renderDashboard, import: renderImport, calibration: renderCalibration, qc: renderQc, assistant: renderAssistant, report: renderReport };
function render() { renderSource(); RENDER[S.view](); }
function show(view, push) {
  if (!VIEWS.includes(view)) view = 'dashboard'; S.view = view;
  for (const v of VIEWS) { $('view-' + v).hidden = v !== view; $('tab-' + v).setAttribute('aria-selected', String(v === view)); }
  if (push) { try { if (location.hash !== '#' + view) location.hash = view; } catch (e) { /* 해시를 쓸 수 없는 환경 */ } }
  render(); window.scrollTo(0, 0);
}
function goCell(v, view) { const [b, a] = v.split('||'); if (view === 'calibration') { S.cal.batch = b; S.cal.analyte = a; S.cal.exRow = null; } else { S.qc.batch = b; S.qc.analyte = a; S.qc.sev = ''; } show(view, true); }
function onClick(ev) {
  const el = ev.target.closest('[data-go],[data-cell],[data-tocal],[data-ex],[data-exok],[data-excancel],[data-restore],[data-export],[data-eln]'); if (!el) return; const ds = el.dataset;
  if (ds.go) return show(ds.go, true);
  if (ds.cell) return goCell(ds.cell, 'qc');
  if (ds.tocal) return goCell(ds.tocal, 'calibration');
  if (ds.export) return doExport(ds.export);
  if (ds.eln) { const ex = elnExport(S.result, S.elnBatch); const p = ex[ds.eln]; if (p.rows.length < 2) { $('export-msg').textContent = '이 배치에는 ' + ds.eln + ' 형식으로 옮길 수 있는 행이 없습니다.'; return; }
    return saveFile('biopilot_eln_' + S.elnBatch.replace(/[^A-Za-z0-9_-]+/g, '_') + '_' + ds.eln + '.csv', elnCsv(p)); }
  const key = groupKey(S.cal.batch, S.cal.analyte);
  if (ds.ex) { S.cal.exRow = Number(ds.ex); renderCalibration(); const inp = $('ex-reason'); if (inp) inp.focus(); return; }
  if (ds.excancel) { S.cal.exRow = null; return renderCalibration(); }
  if (ds.exok) { const reason = ($('ex-reason').value || '').trim(); if (!reason) { $('ex-reason').placeholder = '사유를 입력해야 제외할 수 있습니다'; $('ex-reason').focus(); return; }
    (S.settings.excluded[key] = S.settings.excluded[key] || {})[ds.exok] = reason; S.cal.exRow = null; return rerun('검량점 제외', key + ' 행 ' + ds.exok, reason); }
  if (ds.restore) { delete S.settings.excluded[key][ds.restore]; return rerun('검량점 제외 취소', key + ' 행 ' + ds.restore, ''); }
}
function onChange(ev) {
  const el = ev.target; const ds = el.dataset || {}; const id = el.id;
  if (ds.map) { S.mapping[ds.map] = Number(el.value); delete S.confidence[ds.map]; addLog('컬럼 매핑 변경', ds.map, el.value >= 0 ? S.table.headers[el.value] : '(없음)'); rebuild(true); return render(); }
  if (ds.const) { S.constants[ds.const] = el.value; addLog('고정값 입력', ds.const, el.value); rebuild(true); return render(); }
  if (ds.type !== undefined && id.startsWith('type-')) { if (el.value) S.typeMap[ds.type] = el.value; else delete S.typeMap[ds.type]; addLog('시료 유형 지정', ds.type, el.value ? TYPES[el.value] : '제외'); rebuild(true); return render(); }
  if (id === 'assume-dil') { S.assumeDilutionOne = el.checked; addLog('희석배수 누락 처리', '', el.checked ? '1로 간주' : '계산하지 않음'); rebuild(true); return render(); }
  if (id === 'sheet-select') { addLog('시트 변경', S.sheets[Number(el.value)].name, ''); try { setSheet(Number(el.value)); } catch (e) { $('import-error').innerHTML = '<div class="banner err"><span class="ico">✕</span><span>' + esc(e.message) + '</span></div>'; } return render(); }
  if (id === 'cal-batch') { S.cal.batch = el.value; S.cal.exRow = null; return renderCalibration(); }
  if (id === 'cal-analyte') { S.cal.analyte = el.value; S.cal.exRow = null; return renderCalibration(); }
  if (id === 'cal-log') { S.cal.log = el.checked; return renderCalibration(); }
  if (id === 'cal-method' || id === 'cal-weight') { const key = groupKey(S.cal.batch, S.cal.analyte); const o = S.settings.perGroup[key] = S.settings.perGroup[key] || {}; if (id === 'cal-method') o.method = el.value; else o.weighting = el.value; return rerun(id === 'cal-method' ? '정량 방식 변경' : '가중치 변경', key, el.options[el.selectedIndex].text); }
  if (id === 'qc-batch' || id === 'qc-analyte' || id === 'qc-sev') { S.qc[id.slice(3)] = el.value; return renderQc(); }
  if (id === 'as-batch' || id === 'as-analyte') { S.as[id.slice(3)] = el.value; return renderAssistant(); }
  if (id === 'as-only') { S.as.onlyHyp = el.checked; return renderAssistant(); }
  if (id === 'eln-batch') { S.elnBatch = el.value; return renderEln(); }
  if (ds.review) { const rv = S.reviews[ds.review] = S.reviews[ds.review] || { status: 'open', note: '' }; rv.status = el.value; rv.time = now(); return addLog('검토 상태 변경', ds.review, REVIEW_STATUS[el.value] + (rv.note ? ': ' + rv.note : '')); }
  if (ds.note) { const rv = S.reviews[ds.note] = S.reviews[ds.note] || { status: 'open', note: '' }; rv.note = el.value; rv.time = now(); return addLog('검토 메모', ds.note, el.value); }
  if (ds.rule) { const before = getRule(S.settings.rules, ds.rule); const res = setRule(S.settings.rules, ds.rule, el.type === 'checkbox' ? el.checked : el.value); const meta = RULE_META.find(m => m.path === ds.rule);
    if (res.error) { $('rules-msg').textContent = res.error + ' 기존 값을 유지합니다.'; if (el.type !== 'checkbox') el.value = before; return; }
    $('rules-msg').textContent = res.warning || ''; const open = $('rules-panel').open; rerun('QC 기준 변경', meta.label, String(before) + ' → ' + String(getRule(S.settings.rules, ds.rule))); $('rules-panel').open = open; return; }
}
function initCaps() {
  if (!caps.framed) { caps.ready = true; return; }
  Promise.all([window.claude.use('downloads').catch(() => null), window.claude.use('sample').catch(() => null)]).then(v => { caps.downloads = v[0]; caps.sample = v[1]; caps.ready = true; if (S.view === 'assistant') renderLlm(); });
}
function start() {
  $('ft-version').textContent = ENGINE_VERSION;
  $('demo-select').innerHTML = opt('all', '전체 9개 배치 (정상 1 + 오류 8)', 'all') + SCENARIOS.map(s => opt(s.id, s.id + ' · ' + s.name, '')).join('');
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => show(t.dataset.view, true)));
  document.addEventListener('click', onClick); document.addEventListener('change', onChange);
  $('demo-load').addEventListener('click', () => { $('import-error').innerHTML = ''; loadDemo($('demo-select').value); show('dashboard', true); });
  $('file-input').addEventListener('change', ev => { const f = ev.target.files && ev.target.files[0]; if (f) handleFile(f); ev.target.value = ''; });
  const drop = $('drop'); ['dragenter', 'dragover'].forEach(n => drop.addEventListener(n, ev => { ev.preventDefault(); drop.classList.add('over'); })); ['dragleave', 'drop'].forEach(n => drop.addEventListener(n, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', ev => { const f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0]; if (f) handleFile(f); });
  $('rules-apply-profile').addEventListener('click', () => { const id = $('rules-profile').value; S.settings.rules = profileRules(id); const open = $('rules-panel').open; rerun('QC 기준 묶음 적용', PROFILES[id].name, ''); $('rules-panel').open = open; $('rules-msg').textContent = PROFILES[id].name + '을(를) 적용했습니다.'; });
  $('llm-run').addEventListener('click', runLlm); $('llm-stop').addEventListener('click', () => { if (llmCtl) llmCtl.abort(); });
  $('memo-add').addEventListener('click', () => { const v = $('memo-text').value.trim(); if (!v) return; addLog('검토 메모', '', v); $('memo-text').value = ''; renderReport(); });
  $('print-btn').addEventListener('click', () => { addLog('인쇄', '', ''); window.print(); });
  window.addEventListener('hashchange', () => show((location.hash || '').replace('#', ''), false));
  loadDemo('all'); initCaps();
  show((location.hash || '').replace('#', '') || 'dashboard', false);
}
if (window.claude && window.claude.hot && window.claude.hot.ready) window.claude.hot.ready(start);
else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
