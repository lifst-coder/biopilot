// BIOPILOT — 보고서 생성. 구조화된 객체(JSON), 독립 실행 HTML(인쇄·PDF 저장용), CSV를 만든다.
import { isNum } from './stats.js';
import { toCsv, TYPES } from './parse.js';
import { RULE_META, PROFILES, ruleText } from './rules.js';

export const REVIEW_STATUS = { open: '미검토', confirmed: '확인함', action: '조치 필요', dismissed: '해당 없음' };
const SEV = { fail: '기준 미충족', warn: '주의', info: '참고' };
const n4 = v => isNum(v) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : Number(v.toPrecision(4)).toString()) : '';

// ctx: { fileName, format, generatedAt, settings, issues, reviews: {findingId: {status, note, time}}, log: [...], cards, summary, llm }
export function buildReport(result, ctx) {
  const rv = ctx.reviews || {};
  return {
    title: 'BIOPILOT LC-MS/MS 정량 데이터 품질 검증 보고서', generatedAt: ctx.generatedAt, engineVersion: result.engineVersion,
    source: { fileName: ctx.fileName || '', format: ctx.format || '', rows: result.dashboard.rows, isExample: !!ctx.isExample },
    notice: '허용 기준은 사용자가 설정한 값이며 기본값은 예시 기준이다. 원인 진단은 가설이며 확정된 원인이 아니다.',
    summary: { dashboard: result.dashboard, lines: ctx.summary || [] },
    settings: { profile: (PROFILES[ctx.settings.rules.profile] || { name: '사용자 정의' }).name, defaultMethod: ctx.settings.method, defaultWeighting: ctx.settings.weighting,
      rules: RULE_META.map(m => ({ path: m.path, group: m.group, label: m.label, value: ruleText(ctx.settings.rules, m.path), source: m.source })) },
    dataIssues: (ctx.issues || []).map(i => ({ severity: i.severity, code: i.code, message: i.message, rows: (i.rows || []).slice(0, 50) })),
    calibrations: result.groups.map(g => ({ batchId: g.batchId, analyte: g.analyte, method: g.method, weighting: g.weighting, verdict: g.cal.verdict, equation: g.cal.equation || null,
      slope: g.cal.fit ? g.cal.fit.slope : null, intercept: g.cal.fit ? g.cal.fit.intercept : null, r2: g.cal.fit ? g.cal.fit.r2 : null, lloq: g.cal.lloq || null, uloq: g.cal.uloq || null,
      criteria: g.cal.criteria, points: g.cal.points.map(p => ({ row: p.row, sampleId: p.sampleId, nominal: p.nominal, response: p.response, included: p.included, reason: p.reason, backCalc: p.backCalc, devPct: p.devPct, limit: p.limit, pass: p.pass })) })),
    findings: result.findings.map(f => ({ id: f.id, severity: f.severity, code: f.code, label: f.label, batchId: f.batchId, analyte: f.analyte, sampleIds: f.sampleIds, observed: f.observed, criterion: f.criterion, basis: f.basis,
      ruleSource: f.ruleKey ? (RULE_META.find(m => m.path === f.ruleKey) || {}).source || '' : '', review: rv[f.id] ? { status: rv[f.id].status, statusLabel: REVIEW_STATUS[rv[f.id].status], note: rv[f.id].note || '', time: rv[f.id].time } : { status: 'open', statusLabel: REVIEW_STATUS.open, note: '' } })),
    reviewSamples: result.review,
    diagnosis: (ctx.cards || []).map(c => ({ findingId: c.findingId, title: c.title, batchId: c.batchId, analyte: c.analyte, causeStatus: c.causeStatus, observations: c.observations, hypotheses: c.hypotheses.map(h => ({ cause: h.cause, standing: h.standingLabel, support: h.support, against: h.against, unknown: h.unknown })), checks: c.checks, verifications: c.verifications, conclusion: c.conclusion })),
    llm: ctx.llm ? { note: 'LLM이 생성한 해석. 계산값은 엔진 결과이며 LLM이 수정하지 않았다.', output: ctx.llm.data || null, raw: ctx.llm.data ? undefined : ctx.llm.raw, guard: ctx.llm.guard } : null,
    reviewLog: ctx.log || [],
  };
}

