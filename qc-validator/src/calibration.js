// BIOPILOT — 검량선 엔진. 한 배치·한 분석물의 검량 표준으로 가중 선형 회귀를 하고, 적합성을 R²가 아니라
// 검량점별 역산 정확도·수준 수·범위 끝점으로 판정한다. 곡률·이상점·설정 오류는 별도의 진단으로 보고한다.
import { isNum, lte, mean, wls, weights, studentized, curvatureTest, tTwoSidedP, WEIGHTINGS, WEIGHTING_LABEL } from './stats.js';

export const OUTLIER_ALPHA = 0.05;   // 본페로니 보정 후 유의수준(이상점 후보 판단)

// 응답값: 내부표준법 = 분석물 면적 / 내부표준 면적, 외부표준법 = 분석물 면적
export function responseOf(rec, method) {
  if (!isNum(rec.area) || rec.area < 0) return null;
  if (method === 'internal') return (isNum(rec.isArea) && rec.isArea > 0) ? rec.area / rec.isArea : null;
  return rec.area;
}
export function fmtNum(v, d) { return isNum(v) ? (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(3) : v.toFixed(d === undefined ? 3 : d)) : '–'; }
export function fmtSig(v, n) { return isNum(v) ? Number(v.toPrecision(n || 4)).toString() : '–'; }
const sig = fmtSig;

function fitPoints(pts, scheme) {
  const x = pts.map(p => p.nominal), y = pts.map(p => p.response);
  const ww = weights(x, y, scheme); if (ww.error) return { error: ww.error };
  const fit = wls(x, y, ww.w); if (fit.error) return { error: fit.error };
  return { fit, w: ww.w, x, y };
}
function evaluatePoints(pts, fit, rules, lloq) {
  let nPass = 0, sumAbs = 0, maxAbs = 0;
  const rows = pts.map(p => {
    const back = (p.response - fit.intercept) / fit.slope; const dev = (back - p.nominal) / p.nominal * 100;
    const limit = p.nominal <= lloq * (1 + 1e-9) ? rules.cal.devPctLloq : rules.cal.devPct; const pass = lte(Math.abs(dev), limit);
    if (pass) nPass++; sumAbs += Math.abs(dev); if (Math.abs(dev) > maxAbs) maxAbs = Math.abs(dev);
    return { back, dev, limit, pass };
  });
  return { rows, nPass, sumAbs, maxAbs };
}
function levelSummary(pts, evals) {
  const m = new Map();
  pts.forEach((p, i) => { const k = p.nominal; if (!m.has(k)) m.set(k, { nominal: k, n: 0, nPass: 0 }); const o = m.get(k); o.n++; if (evals.rows[i].pass) o.nPass++; });
  const levels = Array.from(m.values()).sort((a, b) => a.nominal - b.nominal);
  for (const l of levels) l.pass = l.nPass / l.n >= 0.5;   // 한 수준의 반복 중 절반 이상이 기준 내이면 그 수준은 적합
  return levels;
}

