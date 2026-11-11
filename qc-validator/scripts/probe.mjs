// 개발용: 시나리오별 탐지 결과를 출력한다.  node scripts/probe.mjs [seed]
import { generateDataset, SCENARIOS } from '../src/synth.js';
import { runRows, scoreScenario } from '../src/pipeline.js';
const seed = Number(process.argv[2] || 1);
for (const s of SCENARIOS) {
  const run = runRows(generateDataset([s.id], seed));
  const sc = scoreScenario(run.result, s.id);
  console.log('== ' + s.id + ' ' + s.name + '  detected=' + sc.detected + ' clean=' + sc.clean + (sc.fn.length ? '  MISSED ' + sc.fn.join(',') : '') + (sc.fp.length ? '  FALSE-POS ' + sc.fp.join(',') : ''));
  for (const f of run.result.findings.filter(f => f.severity !== 'info')) console.log('   [' + f.severity + '] ' + f.code + ' / ' + f.analyte + ' — ' + f.observed.slice(0, 150));
  if (process.argv[3]) for (const g of run.result.groups) console.log('   ', g.analyte, g.cal.equation, 'R2', g.cal.fit && g.cal.fit.r2.toFixed(5), g.cal.verdict, 'curv', g.cal.diagnostics.curvature && [g.cal.diagnostics.curvature.p.toExponential(1), g.cal.diagnostics.curvature.curvaturePct.toFixed(1)].join('/'));
  const issues = run.built.issues.filter(i => i.severity === 'error'); if (issues.length) console.log('   ISSUES', issues.map(i => i.code).join(','));
}