export function findingsCsv(report) {
  const rows = [['판정', '오류 코드', '오류 유형', '배치', '분석물', '대상 시료', '관측값', '기준', '계산 근거', '기준 출처(예시)', '검토 상태', '검토 메모']];
  for (const f of report.findings) rows.push([SEV[f.severity], f.code, f.label, f.batchId, f.analyte, f.sampleIds.join(' '), f.observed, f.criterion, f.basis, f.ruleSource, f.review.statusLabel, f.review.note]);
  return '﻿' + toCsv(rows);
}
export function quantCsv(result) {
  const rows = [['배치', '분석물', '시료 ID', '시료 유형', '반복', '명목 농도', '피크 면적', '내부표준 면적', '응답값', '장비 측정 농도', '희석배수', '최종 농도', '범위 표시', '검량선 판정']];
  for (const g of result.groups) for (const x of g.rows) rows.push([g.batchId, g.analyte, x.rec.sampleId, TYPES[x.rec.type] || x.rec.type, x.rec.replicate || '', x.rec.nominal == null ? '' : x.rec.nominal, x.rec.area == null ? '' : x.rec.area, x.rec.isArea == null ? '' : x.rec.isArea,
    isNum(x.q.response) ? Number(x.q.response.toPrecision(6)) : '', isNum(x.q.conc) ? Number(x.q.conc.toPrecision(5)) : '', x.rec.dilutionUsed == null ? '' : x.rec.dilutionUsed, isNum(x.q.final) ? Number(x.q.final.toPrecision(5)) : '',
    x.q.flag === 'BLQ' ? 'LLOQ 미만' : x.q.flag === 'ALQ' ? 'ULOQ 초과' : x.q.flag === 'NEG' ? '음수' : '', g.cal.verdict === 'pass' ? '적합' : g.cal.verdict === 'fail' ? '부적합(참고값)' : '평가 불가']);
  return '﻿' + toCsv(rows);
}