// recs: 한 배치·한 분석물의 전체 레코드. opts: { method, weighting, rules, excluded: {행번호: 사유} }
export function buildCalibration(recs, opts) {
  const method = opts.method === 'external' ? 'external' : 'internal'; const weighting = WEIGHTINGS.includes(opts.weighting) ? opts.weighting : '1/x2';
  const rules = opts.rules; const excluded = opts.excluded || {}; const config = []; const findings = [];
  const out = { ok: false, method, weighting, points: [], levels: [], criteria: [], verdict: 'not_evaluable', diagnostics: { configIssues: config, outliers: [], curvature: null, weightingComparison: [] }, findings };
  const addConfig = (code, severity, message) => config.push({ code, severity, message });
  if (!WEIGHTINGS.includes(opts.weighting) && opts.weighting !== undefined) addConfig('CAL_CONFIG_WEIGHTING', 'fail', '알 수 없는 가중치 "' + opts.weighting + '"가 지정되어 1/x²로 계산했습니다.');

  const std = recs.filter(r => r.type === 'STD').sort((a, b) => a.order - b.order);
  if (!std.length) { out.error = '검량 표준이 없습니다.'; addConfig('CAL_NO_STANDARDS', 'fail', '이 배치·분석물에는 시료 유형이 검량 표준인 행이 없어 검량선을 만들 수 없습니다.'); return finalize(out, rules); }

  // 점 구성과 제외 사유
  let isMissing = 0;
  for (const r of std) {
    const p = { row: r.row, sampleId: r.sampleId, level: r.level, nominal: r.nominal, area: r.area, isArea: r.isArea, rt: r.rt, order: r.order, response: responseOf(r, method), included: true, excludedBy: null, reason: null };
    if (!isNum(r.nominal)) { p.included = false; p.excludedBy = 'invalid'; p.reason = '명목 농도 없음'; }
    else if (r.nominal < 0) { p.included = false; p.excludedBy = 'invalid'; p.reason = '명목 농도가 음수'; }
    else if (r.nominal === 0) { p.included = false; p.excludedBy = 'invalid'; p.reason = '명목 농도 0 (회귀에서 제외)'; }
    else if (!isNum(r.area) || r.area < 0) { p.included = false; p.excludedBy = 'invalid'; p.reason = '피크 면적 없음 또는 음수'; }
    else if (p.response == null) { p.included = false; p.excludedBy = 'invalid'; p.reason = '내부표준 면적 없음 또는 0 이하'; isMissing++; }
    if (p.included && Object.prototype.hasOwnProperty.call(excluded, r.row)) { p.included = false; p.excludedBy = 'user'; p.reason = String(excluded[r.row] || '사유 미기재'); }
    out.points.push(p);
  }
  if (method === 'internal' && isMissing) addConfig('CAL_CONFIG_IS_MISSING', 'fail', '내부표준법을 선택했지만 검량 표준 ' + std.length + '개 중 ' + isMissing + '개에 유효한 내부표준 면적이 없습니다. 해당 점은 회귀에서 빠졌습니다.' + (isMissing === std.length ? ' 내부표준 면적 열 매핑을 확인하거나 외부표준법을 선택하세요.' : ''));
  // 수준 라벨과 명목 농도의 불일치
  const byLabel = new Map(), byNominal = new Map();
  for (const p of out.points) { if (p.level == null || !isNum(p.nominal)) continue; (byLabel.get(p.level) || byLabel.set(p.level, new Set()).get(p.level)).add(p.nominal); (byNominal.get(p.nominal) || byNominal.set(p.nominal, new Set()).get(p.nominal)).add(p.level); }
  for (const [lab, set] of byLabel) if (set.size > 1) addConfig('CAL_CONFIG_LEVEL_CONFLICT', 'warn', '농도 수준 "' + lab + '"에 서로 다른 명목 농도(' + Array.from(set).sort((a, b) => a - b).join(', ') + ')가 지정되어 있습니다. 표준 조제표를 확인하세요.');
  for (const [nom, set] of byNominal) if (set.size > 1) addConfig('CAL_CONFIG_LEVEL_CONFLICT', 'warn', '명목 농도 ' + nom + '에 서로 다른 수준 라벨(' + Array.from(set).join(', ') + ')이 붙어 있습니다.');

  const pts = out.points.filter(p => p.included);
  const distinct = Array.from(new Set(pts.map(p => p.nominal))).sort((a, b) => a - b);
  out.nLevels = distinct.length;
  if (pts.length < 3 || distinct.length < 2) { out.error = '회귀에 쓸 수 있는 검량점이 부족합니다(유효한 점 ' + pts.length + '개, 수준 ' + distinct.length + '개).'; addConfig('CAL_CONFIG_FEW_POINTS', 'fail', out.error); return finalize(out, rules); }
  const f = fitPoints(pts, weighting);
  if (f.error) { out.error = f.error; addConfig('CAL_CONFIG_WEIGHTING', 'fail', '선택한 가중치 ' + WEIGHTING_LABEL[weighting] + '를 적용할 수 없습니다: ' + f.error); return finalize(out, rules); }
  const fit = f.fit; out.ok = true; out.fit = { slope: fit.slope, intercept: fit.intercept, r2: fit.r2, n: fit.n, s: fit.s, seSlope: fit.seSlope, seIntercept: fit.seIntercept };
  out.lloq = distinct[0]; out.uloq = distinct[distinct.length - 1];
  const ev = evaluatePoints(pts, fit, rules, out.lloq); const st = studentized(fit, f.w);
  pts.forEach((p, i) => { p.fitted = fit.fitted[i]; p.residual = fit.residuals[i]; p.backCalc = ev.rows[i].back; p.devPct = ev.rows[i].dev; p.limit = ev.rows[i].limit; p.pass = ev.rows[i].pass; p.isLloq = p.nominal === out.lloq; p.isUloq = p.nominal === out.uloq; p.studentized = st[i]; });
  out.levels = levelSummary(pts, ev);
  out.lloqArea = mean(pts.filter(p => p.isLloq).map(p => p.area));
  out.equation = (method === 'internal' ? '면적비' : '면적') + ' = ' + sig(fit.slope, 5) + ' × 농도 ' + (fit.intercept >= 0 ? '+ ' : '− ') + sig(Math.abs(fit.intercept), 4);

  // ── 적합성 기준 ──
  const passLevels = out.levels.filter(l => l.pass).length; const passPct = ev.nPass / pts.length * 100;
  const crit = (id, label, pass, observed, limit, source) => out.criteria.push({ id, label, pass, observed, limit, source });
  crit('levels', '농도 수준 수', distinct.length >= rules.cal.minLevels, distinct.length + '개', '≥ ' + rules.cal.minLevels + '개', 'cal.minLevels');
  crit('pointsPass', '기준 내 검량점 비율', passPct >= rules.cal.minPassPct - 1e-9, ev.nPass + '/' + pts.length + ' (' + passPct.toFixed(0) + '%)', '≥ ' + rules.cal.minPassPct + '% (각 점 ±' + rules.cal.devPct + '%, 최저점 ±' + rules.cal.devPctLloq + '%)', 'cal.minPassPct');
  crit('levelsPass', '기준 내 농도 수준 수', passLevels >= Math.min(rules.cal.minLevels, distinct.length) && passLevels >= rules.cal.minLevels, passLevels + '개', '≥ ' + rules.cal.minLevels + '개', 'cal.minLevels');
  const lo = out.levels[0], hi = out.levels[out.levels.length - 1];
  crit('lloq', '최저 검량점(LLOQ) 정확도', lo.pass, lo.nPass + '/' + lo.n + ' 적합', '절반 이상 ±' + rules.cal.devPctLloq + '% 이내', 'cal.devPctLloq');
  crit('uloq', '최고 검량점(ULOQ) 정확도', hi.pass, hi.nPass + '/' + hi.n + ' 적합', '절반 이상 ±' + rules.cal.devPct + '% 이내', 'cal.devPct');
  crit('slope', '기울기 부호', fit.slope > 0, sig(fit.slope, 5), '> 0', null);
  if (rules.cal.useR2) crit('r2', '결정계수 R²', fit.r2 >= rules.cal.r2Min, fit.r2.toFixed(5), '≥ ' + rules.cal.r2Min, 'cal.r2Min');
  if (!(fit.slope > 0)) addConfig('CAL_CONFIG_NEG_SLOPE', 'fail', '기울기가 0 이하입니다(' + sig(fit.slope, 5) + '). 농도와 응답의 열 매핑이 뒤바뀌었거나 표준 순서가 잘못 입력되었을 수 있습니다.');

  // ── 진단 1: 이상점 후보 ──
  const n = pts.length; const cands = [];
  pts.forEach((p, i) => {
    if (p.pass) return;
    const pAdj = Math.min(1, tTwoSidedP(st[i], n - 3) * n);
    // 그 점을 빼고 다시 적합했을 때: 나머지가 모두 기준 내이고 그 점만 크게 벗어나는가
    let loo = null;
    if (n >= 5) { const rest = pts.filter((_, k) => k !== i); const g = fitPoints(rest, weighting);
      if (!g.error && new Set(rest.map(q => q.nominal)).size >= 2) { const lloq2 = Math.min.apply(null, rest.map(q => q.nominal)); const e2 = evaluatePoints(rest, g.fit, rules, lloq2); const back = (p.response - g.fit.intercept) / g.fit.slope; loo = { restAllPass: e2.nPass === rest.length, devPct: (back - p.nominal) / p.nominal * 100 }; } }
    const byTest = pAdj < OUTLIER_ALPHA, byLoo = !!(loo && loo.restAllPass && Math.abs(loo.devPct) > 2 * p.limit);
    if (byTest || byLoo) cands.push({ index: i, row: p.row, sampleId: p.sampleId, nominal: p.nominal, devPct: p.devPct, studentized: st[i], pAdj, looDevPct: loo ? loo.devPct : null, restAllPass: loo ? loo.restAllPass : null, basis: byTest && byLoo ? '스튜던트화 잔차 + 제외 후 재적합' : (byTest ? '스튜던트화 잔차' : '제외 후 재적합') });
  });
  cands.sort((a, b) => Math.abs(b.devPct) - Math.abs(a.devPct));

  // ── 진단 2: 곡률(2차 항 F 검정 + 크기) ──
  const curvOf = (subset) => { if (subset.length < 5 || new Set(subset.map(q => q.nominal)).size < 4) return null; const g = fitPoints(subset, weighting); if (g.error) return null; const c = curvatureTest(g.x, g.y, g.w); if (c.error) return null;
    // 곡률이 통계적으로 유의하고(p), 크기가 충분하며(curvaturePct), 실제로 역산 정확도에 영향을 줄 때만 경고한다(최대 편차가 허용 편차의 2/3 이상).
    const maxRel = Math.max.apply(null, subset.map(q => Math.abs(q.devPct) / q.limit));
    return { p: c.p, F: c.F, curvaturePct: c.curvaturePct, maxDevOverLimit: maxRel, flagged: c.p < rules.cal.alpha && Math.abs(c.curvaturePct) >= rules.cal.curvatureMinPct && maxRel >= 2 / 3, n: subset.length }; };
  const curvAll = curvOf(pts); const top = cands.slice(0, 1); const curvRest = top.length ? curvOf(pts.filter((_, k) => k !== top[0].index)) : curvAll;
  let nonlinear = false, outliers = [];
  // 이상점 후보가 범위의 끝점(최저·최고 수준)이고 전체 곡률이 유의하면 비선형으로 본다: 끝점 하나만 벗어난 경우는 포화와 단일 이상점을 이 데이터로 구별할 수 없다.
  const topAtEnd = top.length && (pts[top[0].index].nominal === out.uloq || pts[top[0].index].nominal === out.lloq);
  if (top.length) { if ((curvRest && curvRest.flagged) || (topAtEnd && curvAll && curvAll.flagged)) nonlinear = true; else outliers = cands.slice(0, Math.max(1, Math.min(2, cands.length))); }
  else if (curvAll && curvAll.flagged) nonlinear = true;
  out.diagnostics.endPointAmbiguity = !!topAtEnd;
  out.diagnostics.curvature = curvAll ? Object.assign({}, curvAll, { flagged: nonlinear, withoutCandidate: top.length ? curvRest : null }) : null;
  out.diagnostics.outliers = outliers;

  // ── 진단 3: 가중치 비교(선택한 가중치가 저농도 정확도를 해치는지) ──
  for (const scheme of WEIGHTINGS) {
    const g = fitPoints(pts, scheme); if (g.error) { out.diagnostics.weightingComparison.push({ scheme, error: g.error }); continue; }
    const e = evaluatePoints(pts, g.fit, rules, out.lloq);
    out.diagnostics.weightingComparison.push({ scheme, sumAbsRE: e.sumAbs, maxAbsRE: e.maxAbs, nPass: e.nPass, n: pts.length, r2: g.fit.r2, allPass: e.nPass === pts.length, selected: scheme === weighting });
  }
  const sel = out.diagnostics.weightingComparison.find(wc => wc.selected); const better = out.diagnostics.weightingComparison.filter(wc => !wc.error && !wc.selected && wc.allPass).sort((a, b) => a.sumAbsRE - b.sumAbsRE)[0];
  if (sel && !sel.allPass && better && !nonlinear && !outliers.length && sel.sumAbsRE > 2 * better.sumAbsRE)
    addConfig('CAL_CONFIG_WEIGHTING', 'warn', '선택한 가중치 ' + WEIGHTING_LABEL[weighting] + '에서는 ' + (sel.n - sel.nPass) + '개 점이 기준을 벗어나지만(|편차| 합 ' + sel.sumAbsRE.toFixed(1) + '%), ' + WEIGHTING_LABEL[better.scheme] + '에서는 모든 점이 기준 내입니다(합 ' + better.sumAbsRE.toFixed(1) + '%). 가중치는 분석법 밸리데이션에서 정한 것을 써야 하므로, 설정이 분석법과 같은지 확인하세요.');
  // 외부표준법인데 내부표준이 변동을 크게 줄이는 경우(참고)
  if (method === 'external' && pts.every(p => isNum(p.isArea) && p.isArea > 0)) {
    const alt = fitPoints(pts.map(p => Object.assign({}, p, { response: p.area / p.isArea })), weighting);
    if (!alt.error) { const e = evaluatePoints(pts.map(p => Object.assign({}, p, { response: p.area / p.isArea })), alt.fit, rules, out.lloq);
      if (sel && e.sumAbs < 0.5 * sel.sumAbsRE && sel.maxAbsRE > rules.cal.devPct) addConfig('CAL_CONFIG_METHOD_HINT', 'info', '외부표준법으로 계산했습니다. 같은 데이터를 내부표준법으로 계산하면 역산 편차 합이 ' + sel.sumAbsRE.toFixed(1) + '% → ' + e.sumAbs.toFixed(1) + '%로 줄어듭니다. 분석법이 내부표준법이라면 설정을 확인하세요.'); }
  }
  out.nonlinear = nonlinear;
  return finalize(out, rules);
}

