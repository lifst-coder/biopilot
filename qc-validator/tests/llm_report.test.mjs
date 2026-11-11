// LLM 연결부(가짜 응답으로 시험)와 보고서 생성 시험
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCsv, decodeText } from '../src/parse.js';
import { runRows, defaultSettings } from '../src/pipeline.js';
import { diagnose, summarize } from '../src/diagnose.js';
import { buildFacts, buildPrompt, parseLlmJson, guardNarrative } from '../src/llm.js';
import { buildReport, reportHtml, findingsCsv, quantCsv } from '../src/report.js';

const data = join(dirname(fileURLToPath(import.meta.url)), '..', 'data');
const run = runRows(parseCsv(decodeText(readFileSync(join(data, 'synthetic_all_batches.csv'))).text).rows);
const cards = diagnose(run.result), lines = summarize(run.result), facts = buildFacts(run.result, cards, lines);
const spike = run.result.findings.find(f => f.code === 'SPIKE_LOW');

test('LLM에 넘기는 사실 묶음: 엔진 판정만 담고 원자료 행은 담지 않는다', () => {
  const s = JSON.stringify(facts); assert.ok(facts.findings.length > 0 && facts.findings.every(f => f.id && f.observed)); assert.ok(facts.rule_based_diagnosis.length > 0);
  assert.ok(!('rows' in facts) && !/"isArea"|"area"/.test(s)); assert.ok(s.length < 200000, '프롬프트 크기 ' + s.length);
  assert.ok(facts.findings.every(f => f.severity !== 'info'));
});
test('프롬프트: 수치 변경 금지, 사실/가설 분리, 원인 미확정 규칙과 출력 형식을 포함한다', () => {
  const p = buildPrompt(facts); for (const k of ['수치를 새로 계산하거나 바꾸지 마세요', '관측 사실', '가설', '원인 미확정', 'additional_hypotheses', '읽기 전용']) assert.ok(p.includes(k), k);
  assert.ok(p.endsWith(JSON.stringify(facts)));
});
test('LLM 응답 해석: JSON을 꺼내고, 형식이 깨지면 원문만 보존한다', () => {
  assert.deepEqual(parseLlmJson('설명 {"summary": "ok"} 끝').data, { summary: 'ok' }); assert.equal(parseLlmJson('JSON 아님').data, undefined); assert.equal(parseLlmJson('{깨진').raw, '{깨진'); assert.equal(parseLlmJson(null).raw, '');
});
test('가드: 계산 결과의 수치만 인용한 충실한 응답은 통과', () => {
  const rec = /: (\d+\.\d)%/.exec(spike.observed)[1];
  const out = parseLlmJson(JSON.stringify({ summary: '첨가 회수율이 ' + rec + '%로 기준 70–130%를 벗어났다. 원인은 미확정이다.', priorities: [{ finding_id: spike.id, why: '시료 결과의 정확도에 직접 영향' }], additional_hypotheses: [{ finding_id: spike.id, hypothesis: '가설: 첨가 용액의 보관 중 농도 변화 가능성', evidence_in_data: '다른 분석물은 정상', uncertainty: '보관 기록이 없어 판단 불가', how_to_test: '첨가 용액 재조제 후 비교' }], cross_findings: '', caveats: '데이터만으로는 원인을 확정할 수 없다.' }));
  const g = guardNarrative(out, facts); assert.deepEqual(g.unsupported, []); assert.deepEqual(g.assertive, []); assert.deepEqual(g.unknownIds, []); assert.equal(g.ok, true); assert.ok(g.citedCount >= 3);
});
test('가드: 계산 결과에 없는 수치를 잡아낸다(LLM이 값을 바꾸거나 지어낸 경우)', () => {
  const out = parseLlmJson(JSON.stringify({ summary: '첨가 회수율은 62.4%였고 R²는 0.8123이다. 보정하면 회수율 97.3%가 된다.', priorities: [], additional_hypotheses: [], cross_findings: '', caveats: '' }));
  const g = guardNarrative(out, facts); assert.equal(g.ok, false); for (const n of ['62.4', '0.8123', '97.3']) assert.ok(g.unsupported.includes(n), n);
});
test('가드: 반올림한 인용은 허용하고 작은 정수(개수·순번)는 검사하지 않는다', () => {
  const rec = Number(/: (\d+\.\d)%/.exec(spike.observed)[1]);
  const g = guardNarrative(parseLlmJson(JSON.stringify({ summary: '회수율 약 ' + Math.round(rec) + '%. 후보 3개 중 2개가 일관된다.', caveats: '' })), facts); assert.deepEqual(g.unsupported, []);
});
test('가드: 원인을 단정하는 표현을 잡아내고, 부정·가설 문맥은 통과시킨다', () => {
  const bad = guardNarrative(parseLlmJson(JSON.stringify({ summary: '회수율 저하의 원인은 이온 억제이다. 장비 고장이 확실하다. 전처리 손실 때문이다.' })), facts); assert.equal(bad.ok, false); assert.ok(bad.assertive.length >= 3);
  const ok = guardNarrative(parseLlmJson(JSON.stringify({ summary: '원인은 이 데이터로 확정할 수 없다. 이온 억제 때문일 가능성이 있다. 확실히 말할 수 없다.' })), facts); assert.deepEqual(ok.assertive, []);
});
test('가드: 존재하지 않는 항목을 가리키면 잡아낸다', () => {
  const g = guardNarrative(parseLlmJson(JSON.stringify({ summary: '요약', priorities: [{ finding_id: 'FAKE|X|Y|1', why: '?' }] })), facts); assert.deepEqual(g.unknownIds, ['FAKE|X|Y|1']); assert.equal(g.ok, false);
});
test('가드: JSON이 아닌 원문 응답도 검사한다', () => { const g = guardNarrative(parseLlmJson('회수율은 12.34%이며 원인은 오염이다.'), facts); assert.equal(g.parsed, false); assert.ok(g.unsupported.includes('12.34')); assert.ok(g.assertive.length >= 1); });
test('LLM 경로는 엔진 결과를 바꾸지 않는다', () => { const before = JSON.stringify(run.result); buildPrompt(buildFacts(run.result, cards, lines)); guardNarrative(parseLlmJson('{"summary":"x 999"}'), facts); assert.equal(JSON.stringify(run.result), before); });

