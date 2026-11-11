// BIOPILOT — QC 검증 엔진. 한 배치·한 분석물 단위로 설정된 규칙을 적용한다. 계산할 수 없는 항목은 "평가 불가"로 보고하고 값을 지어내지 않는다.
import { isNum, lte, gte, mean, sd, rsd, relError, rpd, trend } from './stats.js';

export const CODES = {
  CAL_FAIL: '검량선 부적합', CAL_POINT_DEV: '검량점 역산 편차 초과', CAL_NONLINEAR: '검량선 비선형성', CAL_OUTLIER: '검량점 이상치 후보', CAL_POINT_EXCLUDED: '검량점 사용자 제외',
  CAL_NO_STANDARDS: '검량 표준 없음', CAL_CONFIG_IS_MISSING: '설정 오류: 내부표준 면적 없음', CAL_CONFIG_WEIGHTING: '설정 확인: 가중치', CAL_CONFIG_LEVEL_CONFLICT: '설정 확인: 농도 수준 불일치',
  CAL_CONFIG_FEW_POINTS: '설정 오류: 검량점 부족', CAL_CONFIG_NEG_SLOPE: '설정 오류: 기울기 음수', CAL_CONFIG_METHOD_HINT: '설정 참고: 정량 방식',
  MB_CONTAM: '방법 바탕 오염 신호', CB_CONTAM: '검량 바탕 오염 신호',
  QC_ACCURACY: 'QC 정확도 초과', QC_BATCH_FAIL: 'QC 배치 기준 미달', QC_PRECISION: 'QC 반복 정밀도 초과',
  DUP_RPD: '중복 시료 편차 초과', REP_RSD: '반복 측정 변동 초과', DUP_NO_PARENT: '중복 시료 짝 없음',
  SPIKE_LOW: '첨가 회수율 낮음', SPIKE_HIGH: '첨가 회수율 높음',
  IS_RESPONSE: '내부표준 응답 이상', IS_DRIFT: '내부표준 응답 표류', RT_SHIFT: '머무름 시간 이동',
  QC_MISSING: '필수 QC 누락', SAMPLE_ABOVE_RANGE: '시료가 검량 범위 초과', SAMPLE_BELOW_RANGE: '시료가 정량한계 미만',
  NOT_EVALUATED: '평가 불가',
};

const pct = (v, d) => isNum(v) ? v.toFixed(d === undefined ? 1 : d) + '%' : '–';
const sgn = (v, d) => isNum(v) ? (v >= 0 ? '+' : '') + v.toFixed(d === undefined ? 1 : d) : '–';
const num = (v) => isNum(v) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : Number(v.toPrecision(4)).toString()) : '–';
const stripSuffix = (id, re) => String(id).replace(re, '');
const DUP_SUFFIX = /[\s_-]*(dup|duplicate|d|msd|중복)\s*\d*$/i, SPIKE_SUFFIX = /[\s_-]*(ms|msd|spike|spk|sp|첨가)\s*\d*$/i;

