// BIOPILOT — LLM 연결부. LLM은 계산을 하지 않는다: 엔진이 확정한 수치와 규칙 기반 진단을 읽기 전용으로 받아 요약과 추가 가설만 쓴다.
// 돌아온 글은 guardNarrative로 검사해, 계산 결과에 없는 수치나 단정 표현이 있으면 화면에 표시한다.

// LLM에 넘길 사실 묶음(읽기 전용). 원자료 행은 넘기지 않고 엔진의 판정 결과만 넘긴다.
export function buildFacts(result, cards, summaryLines) {
  const sel = result.findings.filter(f => f.severity !== 'info').slice(0, 60);
  return {
    engine_version: result.engineVersion, summary: summaryLines,
    dashboard: { batches: result.dashboard.batches, analytes: result.dashboard.analytes, criteria_not_met: result.dashboard.fail, cautions: result.dashboard.warn, samples_to_review: result.dashboard.reviewSamples },
    calibrations: result.groups.map(g => ({ batch: g.batchId, analyte: g.analyte, method: g.method, weighting: g.weighting, verdict: g.cal.verdict, equation: g.cal.equation || null, r2: g.cal.fit ? Number(g.cal.fit.r2.toFixed(5)) : null, levels: g.cal.nLevels || 0 })),
    findings: sel.map(f => ({ id: f.id, type: f.label, severity: f.severity, batch: f.batchId, analyte: f.analyte, observed: f.observed, criterion: f.criterion })),
    rule_based_diagnosis: cards.filter(c => sel.some(f => f.id === c.findingId)).map(c => ({ finding_id: c.findingId, observations: c.observations, hypotheses: c.hypotheses.map(h => ({ cause: h.cause, standing: h.standingLabel, support: h.support, against: h.against, unknown: h.unknown })), conclusion: c.conclusion })),
  };
}

export function buildPrompt(facts) {
  return [
    '당신은 LC-MS/MS 정량분석 데이터 검토를 돕는 분석화학 연구 보조자입니다. 아래 JSON은 결정론적 계산 엔진이 이미 확정한 결과입니다.',
    '',
    '규칙:',
    '1. 수치를 새로 계산하거나 바꾸지 마세요. 수치를 인용할 때는 JSON에 있는 값을 그대로 쓰세요. JSON에 없는 수치는 쓰지 마세요.',
    '2. 관측 사실(JSON의 observed, observations)과 가설을 섞지 마세요. 가설은 반드시 가설이라고 표시하세요.',
    '3. 원인을 확정하지 마세요. 근거가 부족하면 "원인 미확정"이라고 쓰세요. 피크 면적 감소만으로 이온 억제나 장비 고장이라고 단정하는 식의 서술은 금지입니다.',
    '4. 규칙 기반 진단에 이미 있는 가설을 반복하지 말고, 빠진 관점이 있을 때만 추가 가설을 제시하세요. 없으면 빈 배열을 돌려주세요.',
    '5. 각 추가 가설에는 이 데이터 안의 근거, 불확실성, 구별에 필요한 확인 방법을 적으세요.',
    '6. 한국어로, 아래 JSON 형식만 출력하세요. 코드 블록이나 설명을 덧붙이지 마세요.',
    '',
    '{"summary": "배치 상태를 3–5문장으로 요약", "priorities": [{"finding_id": "…", "why": "먼저 확인해야 하는 이유"}], "additional_hypotheses": [{"finding_id": "…", "hypothesis": "…", "evidence_in_data": "…", "uncertainty": "…", "how_to_test": "…"}], "cross_findings": "여러 항목을 함께 볼 때 드러나는 점(없으면 빈 문자열)", "caveats": "이 해석의 한계"}',
    '',
    '계산 결과(읽기 전용):',
    JSON.stringify(facts),
  ].join('\n');
}

// LLM 응답에서 JSON을 꺼낸다. 실패하면 { raw }만 돌려준다.
export function parseLlmJson(text) {
  const s = String(text || ''); const a = s.indexOf('{'), b = s.lastIndexOf('}');
  if (a < 0 || b <= a) return { raw: s };
  try { const o = JSON.parse(s.slice(a, b + 1)); return (o && typeof o === 'object') ? { data: o, raw: s } : { raw: s }; } catch (e) { return { raw: s }; }
}

const NUM_RE = /[-+−]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?/g;
function numbersIn(text) {
  const out = []; let m; const s = String(text); NUM_RE.lastIndex = 0;
  while ((m = NUM_RE.exec(s))) { const raw = m[0]; const clean = raw.replace(/,/g, '').replace('−', '-'); const v = Number(clean); if (Number.isFinite(v)) out.push({ raw, value: Math.abs(v), decimals: (clean.split(/[eE]/)[0].split('.')[1] || '').length }); }
  return out;
}
const ASSERTIVE = [/원인은[^.。\n]{0,40}(이다|입니다|였다|였습니다)(?![^.。\n]{0,6}(수|가능))/g, /(확실히|확실하다|확실합니다|틀림없|명백히|명백하다|분명히)/g, /(로|으로) 확정(된다|됩니다|한다|합니다|할 수 있)/g, /(때문이다|때문입니다)/g];
// LLM이 쓴 글을 검사한다. 계산 결과에 없는 수치(unsupported), 단정 표현(assertive), 존재하지 않는 항목 참조(unknownIds)를 찾아 돌려준다.
export function guardNarrative(output, facts) {
  const texts = []; const collect = v => { if (typeof v === 'string') texts.push(v); else if (Array.isArray(v)) v.forEach(collect); else if (v && typeof v === 'object') Object.keys(v).forEach(k => { if (k !== 'finding_id') collect(v[k]); }); };
  collect(output && output.data ? output.data : (output && output.raw) || output);
  const factNums = numbersIn(JSON.stringify(facts)).map(n => n.value); const text = texts.join('\n');
  const cited = numbersIn(text); const unsupported = [];
  for (const n of cited) {
    if (Number.isInteger(n.value) && n.value <= 10 && n.decimals === 0) continue;       // 개수·순번 같은 작은 정수는 검사하지 않는다
    const scale = Math.pow(10, n.decimals); const ok = factNums.some(f => Math.abs(Math.round(f * scale) / scale - n.value) < 1e-9 || Math.abs(f - n.value) <= 1e-9 * Math.max(1, f));
    if (!ok) unsupported.push(n.raw);
  }
  const assertive = []; for (const re of ASSERTIVE) { re.lastIndex = 0; let m; while ((m = re.exec(text))) { const ctx = text.slice(Math.max(0, m.index - 12), m.index + m[0].length + 14); if (!/(수 없|않|미확정|불가|아니|가설|가능성)/.test(ctx)) assertive.push(ctx.replace(/\s+/g, ' ').trim()); } }
  const ids = new Set((facts.findings || []).map(f => f.id)); const unknownIds = [];
  const walkIds = v => { if (Array.isArray(v)) v.forEach(walkIds); else if (v && typeof v === 'object') { if (typeof v.finding_id === 'string' && !ids.has(v.finding_id)) unknownIds.push(v.finding_id); Object.values(v).forEach(walkIds); } };
  if (output && output.data) walkIds(output.data);
  return { citedCount: cited.length, unsupported: Array.from(new Set(unsupported)), assertive: Array.from(new Set(assertive)), unknownIds: Array.from(new Set(unknownIds)), parsed: !!(output && output.data),
    ok: unsupported.length === 0 && assertive.length === 0 && unknownIds.length === 0 };
}