const ctx = { fileName: 'synthetic_all_batches.csv', format: 'CSV', generatedAt: '2026-11-11 12:00', settings: defaultSettings(), issues: run.built.issues, cards, summary: lines, isExample: true,
  reviews: { [spike.id]: { status: 'action', note: '첨가 용액 재조제 후 재분석 예정', time: '2026-11-11 12:01' } }, log: [{ time: '2026-11-11 12:01', action: '검토 상태 변경', target: spike.id, note: '조치 필요: 첨가 용액 재조제 후 재분석 예정' }] };
const report = buildReport(run.result, ctx);
test('보고서(구조화): 요약·검량선·QC 결과·진단·검토 기록·적용 기준을 담고 JSON으로 직렬화된다', () => {
  const back = JSON.parse(JSON.stringify(report)); for (const k of ['summary', 'settings', 'calibrations', 'findings', 'reviewSamples', 'diagnosis', 'reviewLog', 'notice']) assert.ok(k in back, k);
  assert.equal(back.calibrations.length, 27); assert.equal(back.findings.length, run.result.findings.length); assert.equal(back.summary.dashboard.batches, 9);
  const f = back.findings.find(x => x.id === spike.id); assert.equal(f.review.status, 'action'); assert.match(f.review.note, /재조제/); assert.match(f.ruleSource, /EPA 537\.1/);
  assert.ok(back.findings.filter(x => x.id !== spike.id).every(x => x.review.status === 'open')); assert.match(back.notice, /예시 기준/); assert.match(back.settings.profile, /예시/); assert.equal(back.settings.rules.length > 25, true);
  assert.ok(back.diagnosis.every(d => d.causeStatus === '원인 미확정'));
});
test('보고서(HTML): 모든 절이 있고 특수문자가 이스케이프된다', () => {
  const h = reportHtml(buildReport(run.result, Object.assign({}, ctx, { log: [{ time: 't', action: '메모', target: '<script>alert(1)</script>', note: 'a & b' }] })));
  for (const s of ['1. 분석 요약', '2. 검량선', '3. QC 결과', '4. 검토가 필요한 시료', '5. 이상 원인 진단 (가설)', '검토 기록', '부록. 적용한 QC 기준', '합성 예시 데이터', '원인 미확정', 'R²는 참고값']) assert.ok(h.includes(s), s);
  assert.ok(h.startsWith('<!doctype html>')); assert.ok(!h.includes('<script>alert(1)</script>')); assert.ok(h.includes('&lt;script&gt;')); assert.ok(h.includes('a &amp; b'));
});
test('보고서(CSV): 판정 표와 정량 결과 표가 다시 읽히고 행 수가 맞는다', () => {
  const f = parseCsv(findingsCsv(report)).rows; assert.equal(f.length, run.result.findings.length + 1); assert.equal(f[0][2], '오류 유형'); assert.ok(f.some(r => r[10] === '조치 필요'));
  const q = parseCsv(quantCsv(run.result)).rows; assert.equal(q.length, run.built.records.length + 1); assert.equal(q[0][9], '장비 측정 농도'); assert.ok(q.some(r => r[12] === 'ULOQ 초과' || r[12] === 'LLOQ 미만' || r[12] === ''));
});