const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// 독립 실행 HTML. 브라우저에서 열어 인쇄하면 PDF로 저장할 수 있다.
export function reportHtml(r) {
  const d = r.summary.dashboard; let h = '';
  // 문서 뼈대 태그는 조각내어 적는다: 이 소스가 다른 HTML 안에 실릴 때 실제 태그로 오인되지 않게 하기 위해서다.
  h += '<!' + 'doctype html><' + 'html lang="ko"><' + 'head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(r.title) + '</title><style>' +
    'body{font-family:system-ui,"Malgun Gothic",sans-serif;font-size:12px;line-height:1.55;color:#14161f;margin:24px;max-width:1000px}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #999;padding-bottom:3px}h3{font-size:13px;margin:14px 0 4px}' +
    'table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid #bbb;padding:3px 6px;text-align:left;vertical-align:top}th{background:#eee}.n{text-align:right;font-variant-numeric:tabular-nums}.muted{color:#555}.box{border:1px solid #999;padding:8px 10px;margin:8px 0}' +
    '.fail{font-weight:700}.tag{display:inline-block;border:1px solid #666;padding:0 5px;font-size:11px}@media print{body{margin:10mm}h2{break-after:avoid}table{break-inside:auto}tr{break-inside:avoid}}</style></' + 'head><' + 'body>';
  h += '<h1>' + esc(r.title) + '</h1><div class="muted">생성 ' + esc(r.generatedAt) + ' · 엔진 v' + esc(r.engineVersion) + ' · 파일 ' + esc(r.source.fileName) + (r.source.isExample ? ' (합성 예시 데이터)' : '') + ' · ' + r.source.rows + '행</div>';
  h += '<div class="box">' + esc(r.notice) + '</div>';
  h += '<h2>1. 분석 요약</h2><table><tr><th>배치</th><th>분석물</th><th>기준 미충족</th><th>주의</th><th>검토 필요 시료</th></tr><tr><td class="n">' + d.batches + '</td><td class="n">' + d.analytes + '</td><td class="n">' + d.fail + '</td><td class="n">' + d.warn + '</td><td class="n">' + d.reviewSamples + '</td></tr></table>';
  h += r.summary.lines.map(l => '<div>' + esc(l) + '</div>').join('');
  h += '<h2>2. 검량선</h2><table><tr><th>배치</th><th>분석물</th><th>방식</th><th>가중치</th><th>회귀식</th><th>R²</th><th>범위</th><th>판정</th><th>충족하지 못한 기준</th></tr>';
  for (const c of r.calibrations) h += '<tr><td>' + esc(c.batchId) + '</td><td>' + esc(c.analyte) + '</td><td>' + (c.method === 'internal' ? '내부표준법' : '외부표준법') + '</td><td>' + esc(c.weighting) + '</td><td>' + esc(c.equation || '–') + '</td><td class="n">' + (isNum(c.r2) ? c.r2.toFixed(5) : '–') + '</td><td>' + (c.lloq != null ? n4(c.lloq) + '–' + n4(c.uloq) : '–') + '</td><td class="' + (c.verdict === 'pass' ? '' : 'fail') + '">' + (c.verdict === 'pass' ? '적합' : c.verdict === 'fail' ? '부적합' : '평가 불가') + '</td><td>' + esc(c.criteria.filter(x => !x.pass).map(x => x.label + ' ' + x.observed).join('; ')) + '</td></tr>';
  h += '</table><div class="muted">검량선 적합성은 검량점별 역산 정확도, 농도 수준 수, 범위 끝점으로 판정했다. R²는 참고값이다.</div>';
  h += '<h2>3. QC 결과</h2><table><tr><th>판정</th><th>오류 유형</th><th>배치 / 분석물</th><th>관측값</th><th>기준</th><th>검토</th></tr>';
  for (const f of r.findings.filter(x => x.severity !== 'info')) h += '<tr><td class="' + (f.severity === 'fail' ? 'fail' : '') + '">' + SEV[f.severity] + '</td><td>' + esc(f.label) + '</td><td>' + esc(f.batchId) + ' / ' + esc(f.analyte) + '</td><td>' + esc(f.observed) + '</td><td>' + esc(f.criterion) + '</td><td>' + esc(f.review.statusLabel) + (f.review.note ? ': ' + esc(f.review.note) : '') + '</td></tr>';
  h += '</table>';
  const infos = r.findings.filter(x => x.severity === 'info'); if (infos.length) h += '<h3>참고·평가 불가 항목</h3><ul>' + infos.map(f => '<li>' + esc(f.batchId + ' / ' + f.analyte + ' — ' + f.label + ': ' + f.observed) + '</li>').join('') + '</ul>';
  if (r.dataIssues.length) h += '<h3>입력 데이터의 문제</h3><ul>' + r.dataIssues.map(i => '<li>' + esc(i.message) + '</li>').join('') + '</ul>';
  h += '<h2>4. 검토가 필요한 시료</h2>' + (r.reviewSamples.length ? '<table><tr><th>배치</th><th>시료</th><th>사유</th></tr>' + r.reviewSamples.map(s => '<tr><td>' + esc(s.batchId) + '</td><td>' + esc(s.sampleId) + '</td><td>' + esc(s.reasons.map(x => x.analyte + ': ' + x.reason).join('; ')) + '</td></tr>').join('') + '</table>' : '<div>없음</div>');
  h += '<h2>5. 이상 원인 진단 (가설)</h2><div class="muted">아래는 관측 사실에 대한 가설이며 확정된 원인이 아니다.</div>';
  for (const c of r.diagnosis.filter(x => x.hypotheses.length)) {
    h += '<h3>' + esc(c.batchId + ' / ' + c.analyte + ' — ' + c.title) + ' <span class="tag">' + esc(c.causeStatus) + '</span></h3><div><b>관측 사실</b><ul>' + c.observations.map(o => '<li>' + esc(o) + '</li>').join('') + '</ul></div>';
    h += '<table><tr><th>가능한 원인(가설)</th><th>데이터 안의 근거</th><th>맞지 않는 점</th><th>판단할 수 없는 부분</th><th>상태</th></tr>' + c.hypotheses.map(x => '<tr><td>' + esc(x.cause) + '</td><td>' + esc(x.support.join(' ')) + '</td><td>' + esc(x.against.join(' ')) + '</td><td>' + esc(x.unknown) + '</td><td>' + esc(x.standing) + '</td></tr>').join('') + '</table>';
    h += '<div><b>추가 확인 항목</b>: ' + esc(c.checks.join(' · ')) + '</div><div><b>권장 검증</b>: ' + esc(c.verifications.join(' · ')) + '</div><div><b>결론</b>: ' + esc(c.conclusion) + '</div>';
  }
  if (r.llm && r.llm.output) { const o = r.llm.output; h += '<h2>6. LLM 해석 (참고)</h2><div class="box">' + esc(r.llm.note) + (r.llm.guard ? ' 수치 검사: ' + (r.llm.guard.unsupported.length ? '계산 결과에 없는 수치 ' + esc(r.llm.guard.unsupported.join(', ')) : '인용 수치 모두 계산 결과와 일치') + '.' : '') + '</div><div>' + esc(o.summary || '') + '</div>' + (o.cross_findings ? '<div>' + esc(o.cross_findings) + '</div>' : '') + (o.caveats ? '<div class="muted">' + esc(o.caveats) + '</div>' : ''); }
  h += '<h2>' + (r.llm && r.llm.output ? '7' : '6') + '. 검토 기록</h2>' + (r.reviewLog.length ? '<table><tr><th>시각</th><th>작업</th><th>대상</th><th>내용</th></tr>' + r.reviewLog.map(l => '<tr><td>' + esc(l.time) + '</td><td>' + esc(l.action) + '</td><td>' + esc(l.target || '') + '</td><td>' + esc(l.note || '') + '</td></tr>').join('') + '</table>' : '<div>기록 없음</div>');
  h += '<h2>부록. 적용한 QC 기준 (' + esc(r.settings.profile) + ')</h2><table><tr><th>구분</th><th>항목</th><th>값</th><th>출처·비고</th></tr>' + r.settings.rules.map(x => '<tr><td>' + esc(x.group) + '</td><td>' + esc(x.label) + '</td><td>' + esc(x.value) + '</td><td>' + esc(x.source) + '</td></tr>').join('') + '</table>';
  return h + '</' + 'body></' + 'html>';
}