function finalize(out, rules) {
  const F = out.findings; const pts = out.points.filter(p => p.included);
  const add = (code, severity, observed, criterion, ruleKey, basis, rows, details) => F.push({ code, severity, observed, criterion, ruleKey, basis, rows: rows || [], details: details || {} });
  for (const c of out.diagnostics.configIssues) add(c.code, c.severity, c.message, '검량선 설정 점검', null, '설정과 데이터의 일관성 검사', out.points.map(p => p.row), {});
  if (!out.ok) { out.verdict = 'not_evaluable'; return out; }
  const failed = out.criteria.filter(c => !c.pass);
  out.verdict = failed.length ? 'fail' : 'pass';
  const bad = pts.filter(p => !p.pass);
  if (failed.length) add('CAL_FAIL', 'fail', '충족하지 못한 기준: ' + failed.map(c => c.label + ' ' + c.observed + ' (기준 ' + c.limit + ')').join('; '), '검량선 적합성 기준 전체', 'cal.minPassPct', '검량점별 역산 정확도·수준 수·범위 끝점으로 판정(R² 단독 판정 아님)', pts.map(p => p.row), { failed: failed.map(c => c.id) });
  if (bad.length) add('CAL_POINT_DEV', failed.length ? 'fail' : 'warn', bad.map(p => p.nominal + ': ' + (p.devPct >= 0 ? '+' : '') + p.devPct.toFixed(1) + '%').join(', '), '±' + rules.cal.devPct + '% (최저점 ±' + rules.cal.devPctLloq + '%)', 'cal.devPct', '역산 농도 = (응답 − 절편) / 기울기, 편차 = (역산 − 명목) / 명목 × 100', bad.map(p => p.row), { items: bad.map(p => ({ row: p.row, sampleId: p.sampleId, nominal: p.nominal, devPct: p.devPct, limit: p.limit })) });
  const cv = out.diagnostics.curvature;
  if (out.nonlinear && cv) add('CAL_NONLINEAR', out.verdict === 'fail' ? 'fail' : 'warn', '2차 항 F 검정 p = ' + cv.p.toExponential(2) + ', 최고 농도에서 2차 항 / 1차 항 = ' + cv.curvaturePct.toFixed(1) + '% (' + (cv.curvaturePct < 0 ? '고농도에서 응답이 직선보다 낮음' : '고농도에서 응답이 직선보다 높음') + ')', 'p < ' + rules.cal.alpha + ' 이고 |곡률| ≥ ' + rules.cal.curvatureMinPct + '%', 'cal.curvatureMinPct', '같은 가중치로 직선과 2차식을 적합해 잔차제곱합을 비교', pts.map(p => p.row), { p: cv.p, curvaturePct: cv.curvaturePct, devByLevel: pts.map(p => ({ nominal: p.nominal, devPct: p.devPct, isArea: p.isArea, area: p.area })) });
  for (const o of out.diagnostics.outliers) add('CAL_OUTLIER', out.verdict === 'fail' ? 'fail' : 'warn', '명목 ' + o.nominal + ' (' + o.sampleId + '): 편차 ' + (o.devPct >= 0 ? '+' : '') + o.devPct.toFixed(1) + '%, 스튜던트화 잔차 ' + (isNum(o.studentized) ? o.studentized.toFixed(1) : '∞') + (o.looDevPct != null ? ', 이 점을 빼고 적합하면 편차 ' + (o.looDevPct >= 0 ? '+' : '') + o.looDevPct.toFixed(1) + '%' + (o.restAllPass ? '이고 나머지 점은 모두 기준 내' : '') : ''), '보정 p < ' + OUTLIER_ALPHA + ' 또는 제외 후 편차 > 허용 편차의 2배', null, o.basis, [o.row], { nominal: o.nominal, devPct: o.devPct, looDevPct: o.looDevPct, restAllPass: o.restAllPass, point: pts.find(p => p.row === o.row) });
  const userEx = out.points.filter(p => p.excludedBy === 'user');
  if (userEx.length) add('CAL_POINT_EXCLUDED', 'info', '사용자가 제외한 검량점 ' + userEx.length + '개: ' + userEx.map(p => p.nominal + ' (' + p.reason + ')').join(', '), '제외 사유 기록', null, '사용자 조작(검토 기록에 남음)', userEx.map(p => p.row), {});
  return out;
}

// 검량선으로 한 행을 정량한다. 반환: { response, conc(장비 측정 농도), final(희석 반영), flag }
export function quantify(cal, rec) {
  const response = responseOf(rec, cal.method);
  if (!cal.ok || response == null) return { response, conc: null, final: null, flag: response == null ? 'NO_RESPONSE' : 'NO_CAL' };
  const conc = (response - cal.fit.intercept) / cal.fit.slope;
  let flag = null; if (conc < 0) flag = 'NEG'; else if (conc < cal.lloq) flag = 'BLQ'; else if (conc > cal.uloq) flag = 'ALQ';
  const final = isNum(rec.dilutionUsed) ? conc * rec.dilutionUsed : null;
  return { response, conc, final, flag };
}