// rows: [{ rec, q: {response, conc, final, flag} }] 주입 순서로 정렬. cal: buildCalibration 결과.
export function runQc(rows, cal, rules, meta) {
  const F = []; const T = { blanks: [], qcItems: [], qcLevels: [], dups: [], reps: [], spikes: [], isItems: [], rtItems: [], missing: [] };
  const add = (code, severity, observed, criterion, ruleKey, basis, items, details) => F.push({ code, severity, observed, criterion, ruleKey, basis, rows: (items || []).map(i => i.row), sampleIds: Array.from(new Set((items || []).map(i => i.sampleId))), details: Object.assign({ items: items || [] }, details || {}) });
  const notEval = (what, why) => F.push({ code: 'NOT_EVALUATED', severity: 'info', observed: what + ': ' + why, criterion: '–', ruleKey: null, basis: '필요한 데이터가 없어 계산하지 않음', rows: [], sampleIds: [], details: { what, why, items: [] } });
  const of = t => rows.filter(x => x.rec.type === t);
  const measured = x => isNum(x.q.final) ? x.q.final : null;     // 희석배수가 없으면 최종 농도는 null (임의로 1을 넣지 않는다)
  const calOk = cal && cal.ok;

  // ── 1. 바탕 시료 ──
  for (const [type, code, name] of [['METHOD_BLANK', 'MB_CONTAM', '방법 바탕'], ['CAL_BLANK', 'CB_CONTAM', '검량 바탕']]) {
    const bl = of(type); if (!bl.length) continue;
    if (!calOk) { notEval(name + ' 평가', '검량선이 없어 LLOQ 기준을 정할 수 없습니다.'); continue; }
    const bad = [];
    for (const x of bl) {
      const prev = rows.filter(y => y.rec.order < x.rec.order).slice(-1)[0];
      const item = { row: x.rec.row, sampleId: x.rec.sampleId, type, area: x.rec.area, conc: x.q.conc, pctOfLloq: isNum(x.rec.area) && cal.lloqArea > 0 ? x.rec.area / cal.lloqArea * 100 : null,
        prev: prev ? { sampleId: prev.rec.sampleId, type: prev.rec.type, nominal: prev.rec.nominal, area: prev.rec.area, conc: prev.q.conc, aboveHalfUloq: isNum(prev.q.conc) && prev.q.conc > 0.5 * cal.uloq } : null };
      if (rules.blank.mode === 'conc') {
        const c = measured(x); item.limit = rules.blank.maxFractionOfLloqConc * cal.lloq;
        if (c == null) { item.status = 'not_evaluated'; item.note = x.q.conc == null ? '응답 없음' : '희석배수 없음'; }
        else { item.value = c; item.pass = c < item.limit; }
      } else {
        item.limit = rules.blank.maxPctOfLloqResponse;
        if (item.pctOfLloq == null) { item.status = 'not_evaluated'; item.note = '피크 면적 없음'; }
        else { item.value = item.pctOfLloq; item.pass = lte(item.pctOfLloq, item.limit); }
      }
      T.blanks.push(item); if (item.pass === false) bad.push(item);
    }
    const ne = T.blanks.filter(i => i.type === type && i.status === 'not_evaluated'); if (ne.length) notEval(name + ' ' + ne.length + '개', ne[0].note);
    if (bad.length) add(code, 'fail', bad.map(i => i.sampleId + ': ' + (rules.blank.mode === 'conc' ? '농도 ' + num(i.value) : 'LLOQ 응답의 ' + pct(i.value))).join(', '),
      rules.blank.mode === 'conc' ? 'LLOQ(' + num(cal.lloq) + ')의 ' + rules.blank.maxFractionOfLloqConc + '배 미만' : 'LLOQ 표준 평균 면적(' + num(cal.lloqArea) + ')의 ' + rules.blank.maxPctOfLloqResponse + '% 이하',
      rules.blank.mode === 'conc' ? 'blank.maxFractionOfLloqConc' : 'blank.maxPctOfLloqResponse', rules.blank.mode === 'conc' ? '바탕 시료의 계산 농도와 LLOQ 농도 비교' : '바탕 시료의 분석물 면적 / LLOQ 표준의 평균 분석물 면적 × 100', bad,
      { allBlanks: T.blanks.filter(i => i.type === type), otherBlankType: T.blanks.filter(i => i.type !== type) });
  }

  // ── 2. QC 시료 ──
  const qcs = of('QC');
  if (qcs.length) {
    if (!calOk) notEval('QC 정확도', '검량선이 없어 농도를 계산할 수 없습니다.');
    else {
      const levels = new Map();
      for (const x of qcs) {
        const m = measured(x); const nominal = x.rec.nominal; const isLloq = isNum(nominal) && nominal <= cal.lloq * (1 + 1e-9);
        const limit = isLloq ? rules.qc.devPctLloq : rules.qc.devPct;
        const item = { row: x.rec.row, sampleId: x.rec.sampleId, nominal, measured: m, limit, order: x.rec.order, isPct: null };
        if (!isNum(nominal) || nominal <= 0) { item.status = 'not_evaluated'; item.note = '명목 농도 없음'; }
        else if (m == null) { item.status = 'not_evaluated'; item.note = x.q.conc == null ? '응답 없음' : '희석배수 없음'; }
        else { item.rePct = relError(m, nominal); item.pass = lte(Math.abs(item.rePct), limit); }
        T.qcItems.push(item);
        if (isNum(nominal) && nominal > 0) { if (!levels.has(nominal)) levels.set(nominal, []); levels.get(nominal).push(item); }
      }
      const ne = T.qcItems.filter(i => i.status === 'not_evaluated'); if (ne.length) notEval('QC ' + ne.length + '개', ne.map(i => i.sampleId + '(' + i.note + ')').join(', '));
      const evald = T.qcItems.filter(i => i.pass !== undefined); const bad = evald.filter(i => !i.pass);
      let levelFail = [];
      for (const [nominal, items] of Array.from(levels).sort((a, b) => a[0] - b[0])) {
        const ok = items.filter(i => i.pass !== undefined); const vals = ok.map(i => i.measured); const nPass = ok.filter(i => i.pass).length;
        const lv = { nominal, n: ok.length, mean: mean(vals), sd: sd(vals), rsd: rsd(vals), meanRePct: ok.length ? relError(mean(vals), nominal) : NaN, nPass, passPct: ok.length ? nPass / ok.length * 100 : NaN,
          rsdLimit: nominal <= cal.lloq * (1 + 1e-9) ? Math.max(rules.qc.rsdPct, rules.qc.devPctLloq) : rules.qc.rsdPct };
        T.qcLevels.push(lv);
        if (ok.length && lv.passPct < rules.qc.minPassPctLevel - 1e-9) levelFail.push(lv);
        if (ok.length >= 2 && isNum(lv.rsd) && !lte(lv.rsd, lv.rsdLimit)) add('QC_PRECISION', 'fail', 'QC ' + num(nominal) + ': RSD ' + pct(lv.rsd) + ' (n = ' + ok.length + ', 평균 ' + num(lv.mean) + ', SD ' + num(lv.sd) + ')', 'RSD ≤ ' + lv.rsdLimit + '%', 'qc.rsdPct', 'RSD = 표준편차(n−1) / 평균 × 100', ok, { level: lv });
      }
      if (bad.length) add('QC_ACCURACY', 'fail', bad.map(i => i.sampleId + ' (명목 ' + num(i.nominal) + '): ' + sgn(i.rePct) + '%').join(', '), '상대오차 ±' + rules.qc.devPct + '% (LLOQ 수준 ±' + rules.qc.devPctLloq + '%)', 'qc.devPct', '상대오차 = (측정 농도 − 명목 농도) / 명목 농도 × 100', bad, { all: evald });
      if (evald.length) {
        const overall = (evald.length - bad.length) / evald.length * 100;
        if (overall < rules.qc.minPassPctAll - 1e-9 || levelFail.length) add('QC_BATCH_FAIL', 'fail', '기준 내 QC ' + (evald.length - bad.length) + '/' + evald.length + ' (' + overall.toFixed(0) + '%)' + (levelFail.length ? '; 수준별 미달: ' + levelFail.map(l => num(l.nominal) + ' (' + l.nPass + '/' + l.n + ')').join(', ') : ''),
          '전체 ≥ ' + rules.qc.minPassPctAll + '%, 각 수준 ≥ ' + rules.qc.minPassPctLevel + '%', 'qc.minPassPctAll', '기준 내 QC 수 / 평가한 QC 수', evald, { overallPct: overall, levelFail });
      }
    }
  }

  // ── 3. 중복·반복 ──
  const samples = of('SAMPLE'), dupRows = of('DUP');
  if ((dupRows.length || samples.length) && !calOk) { if (dupRows.length) notEval('중복 시료', '검량선이 없어 농도를 계산할 수 없습니다.'); }
  else {
    const groups = new Map(); const keyOf = id => String(id).trim().toLowerCase();
    for (const x of samples) { const k = keyOf(x.rec.sampleId); if (!groups.has(k)) groups.set(k, { id: x.rec.sampleId, members: [] }); groups.get(k).members.push(x); }
    const orphans = [];
    for (const x of dupRows) {
      const cands = [x.rec.parentId, x.rec.sampleId, stripSuffix(x.rec.sampleId, DUP_SUFFIX)].filter(v => v != null && String(v).trim() !== '').map(keyOf);
      const k = cands.find(c => groups.has(c)); if (k) groups.get(k).members.push(x); else orphans.push({ row: x.rec.row, sampleId: x.rec.sampleId });
    }
    if (orphans.length) add('DUP_NO_PARENT', 'info', '짝이 되는 원시료를 찾지 못한 중복 시료: ' + orphans.map(o => o.sampleId).join(', '), '원시료 ID 열, 같은 Sample ID, 또는 "-DUP" 접미사로 연결', null, '시료 연결 규칙', orphans, {});
    const badDup = [], badRep = [];
    for (const g of groups.values()) {
      if (g.members.length < 2) continue;
      const vals = g.members.map(measured); const flags = g.members.map(x => x.q.flag);
      const item = { row: g.members[0].rec.row, rowsAll: g.members.map(x => x.rec.row), sampleId: g.id, n: g.members.length, values: vals, areas: g.members.map(x => x.rec.area), isAreas: g.members.map(x => x.rec.isArea), responses: g.members.map(x => x.q.response) };
      if (vals.some(v => v == null)) { item.status = 'not_evaluated'; item.note = '농도를 계산할 수 없는 측정 포함(응답 또는 희석배수 없음)'; }
      else if (flags.some(f => f === 'BLQ' || f === 'NEG')) { item.status = 'not_evaluated'; item.note = '정량한계 미만 측정 포함'; }
      else if (g.members.length === 2) { item.rpd = rpd(vals[0], vals[1]); item.limit = rules.dup.rpdPct; item.pass = lte(item.rpd, item.limit); item.kind = 'dup'; }
      else { item.rsd = rsd(vals); item.mean = mean(vals); item.sd = sd(vals); item.limit = rules.rep.rsdPct; item.pass = lte(item.rsd, item.limit); item.kind = 'rep'; }
      // 진단용: 원면적과 내부표준 보정 응답의 변동 비교
      if (g.members.every(x => isNum(x.rec.area))) item.areaRsd = rsd(g.members.map(x => x.rec.area));
      if (g.members.every(x => isNum(x.q.response))) item.responseRsd = rsd(g.members.map(x => x.q.response));
      (item.n === 2 ? T.dups : T.reps).push(item);
      if (item.pass === false) (item.kind === 'dup' ? badDup : badRep).push(item);
    }
    const ne = T.dups.concat(T.reps).filter(i => i.status === 'not_evaluated'); if (ne.length) notEval('중복·반복 ' + ne.length + '건', ne.map(i => i.sampleId + '(' + i.note + ')').join(', '));
    if (badDup.length) add('DUP_RPD', 'fail', badDup.map(i => i.sampleId + ': RPD ' + pct(i.rpd) + ' (' + i.values.map(num).join(' / ') + ')').join(', '), 'RPD ≤ ' + rules.dup.rpdPct + '%', 'dup.rpdPct', 'RPD = |a − b| / ((a + b)/2) × 100', badDup, { all: T.dups });
    if (badRep.length) add('REP_RSD', 'fail', badRep.map(i => i.sampleId + ': RSD ' + pct(i.rsd) + ' (n = ' + i.n + ')').join(', '), 'RSD ≤ ' + rules.rep.rsdPct + '%', 'rep.rsdPct', 'RSD = 표준편차(n−1) / 평균 × 100', badRep, { all: T.reps });
  }

  // ── 4. 첨가 회수율 ──
  const spikes = of('SPIKE');
  if (spikes.length) {
    if (!calOk) notEval('첨가 회수율', '검량선이 없어 농도를 계산할 수 없습니다.');
    else {
      const byId = new Map(); for (const x of samples) byId.set(String(x.rec.sampleId).trim().toLowerCase(), x);
      const low = [], high = [];
      for (const x of spikes) {
        const m = measured(x); const added = x.rec.nominal;
        const pk = [x.rec.parentId, stripSuffix(x.rec.sampleId, SPIKE_SUFFIX)].filter(v => v != null && String(v).trim() !== '').map(v => String(v).trim().toLowerCase()).find(k => byId.has(k));
        const parent = pk ? byId.get(pk) : null; const pm = parent ? measured(parent) : null;
        const item = { row: x.rec.row, sampleId: x.rec.sampleId, added, measured: m, parentId: parent ? parent.rec.sampleId : null, parentConc: pm, area: x.rec.area, isArea: x.rec.isArea, min: rules.spike.minPct, max: rules.spike.maxPct };
        if (!isNum(added) || added <= 0) { item.status = 'not_evaluated'; item.note = '첨가 농도(명목 농도) 없음'; }
        else if (m == null) { item.status = 'not_evaluated'; item.note = x.q.conc == null ? '응답 없음' : '희석배수 없음'; }
        else if (parent && pm == null) { item.status = 'not_evaluated'; item.note = '원시료 ' + parent.rec.sampleId + '의 농도를 계산할 수 없음'; }
        else {
          const bg = parent ? Math.max(0, pm) : 0; item.background = bg;
          item.recoveryPct = (m - bg) / added * 100; item.kind = parent ? 'matrix' : 'blank';
          item.pass = gte(item.recoveryPct, rules.spike.minPct) && lte(item.recoveryPct, rules.spike.maxPct);
        }
        T.spikes.push(item);
        if (item.pass === false) (item.recoveryPct < rules.spike.minPct ? low : high).push(item);
      }
      const ne = T.spikes.filter(i => i.status === 'not_evaluated'); if (ne.length) notEval('첨가 시료 ' + ne.length + '개', ne.map(i => i.sampleId + '(' + i.note + ')').join(', '));
      const obs = list => list.map(i => i.sampleId + ': ' + pct(i.recoveryPct) + (i.kind === 'matrix' ? ' (원시료 ' + i.parentId + ' ' + num(i.background) + ' 차감)' : '')).join(', ');
      const basis = '회수율 = (측정 농도 − 원시료 농도) / 첨가 농도 × 100. 원시료가 연결되지 않은 첨가 시료는 원시료 농도를 0으로 둔 바탕 첨가 방식으로 계산';
      if (low.length) add('SPIKE_LOW', 'fail', obs(low), rules.spike.minPct + '–' + rules.spike.maxPct + '%', 'spike.minPct', basis, low, { all: T.spikes });
      if (high.length) add('SPIKE_HIGH', 'fail', obs(high), rules.spike.minPct + '–' + rules.spike.maxPct + '%', 'spike.maxPct', basis, high, { all: T.spikes });
    }
  }

  // ── 5. 내부표준 응답 ──
  const withIs = rows.filter(x => isNum(x.rec.isArea) && x.rec.isArea > 0);
  if (!meta.hasIs) notEval('내부표준 응답', '내부표준 면적 열이 없습니다.');
  else if (!withIs.length) notEval('내부표준 응답', '유효한 내부표준 면적이 없습니다.');
  else {
    const ref = mean(withIs.filter(x => x.rec.type === 'STD').map(x => x.rec.isArea));
    if (!isNum(ref) || !(ref > 0)) notEval('내부표준 응답', '기준이 되는 검량 표준의 내부표준 면적이 없습니다.');
    else {
      const bad = [];
      for (const x of withIs) { const p = x.rec.isArea / ref * 100; const item = { row: x.rec.row, sampleId: x.rec.sampleId, type: x.rec.type, order: x.rec.order, isArea: x.rec.isArea, pct: p, area: x.rec.area, pass: gte(p, rules.is.minPct) && lte(p, rules.is.maxPct), flag: x.q.flag, conc: x.q.conc, nominal: x.rec.nominal }; T.isItems.push(item); if (!item.pass) bad.push(item); }
      T.isRef = ref;
      if (bad.length) add('IS_RESPONSE', 'fail', bad.map(i => i.sampleId + ': ' + pct(i.pct, 0)).join(', '), '검량 표준 평균 내부표준 면적(' + num(ref) + ')의 ' + rules.is.minPct + '–' + rules.is.maxPct + '%', 'is.minPct', '내부표준 면적 / 검량 표준의 평균 내부표준 면적 × 100', bad,
        { ref, total: withIs.length, byType: countBy(bad, 'type'), all: T.isItems });
      const tr = trend(withIs.map(x => x.rec.order), withIs.map(x => x.rec.isArea));
      if (!tr.error) { T.isTrend = tr; if (tr.p < rules.cal.alpha && Math.abs(tr.changePct) >= rules.is.driftPct) add('IS_DRIFT', 'warn', '주입 순서에 따라 내부표준 면적이 ' + sgn(tr.changePct, 0) + '% 변함 (선형 추세 p = ' + tr.p.toExponential(1) + ', n = ' + tr.n + ')', '추세가 유의(p < ' + rules.cal.alpha + ')하고 변화 ≥ ' + rules.is.driftPct + '%', 'is.driftPct', '주입 순서에 대한 내부표준 면적의 선형 회귀' + (meta.hasOrder ? '' : ' (주입 순서 열이 없어 행 순서를 사용)'), withIs.map(x => ({ row: x.rec.row, sampleId: x.rec.sampleId })), { trend: tr }); }
    }
  }

  // ── 6. 머무름 시간 ──
  const withRt = rows.filter(x => isNum(x.rec.rt) && x.rec.rt > 0);
  if (!meta.hasRt) notEval('머무름 시간', '머무름 시간 열이 없습니다.');
  else if (!withRt.length) notEval('머무름 시간', '유효한 머무름 시간이 없습니다.');
  else {
    const ref = mean(withRt.filter(x => x.rec.type === 'STD').map(x => x.rec.rt));
    if (!isNum(ref)) notEval('머무름 시간', '기준이 되는 검량 표준의 머무름 시간이 없습니다.');
    else {
      const bad = []; const tol = rules.rt.mode === 'rel' ? ref * rules.rt.relPct / 100 : rules.rt.absMin;
      for (const x of withRt) {
        if ((x.rec.type === 'METHOD_BLANK' || x.rec.type === 'CAL_BLANK') && !(x.rec.area > 0)) continue;   // 피크가 없는 바탕은 평가하지 않음
        const d = x.rec.rt - ref; const item = { row: x.rec.row, sampleId: x.rec.sampleId, type: x.rec.type, order: x.rec.order, rt: x.rec.rt, delta: d, pass: lte(Math.abs(d), tol) }; T.rtItems.push(item); if (!item.pass) bad.push(item);
      }
      T.rtRef = ref; T.rtTol = tol;
      const tr = trend(T.rtItems.map(i => i.order), T.rtItems.map(i => i.rt)); if (!tr.error) T.rtTrend = tr;
      if (bad.length) add('RT_SHIFT', 'fail', bad.length + '/' + T.rtItems.length + '개 주입이 허용 범위 밖: ' + bad.slice(0, 6).map(i => i.sampleId + ' ' + sgn(i.delta, 3) + '분').join(', ') + (bad.length > 6 ? ' 외' : ''), '검량 표준 평균(' + ref.toFixed(3) + '분) ± ' + (rules.rt.mode === 'rel' ? rules.rt.relPct + '% (' + tol.toFixed(3) + '분)' : rules.rt.absMin + '분'), rules.rt.mode === 'rel' ? 'rt.relPct' : 'rt.absMin', '머무름 시간 − 검량 표준의 평균 머무름 시간', bad,
        { ref, tol, total: T.rtItems.length, later: bad.filter(i => i.delta > 0).length, earlier: bad.filter(i => i.delta < 0).length, trend: tr.error ? null : tr, byType: countBy(bad, 'type'), all: T.rtItems });
    }
  }

  // ── 7. 필수 QC 구성 ──
  const req = rules.required; const miss = [];
  const count = t => rows.filter(x => x.rec.type === t).length;
  if (count('METHOD_BLANK') < req.methodBlank) miss.push({ what: '방법 바탕', have: count('METHOD_BLANK'), need: req.methodBlank });
  if (count('CAL_BLANK') < req.calBlank) miss.push({ what: '검량 바탕', have: count('CAL_BLANK'), need: req.calBlank });
  const qcByLevel = new Map(); for (const x of qcs) if (isNum(x.rec.nominal)) qcByLevel.set(x.rec.nominal, (qcByLevel.get(x.rec.nominal) || 0) + 1);
  if (qcByLevel.size < req.qcLevels) miss.push({ what: 'QC 농도 수준', have: qcByLevel.size, need: req.qcLevels });
  const thin = Array.from(qcByLevel).filter(e => e[1] < req.qcRepsPerLevel); if (thin.length) miss.push({ what: 'QC 수준별 반복(' + thin.map(e => num(e[0])).join(', ') + ')', have: Math.min.apply(null, thin.map(e => e[1])), need: req.qcRepsPerLevel });
  if (spikes.length < req.spike) miss.push({ what: '첨가 시료', have: spikes.length, need: req.spike });
  const nDup = T.dups.length + T.reps.length; if (nDup < req.duplicate) miss.push({ what: '중복 시료 쌍', have: nDup, need: req.duplicate });
  T.missing = miss;
  if (miss.length) add('QC_MISSING', 'fail', miss.map(m => m.what + ' ' + m.have + '개 (필요 ' + m.need + ')').join(', '), '배치 필수 QC 구성', 'required.methodBlank', '시료 유형별 행 수 집계', [], { missing: miss });

  // ── 8. 시료의 정량 범위 ──
  if (calOk) {
    const above = samples.concat(dupRows).filter(x => x.q.flag === 'ALQ').map(x => ({ row: x.rec.row, sampleId: x.rec.sampleId, conc: x.q.conc }));
    const below = samples.concat(dupRows).filter(x => x.q.flag === 'BLQ' || x.q.flag === 'NEG').map(x => ({ row: x.rec.row, sampleId: x.rec.sampleId, conc: x.q.conc }));
    if (above.length) add('SAMPLE_ABOVE_RANGE', 'warn', above.map(i => i.sampleId + ' (' + num(i.conc) + ')').join(', '), '장비 측정 농도 ≤ ULOQ(' + num(cal.uloq) + ')', null, '검량 범위 밖의 값은 외삽이므로 정량값으로 쓰지 않는다', above, {});
    if (below.length) add('SAMPLE_BELOW_RANGE', 'info', below.map(i => i.sampleId).join(', '), '장비 측정 농도 ≥ LLOQ(' + num(cal.lloq) + ')', null, '정량한계 미만은 수치 대신 "LLOQ 미만"으로 보고', below, {});
  }
  return { findings: F, tables: T };
}
function countBy(list, key) { const o = {}; for (const i of list) o[i[key]] = (o[i[key]] || 0) + 1; return o; }
