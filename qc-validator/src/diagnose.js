// BIOPILOT — 이상 원인 진단(규칙 기반 지식). 계산은 하지 않고, 엔진이 낸 수치를 읽어 가설을 정리한다.
// 원칙: (1) 관측 사실과 가설을 분리한다. (2) 가설마다 이 데이터 안의 지지 근거·반대 근거·판단할 수 없는 부분을 적는다.
//       (3) 데이터만으로 원인을 확정하지 않는다. 결론은 항상 "원인 미확정"이며, 구별에 필요한 확인 절차를 제시한다.
import { isNum, mean, rsd } from './stats.js';
import { TYPES } from './parse.js';

export const STANDING = { supported: '이 데이터와 일관됨', mixed: '근거가 엇갈림', weak: '이 데이터와는 잘 맞지 않음', untestable: '이 데이터로는 판단 불가' };
const p1 = v => isNum(v) ? v.toFixed(1) : '–'; const p0 = v => isNum(v) ? v.toFixed(0) : '–';
const sg = (v, d) => isNum(v) ? (v >= 0 ? '+' : '') + v.toFixed(d === undefined ? 1 : d) : '–';
const n4 = v => isNum(v) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : Number(v.toPrecision(4)).toString()) : '–';
function hyp(cause, support, against, unknown) {
  const s = support.filter(Boolean), a = against.filter(Boolean);
  const standing = s.length && !a.length ? 'supported' : s.length && a.length ? 'mixed' : a.length ? 'weak' : 'untestable';
  return { cause, support: s, against: a, unknown: unknown || '', standing, standingLabel: STANDING[standing] };
}
function conclude(hyps, extra) {
  const consistent = hyps.filter(h => h.standing === 'supported').map(h => h.cause);
  return '원인 미확정. ' + (consistent.length ? '이 데이터와 일관된 후보는 ' + consistent.length + '개(' + consistent.join(' / ') + ')이지만, 데이터만으로는 서로를 구별하거나 확정할 수 없다. ' : '이 데이터 안에는 어느 후보를 특별히 지지하는 근거가 없다. ') + (extra || '아래 확인 절차의 결과가 있어야 원인을 좁힐 수 있다.');
}

function ctxOf(result, group) {
  const others = result.groups.filter(g => g.batchId === group.batchId && g.analyte !== group.analyte);
  const isPct = row => { const i = (group.tables.isItems || []).find(x => x.row === row); return i ? i.pct : null; };
  const rtDelta = row => { const i = (group.tables.rtItems || []).find(x => x.row === row); return i ? i.delta : null; };
  const qc = group.tables.qcItems.filter(i => i.pass !== undefined);
  const qcSum = { n: qc.length, nPass: qc.filter(i => i.pass).length, meanRe: qc.length ? mean(qc.map(i => i.rePct)) : null };
  const othersWith = code => others.filter(g => g.findings.some(f => f.code === code && f.severity !== 'info')).map(g => g.analyte);
  return { others, isPct, rtDelta, qcSum, othersWith, hasIs: result.meta.hasIs, hasOrder: result.meta.hasOrder, method: group.method };
}

const BUILDERS = {};

BUILDERS.CAL_NONLINEAR = (f, g, c) => {
  const d = f.details; const down = d.curvaturePct < 0; const std = g.cal.points.filter(p => p.included);
  const lowIs = mean(std.slice(0, Math.ceil(std.length / 2)).filter(p => isNum(p.isArea)).map(p => p.isArea)), topIs = std[std.length - 1].isArea;
  const isChange = isNum(lowIs) && isNum(topIs) && lowIs > 0 ? (topIs / lowIs - 1) * 100 : null;
  const top = std[std.length - 1], second = std[std.length - 2];
  const onlyTop = Math.abs(top.devPct) > top.limit && std.slice(0, -1).every(p => p.pass);
  const obs = ['직선과 2차식을 같은 가중치(' + g.weighting + ')로 적합해 비교한 F 검정의 p값은 ' + d.p.toExponential(2) + '이다.',
    '최고 농도 ' + n4(top.nominal) + '에서 2차 항은 1차 항의 ' + sg(d.curvaturePct) + '%이다(' + (down ? '응답이 직선보다 낮아지는 방향' : '응답이 직선보다 높아지는 방향') + ').',
    '검량점별 역산 편차: ' + std.map(p => n4(p.nominal) + ' → ' + sg(p.devPct) + '%').join(', ') + '.',
    'R²는 ' + g.cal.fit.r2.toFixed(5) + '이다. R²가 높아도 곡률은 존재할 수 있다.'];
  if (isChange != null) obs.push('최고 농도 표준의 내부표준 면적은 저농도 절반 평균 대비 ' + sg(isChange) + '%이다.');
  const hyps = [
    hyp('검출기 또는 이온화의 포화', [down ? '고농도로 갈수록 응답이 직선보다 낮아진다(' + n4(second.nominal) + ': ' + sg(second.devPct) + '%, ' + n4(top.nominal) + ': ' + sg(top.devPct) + '%).' : ''], [down ? '' : '곡률 방향이 포화와 반대다(고농도에서 응답이 더 높다).'], '피크 꼭대기 모양과 검출기 카운트 상한은 입력 데이터에 없다.'),
    hyp('분석물과 내부표준 사이의 상호 억제 또는 신호 간섭(크로스토크)', [isChange != null && Math.abs(isChange) > 15 ? '내부표준 면적이 분석물 농도에 따라 ' + sg(isChange) + '% 변한다.' : ''], [isChange != null && Math.abs(isChange) <= 15 ? '내부표준 면적은 농도 구간 전체에서 ' + sg(isChange) + '% 이내로 유지된다.' : ''], c.method === 'external' ? '외부표준법이라 내부표준 관계를 평가하지 않았다.' : '내부표준의 동위원소 순도와 전이 설정은 입력 데이터에 없다.'),
    hyp('검량 범위가 분석법의 직선 범위보다 넓거나, 회귀 모형·가중치가 밸리데이션 조건과 다름', [onlyTop ? '최고 농도 한 점만 기준을 벗어나고 나머지는 기준 내다.' : '편차가 농도에 따라 한 방향으로 커진다.'], [], '밸리데이션에서 정한 범위와 모형은 입력 데이터에 없다.'),
    hyp('표준용액 조제의 계통 오차(연속 희석 단계)', [], [std.length >= 4 && !onlyTop ? '편차가 한 단계에서 갑자기 변하지 않고 농도에 따라 매끄럽게 변한다.' : ''], '조제 기록이 없으면 판단할 수 없다.'),
  ];
  if (!down) hyps.push(hyp('저농도에서의 흡착 손실 또는 바탕 신호의 기여', ['저농도 쪽 응답이 상대적으로 낮거나 절편의 영향이 크다(절편 ' + n4(g.cal.fit.intercept) + ').'], [], '용기 재질과 바탕 신호의 출처는 입력 데이터에 없다.'));
  return { title: '검량선이 직선에서 벗어남', observations: obs, hypotheses: hyps,
    checks: ['고농도 표준의 크로마토그램 피크 모양(꼭대기가 평탄한지)', '검출기 신호가 상한에 가까운지(원시 카운트)', '내부표준 면적이 분석물 농도에 따라 변하는지', '표준용액 조제 기록과 원액의 유효기간', '분석법 밸리데이션에서 정한 직선 범위·회귀 모형·가중치'],
    verifications: ['최고 농도 표준을 2배·5배 희석해 다시 주입하고 역산 농도가 맞는지 확인', '독립적으로 조제한 표준(다른 원액)으로 고농도 수준을 다시 측정', '범위를 줄여 다시 평가할 경우 사유를 기록하고 그 범위 밖 시료는 희석 재분석', '분석법에 2차 모형이 밸리데이션되어 있는지 확인(이 도구는 직선 모형만 계산한다)'],
    conclusion: conclude(hyps, onlyTop || g.cal.diagnostics.endPointAmbiguity ? '최고 농도 한 점만 벗어난 경우 포화와 단일 이상점은 이 데이터로 구별되지 않는다. 희석 재주입이 가장 직접적인 구별 방법이다.' : null) };
};

BUILDERS.CAL_OUTLIER = (f, g, c) => {
  const d = f.details; const pt = d.point || {}; const ip = c.isPct(pt.row), rd = c.rtDelta(pt.row); const up = d.devPct > 0;
  const std = g.cal.points.filter(p => p.included); const idx = std.findIndex(p => p.row === pt.row); const prev = idx > 0 ? std[idx - 1] : null;
  const sameLevel = std.filter(p => p.nominal === pt.nominal && p.row !== pt.row);
  const obs = ['명목 ' + n4(d.nominal) + '의 검량점(' + pt.sampleId + ')만 역산 편차가 ' + sg(d.devPct) + '%로 기준(±' + pt.limit + '%)을 벗어난다.',
    d.looDevPct != null ? '이 점을 빼고 다시 적합하면 이 점의 편차는 ' + sg(d.looDevPct) + '%이고' + (d.restAllPass ? ' 나머지 검량점은 모두 기준 내다.' : ' 나머지 중에도 기준을 벗어나는 점이 있다.') : '',
    ip != null ? '이 주입의 내부표준 면적은 검량 표준 평균의 ' + p0(ip) + '%이다.' : '', rd != null ? '이 주입의 머무름 시간은 검량 표준 평균과 ' + sg(rd, 3) + '분 차이다.' : '',
    sameLevel.length ? '같은 수준의 다른 반복 ' + sameLevel.length + '개의 편차: ' + sameLevel.map(p => sg(p.devPct) + '%').join(', ') + '.' : '이 수준은 단일 측정이라 반복으로 확인할 수 없다.'].filter(Boolean);
  const isNormal = ip != null && ip >= 80 && ip <= 120;
  const hyps = [
    hyp('해당 수준 표준용액의 조제 오류(피펫팅·희석·바이알 혼동)', [d.restAllPass ? '한 수준만 벗어나고 나머지는 기준 내다.' : '', isNormal && c.method === 'internal' ? '내부표준 면적은 정상(' + p0(ip) + '%)인데 면적비만 벗어난다. 분석물 쪽 농도가 달랐을 때 나타나는 양상이다.' : ''], [sameLevel.length && sameLevel.every(p => p.pass) ? '같은 수준의 다른 반복은 기준 내다(같은 용액을 쓴 반복이라면 조제 오류와 맞지 않는다).' : ''], '조제 기록이 없다.'),
    hyp('주입량 또는 이온화의 일시적 이상', [ip != null && !isNormal ? '내부표준 면적도 ' + p0(ip) + '%로 평소와 다르다.' : ''], [isNormal && c.method === 'internal' ? '내부표준 면적이 정상이다. 주입량 문제라면 내부표준도 함께 변하고 면적비는 유지되었을 것이다.' : ''], c.method === 'external' ? '외부표준법에서는 주입량 변동이 그대로 결과에 반영되므로 배제할 수 없다.' : ''),
    hyp('피크 적분 오류(베이스라인, 인접 피크 병합, 분리)', [rd != null && Math.abs(rd) > 0.05 ? '머무름 시간이 ' + sg(rd, 3) + '분 다르다.' : ''], [], '크로마토그램이 없어 판단할 수 없다.'),
  ];
  if (up) hyps.push(hyp('직전 주입의 잔류(캐리오버) 또는 오염', [prev && prev.nominal > pt.nominal ? '직전 표준이 더 높은 농도(' + n4(prev.nominal) + ')였다.' : ''], [prev && prev.nominal <= pt.nominal ? '직전 표준은 더 낮은 농도(' + n4(prev.nominal) + ')였다.' : ''], '바탕 시료의 신호 수준과 함께 봐야 한다.'));
  return { title: '검량점 하나가 검량선에서 벗어남', observations: obs, hypotheses: hyps,
    checks: ['해당 주입의 크로마토그램과 적분 구간', '표준 조제 기록(희석 단계, 사용 피펫)', '바이알 위치와 라벨', '직전·직후 주입의 종류'],
    verifications: ['같은 바이알을 다시 주입: 재현되면 용액 쪽, 재현되지 않으면 주입·적분 쪽 가능성이 커진다', '해당 수준을 새로 조제해 측정', '검량점을 제외할 때는 SOP의 제외 기준에 따르고 사유를 기록(이 도구의 Calibration 화면에서 사유와 함께 제외할 수 있다)'],
    conclusion: conclude(hyps) };
};

function blankCard(f, g, c) {
  const isMethod = f.code === 'MB_CONTAM'; const items = f.details.items; const other = f.details.otherBlankType || []; const same = f.details.allBlanks || [];
  const otherBad = other.filter(i => i.pass === false), otherOk = other.filter(i => i.pass === true), sameOk = same.filter(i => i.pass === true);
  const carry = items.filter(i => i.prev && i.prev.aboveHalfUloq), noCarry = items.filter(i => i.prev && !i.prev.aboveHalfUloq);
  const rtOff = items.map(i => ({ i, d: c.rtDelta(i.row) })).filter(x => x.d != null);
  const obs = items.map(i => (isMethod ? '방법 바탕 ' : '검량 바탕 ') + i.sampleId + '의 분석물 면적은 ' + n4(i.area) + '로 LLOQ 표준 평균 면적의 ' + p1(i.pctOfLloq) + '%이다' + (isNum(i.conc) ? '(계산 농도 ' + n4(i.conc) + ', LLOQ ' + n4(g.cal.lloq) + ').' : '.'));
  for (const i of items) if (i.prev) obs.push(i.sampleId + '의 직전 주입은 ' + i.prev.sampleId + '(' + (TYPES[i.prev.type] || i.prev.type) + (isNum(i.prev.conc) ? ', 계산 농도 ' + n4(i.prev.conc) : '') + ')이다' + (c.hasOrder ? '.' : '(행 순서를 주입 순서로 가정).'));
  if (other.length) obs.push((isMethod ? '검량 바탕' : '방법 바탕') + ' ' + other.length + '개 중 ' + otherBad.length + '개가 기준을 넘는다.');
  if (sameOk.length) obs.push('같은 종류의 다른 바탕 ' + sameOk.length + '개는 기준 내다.');
  for (const x of rtOff) obs.push(x.i.sampleId + '에서 검출된 피크의 머무름 시간은 검량 표준 평균과 ' + sg(x.d, 3) + '분 차이다.');
  const hyps = [
    hyp('직전 고농도 주입의 잔류(캐리오버)', [carry.length ? '직전 주입의 농도가 ULOQ의 절반을 넘는다(' + carry.map(i => i.prev.sampleId).join(', ') + ').' : ''], [noCarry.length ? '직전 주입이 저농도 또는 바탕이다(' + noCarry.map(i => i.prev.sampleId).join(', ') + ').' : ''], '니들 세척 조건과 연속 바탕 주입 결과가 없다.'),
    hyp('전처리 과정의 오염(시약·용기·고상추출 카트리지·공용 기구)', [isMethod && otherOk.length && !otherBad.length ? '전처리를 거친 방법 바탕만 높고, 전처리를 거치지 않은 검량 바탕은 기준 내다.' : ''], [!isMethod ? '전처리를 거치지 않는 검량 바탕에서 나타났다.' : '', isMethod && otherBad.length ? '검량 바탕도 함께 높다(전처리 이전 단계의 원인도 가능).' : ''], '시약 lot와 단계별 바탕 결과가 없다.'),
    hyp('용매·이동상·시스템의 오염', [!isMethod || otherBad.length ? '전처리를 거치지 않은 바탕에서도 신호가 나온다.' : ''], [isMethod && otherOk.length && !otherBad.length ? '검량 바탕은 기준 내다.' : '', sameOk.length ? '같은 종류의 다른 바탕은 기준 내다(지속적인 오염이라면 모두 높았을 것이다).' : ''], ''),
    hyp('분석물이 아닌 간섭 피크(같은 전이를 내는 공존 물질)', [rtOff.some(x => Math.abs(x.d) > (g.tables.rtTol || 0.1)) ? '바탕에서 검출된 피크의 머무름 시간이 표준과 다르다.' : ''], [rtOff.length && rtOff.every(x => Math.abs(x.d) <= (g.tables.rtTol || 0.1)) ? '머무름 시간이 표준과 일치한다(' + rtOff.map(x => sg(x.d, 3) + '분').join(', ') + ').' : ''], '확인 이온과의 이온비는 입력 데이터에 없다.'),
  ];
  const lowSamples = g.rows.filter(x => (x.rec.type === 'SAMPLE' || x.rec.type === 'DUP') && isNum(x.q.conc) && x.q.conc < 5 * g.cal.lloq).map(x => x.rec.sampleId);
  return { title: (isMethod ? '방법 바탕' : '검량 바탕') + '에서 분석물 신호 검출', observations: obs.concat(lowSamples.length ? ['농도가 LLOQ의 5배 미만인 시료 ' + lowSamples.length + '개(' + lowSamples.slice(0, 6).join(', ') + (lowSamples.length > 6 ? ' 외' : '') + ')는 바탕 신호의 영향을 상대적으로 크게 받을 수 있다.'] : []), hypotheses: hyps,
    checks: ['주입 순서에서 바탕 직전의 시료', '용매 바탕을 연속 주입했을 때 신호가 줄어드는지', '시약·용매·카트리지의 lot', '확인 이온의 이온비', '바탕 신호가 배치 전체에서 일정한지'],
    verifications: ['용매 바탕을 2–3회 연속 주입: 신호가 차례로 줄면 캐리오버, 일정하면 시스템·용매 오염 쪽', '전처리 단계별 시약 바탕을 만들어 어느 단계에서 들어오는지 확인', '니들 세척 용매·횟수를 바꿔 재현 여부 확인', '저농도 시료는 바탕 문제를 해결한 뒤 재분석 여부를 판단'],
    conclusion: conclude(hyps) };
}
BUILDERS.MB_CONTAM = blankCard; BUILDERS.CB_CONTAM = blankCard;

function spikeCard(f, g, c) {
  const low = f.code === 'SPIKE_LOW'; const items = f.details.items; const all = (f.details.all || []).filter(i => i.pass !== undefined);
  const matrixBad = items.filter(i => i.kind === 'matrix'), blankBad = items.filter(i => i.kind === 'blank'); const blankOk = all.filter(i => i.kind === 'blank' && i.pass), matrixOk = all.filter(i => i.kind === 'matrix' && i.pass);
  const isVals = items.map(i => c.isPct(i.row)).filter(isNum); const isNormal = isVals.length && isVals.every(v => v >= 80 && v <= 120);
  const othersBad = c.othersWith(f.code), othersAll = c.others.filter(o => (o.tables.spikes || []).some(s => s.pass !== undefined)).map(o => o.analyte);
  const obs = items.map(i => '첨가 시료 ' + i.sampleId + '의 회수율은 ' + p1(i.recoveryPct) + '%이다(첨가 ' + n4(i.added) + ', 측정 ' + n4(i.measured) + (i.kind === 'matrix' ? ', 원시료 ' + i.parentId + ' ' + n4(i.background) + ' 차감' : ', 원시료 연결 없음') + '; 기준 ' + i.min + '–' + i.max + '%).');
  if (isVals.length) obs.push('해당 주입의 내부표준 면적은 검량 표준 평균의 ' + isVals.map(p0).join('%, ') + '%이다.');
  if (c.qcSum.n) obs.push('같은 배치의 QC 시료는 ' + c.qcSum.nPass + '/' + c.qcSum.n + '개가 기준 내이고 평균 상대오차는 ' + sg(c.qcSum.meanRe) + '%이다.');
  if (othersAll.length) obs.push('같은 배치의 다른 분석물 ' + othersAll.length + '종 중 같은 문제가 나타난 것은 ' + (othersBad.length ? othersBad.join(', ') : '없다') + '.');
  const qcGood = c.qcSum.n > 0 && c.qcSum.nPass === c.qcSum.n;
  const hyps = low ? [
    hyp('전처리 단계의 손실(추출 효율, 용기 흡착, 농축·건고 손실)', [isNormal ? '내부표준 면적은 정상인데 분석물만 낮다.' : '', qcGood ? 'QC가 모두 기준 내여서 장비·검량선 쪽 문제 가능성은 낮다.' : ''], [othersBad.length === 0 && othersAll.length && isNormal ? '' : ''], '내부표준을 추출 전에 넣었는지 후에 넣었는지 입력 데이터에 없다. 추출 전에 넣었다면 내부표준이 손실을 일부 보정했어야 한다.'),
    hyp('매질에 의한 이온 억제가 내부표준으로 보정되지 않음', [matrixBad.length && blankOk.length ? '매질 첨가 시료만 낮고 바탕 첨가 시료는 기준 내다.' : ''], [blankBad.length ? '매질이 없는 바탕 첨가 시료(' + blankBad.map(i => i.sampleId).join(', ') + ')에서도 낮다.' : '', isVals.length && isNormal ? '내부표준 면적이 억제되지 않았다(같이 용출되는 동위원소 표지 내부표준이라면 함께 억제되었을 것이다).' : ''], '내부표준이 분석물과 같이 용출되는 동위원소 표지 물질인지 입력 데이터에 없다.'),
    hyp('첨가 용액의 농도 또는 첨가량 오류', [items.length >= 2 && Math.max.apply(null, items.map(i => i.recoveryPct)) - Math.min.apply(null, items.map(i => i.recoveryPct)) < 15 ? '첨가 시료들의 회수율이 서로 비슷하다(' + items.map(i => p0(i.recoveryPct) + '%').join(', ') + '). 공통 원인일 때의 양상이다.' : ''], [othersAll.length && othersBad.length === 0 ? '' : ''], othersAll.length && othersBad.length === 0 ? '다른 분석물은 정상이다. 혼합 첨가 용액을 썼다면 첨가량 오류와는 맞지 않지만, 이 분석물만의 농도 문제는 배제되지 않는다.' : '첨가 용액 조제 기록이 없다.'),
    hyp('분석물의 분해 또는 불안정(용액·시료 중)', [othersAll.length && othersBad.length === 0 ? '이 분석물에서만 나타난다.' : ''], [qcGood ? 'QC는 기준 내다(QC와 첨가 용액의 조제·보관 조건이 같다면 분해와 맞지 않는다).' : ''], '보관 시간과 조건이 입력 데이터에 없다.'),
  ] : [
    hyp('첨가 용액의 농도 또는 첨가량 과다', [items.length >= 2 ? '여러 첨가 시료에서 함께 높다.' : ''], [], '첨가 용액 조제 기록이 없다.'),
    hyp('원시료 농도의 과소 평가 또는 시료 불균질', [matrixBad.length ? '매질 첨가 시료에서 나타난다(원시료 값을 차감하므로 원시료 측정의 오차가 그대로 반영된다).' : ''], [blankBad.length ? '원시료가 없는 바탕 첨가 시료에서도 높다.' : ''], ''),
    hyp('매질에 의한 이온 증강 또는 공존 간섭', [matrixBad.length && blankOk.length ? '매질 첨가 시료만 높다.' : ''], [blankBad.length ? '매질이 없는 첨가 시료에서도 높다.' : ''], '이온비와 크로마토그램이 없다.'),
    hyp('오염 또는 캐리오버', [], [], '바탕 시료 결과와 함께 봐야 한다.'),
  ];
  return { title: '첨가 회수율이 기준보다 ' + (low ? '낮음' : '높음'), observations: obs, hypotheses: hyps,
    checks: ['내부표준을 넣는 시점(추출 전·후)', '첨가 용액의 조제 기록과 유효기간', '추출 조건(pH, 용매, 시간)의 변경 여부', '같은 배치 다른 분석물의 회수율', '검량 표준과 첨가 용액이 같은 원액에서 왔는지'],
    verifications: ['추출 전 첨가와 추출 후 첨가를 나란히 분석해 추출 손실과 매질 효과를 분리', '첨가 용액을 용매로 직접 희석해 주입하고 농도를 확인', '매질 추출물을 희석해 다시 측정(매질 효과가 줄어드는지)', '필요하면 포스트컬럼 주입 실험으로 억제 구간 확인'],
    conclusion: conclude(hyps) };
}
BUILDERS.SPIKE_LOW = spikeCard; BUILDERS.SPIKE_HIGH = spikeCard;

BUILDERS.IS_RESPONSE = (f, g, c) => {
  const d = f.details; const items = d.items; const lowN = items.filter(i => i.pct < 100).length, highN = items.length - lowN;
  const types = Object.keys(d.byType); const onlyUnknown = types.every(t => t === 'SAMPLE' || t === 'DUP' || t === 'SPIKE'); const stdAffected = types.includes('STD') || types.includes('QC');
  const orders = items.map(i => i.order).sort((a, b) => a - b); const consecutive = orders.length > 1 && orders[orders.length - 1] - orders[0] === orders.length - 1;
  const shared = c.others.filter(o => (o.tables.isItems || []).some(x => !x.pass && items.some(i => i.sampleId === x.sampleId))).map(o => o.analyte);
  const known = items.filter(i => i.type === 'QC' || i.type === 'STD');
  const knownOk = known.filter(i => { const q = g.tables.qcItems.find(x => x.row === i.row); const s = g.cal.points.find(x => x.row === i.row); return (q && q.pass) || (s && s.pass); });
  const obs = ['내부표준 면적이 검량 표준 평균(' + n4(d.ref) + ')의 허용 범위를 벗어난 주입은 ' + items.length + '/' + d.total + '개다: ' + items.map(i => i.sampleId + ' ' + p0(i.pct) + '%').join(', ') + '.',
    '해당 주입의 시료 유형: ' + types.map(t => (TYPES[t] || t) + ' ' + d.byType[t] + '개').join(', ') + '.',
    orders.length > 1 ? (consecutive ? '주입 순서상 연속된 구간이다.' : '주입 순서상 흩어져 있다.') + (c.hasOrder ? '' : ' (행 순서를 주입 순서로 가정)') : '',
    c.others.length ? '같은 주입에서 다른 분석물의 내부표준도 벗어난 경우: ' + (shared.length ? shared.join(', ') : '없음') + '.' : '',
    known.length ? '농도를 아는 주입(QC·표준) ' + known.length + '개 중 ' + knownOk.length + '개는 정량 결과가 기준 내다.' : '벗어난 주입은 모두 농도를 모르는 시료라, 내부표준이 변동을 제대로 보정했는지 이 데이터로 확인할 수 없다.'].filter(Boolean);
  const hyps = [
    hyp('시료 매질에 의한 이온 억제 또는 증강', [onlyUnknown ? '표준·QC는 정상이고 매질이 있는 시료에서만 나타난다.' : '', lowN && !highN ? '모두 낮아지는 방향이다.' : ''], [stdAffected ? '매질이 없는 표준·QC에서도 나타난다.' : ''], '내부표준이 분석물과 같은 정도로 억제되는지는 확인되지 않았다. 같다면 면적비는 유지되지만, 다르면 정량값이 치우친다.'),
    hyp('내부표준 첨가 오류(누락, 이중 첨가, 부피 오차)', [!consecutive && items.length <= 3 ? '소수의 주입에서 따로따로 나타난다.' : '', highN ? '일부는 높아지는 방향이다(이중 첨가와 일관).' : ''], [shared.length ? '다른 분석물의 내부표준도 같은 주입에서 변했다. 내부표준을 혼합 용액으로 넣는다면 일관되지만, 개별 첨가라면 맞지 않는다.' : ''], '첨가 오류라면 분석물 면적은 그대로이므로 정량값이 치우친다. 미지 시료에서는 이를 확인할 수 없다.'),
    hyp('주입량 부족 또는 니들·바이알 문제(기포, 시료량 부족)', [lowN && !highN && !stdAffected ? '낮아지는 방향이며 특정 바이알에 국한된다.' : ''], [highN ? '높아진 주입이 있다(주입량 부족으로는 설명되지 않는다).' : ''], '분석물 면적도 같은 비율로 줄었는지는 농도를 아는 시료에서만 확인된다.'),
    hyp('장비 감도의 변화(이온원 오염, 분무 불안정)', [consecutive && items.length >= 3 ? '연속된 주입 구간에서 나타난다.' : '', stdAffected ? '표준·QC를 포함해 시료 유형과 무관하게 나타난다.' : ''], [!consecutive && onlyUnknown ? '시료 유형에 따라 갈리고 주입 순서상 흩어져 있다.' : ''], ''),
  ];
  return { title: '내부표준 응답이 허용 범위를 벗어남', observations: obs, hypotheses: hyps,
    checks: ['내부표준 첨가 기록(혼합 용액인지, 누가 언제 넣었는지)', '해당 바이알의 시료량과 기포', '같은 주입의 분석물 면적이 같은 비율로 변했는지', '시스템 압력과 분무 상태 기록', '해당 시료의 매질 특성(고농도 염, 지질 등)'],
    verifications: ['같은 추출물을 다시 주입: 재현되면 추출물(매질·첨가) 쪽, 재현되지 않으면 주입 쪽 가능성이 커진다', '추출물을 희석해 재분석하고 내부표준 응답이 회복되는지 확인', '해당 시료를 다시 전처리해 분석', 'SOP에 정한 내부표준 응답 기준과 재분석 규정에 따라 처리'],
    conclusion: conclude(hyps, known.length && knownOk.length === known.length ? '농도를 아는 주입에서는 정량 결과가 유지되었지만, 이것이 미지 시료에도 적용된다고 볼 근거는 없다.' : null) };
};

BUILDERS.IS_DRIFT = (f, g, c) => {
  const t = f.details.trend; const drifting = c.others.filter(o => o.tables.isTrend && o.tables.isTrend.p < 0.01 && Math.sign(o.tables.isTrend.changePct) === Math.sign(t.changePct)).map(o => o.analyte);
  const obs = ['주입 순서에 따라 내부표준 면적이 처음 대비 ' + sg(t.changePct, 0) + '% 변했다(선형 추세 p = ' + t.p.toExponential(1) + ', n = ' + t.n + ').' + (c.hasOrder ? '' : ' 행 순서를 주입 순서로 가정했다.'),
    c.others.length ? '같은 방향의 유의한 추세가 있는 다른 분석물: ' + (drifting.length ? drifting.join(', ') : '없음') + '.' : '', c.qcSum.n ? 'QC는 ' + c.qcSum.nPass + '/' + c.qcSum.n + '개가 기준 내다.' : ''].filter(Boolean);
  const hyps = [
    hyp('이온원 오염 누적 또는 감도 저하', [t.changePct < 0 ? '배치가 진행될수록 낮아진다.' : '', drifting.length ? '다른 분석물의 내부표준도 같은 방향이다.' : ''], [t.changePct > 0 ? '높아지는 방향이다.' : ''], ''),
    hyp('시료 추출물의 증발·농축(오토샘플러 대기 중)', [t.changePct > 0 ? '배치가 진행될수록 높아진다.' : ''], [t.changePct < 0 ? '낮아지는 방향이다.' : ''], '오토샘플러 온도와 바이알 밀폐 상태가 입력 데이터에 없다.'),
    hyp('내부표준의 용액 중 불안정', [!drifting.length && c.others.length ? '이 분석물의 내부표준에서만 나타난다.' : ''], [drifting.length ? '다른 내부표준도 함께 변한다.' : ''], ''),
  ];
  return { title: '내부표준 응답이 배치 진행에 따라 표류', observations: obs, hypotheses: hyps, checks: ['배치 전후의 시스템 적합성 시료 응답', '이온원 청소 이력', '오토샘플러 온도와 대기 시간', '주입 순서 기록(이 분석은 ' + (c.hasOrder ? '주입 순서 열' : '행 순서') + '에 의존)'],
    verifications: ['배치 끝에 초기 표준을 다시 주입해 응답 비교', '이온원 세척 후 재측정', '표류가 있어도 면적비가 유지되는지 QC의 시간 순서별 정확도로 확인'], conclusion: conclude(hyps) };
};

BUILDERS.RT_SHIFT = (f, g, c) => {
  const d = f.details; const items = d.items; const dirLate = d.later >= d.earlier; const t = d.trend;
  const max = items.reduce((m, i) => Math.abs(i.delta) > Math.abs(m.delta) ? i : m, items[0]);
  const coShift = c.others.filter(o => o.findings.some(x => x.code === 'RT_SHIFT')).map(o => o.analyte), noShift = c.others.filter(o => !o.findings.some(x => x.code === 'RT_SHIFT') && (o.tables.rtItems || []).length).map(o => o.analyte);
  const types = Object.keys(d.byType); const onlyMatrix = types.every(x => x === 'SAMPLE' || x === 'DUP' || x === 'SPIKE'); const gradual = t && t.p < 0.01;
  const obs = [items.length + '/' + d.total + '개 주입의 머무름 시간이 검량 표준 평균(' + d.ref.toFixed(3) + '분)에서 ±' + d.tol.toFixed(3) + '분 넘게 벗어난다. 늦어진 주입 ' + d.later + '개, 빨라진 주입 ' + d.earlier + '개, 최대 ' + sg(max.delta, 3) + '분(' + max.sampleId + ').',
    t ? '주입 순서에 따른 선형 추세: 배치 전체에서 ' + sg(t.slope * (t.n - 1), 3) + '분 변화, p = ' + t.p.toExponential(1) + (c.hasOrder ? '.' : ' (행 순서를 주입 순서로 가정).') : '',
    '벗어난 주입의 시료 유형: ' + types.map(x => (TYPES[x] || x) + ' ' + d.byType[x] + '개').join(', ') + '.',
    c.others.length ? '같은 배치의 다른 분석물: 이동 있음 ' + (coShift.length ? coShift.join(', ') : '없음') + ' / 이동 없음 ' + (noShift.length ? noShift.join(', ') : '없음') + '.' : ''].filter(Boolean);
  const hyps = [
    hyp('이동상 조성·유량·컬럼 온도의 변화', [coShift.length && !noShift.length ? '모든 분석물이 함께 이동한다.' : '', gradual ? '주입 순서에 따라 점진적으로 변한다.' : ''], [noShift.length ? '이동하지 않은 분석물이 있다(' + noShift.join(', ') + ').' : ''], '압력·온도 기록과 이동상 조제 기록이 없다.'),
    hyp('컬럼의 열화 또는 평형 부족', [gradual ? '점진적인 추세가 있다.' : '', coShift.length ? '여러 분석물에서 나타난다.' : ''], [!gradual ? '추세 없이 일부 주입에서만 나타난다.' : ''], '컬럼 사용 이력이 없다.'),
    hyp('시료 매질의 영향(과부하, 용매 강도 차이)', [onlyMatrix ? '매질이 있는 시료에서만 나타나고 표준·QC는 정상이다.' : ''], [!onlyMatrix ? '표준·QC·바탕에서도 나타난다.' : ''], '시료 용매 조성이 입력 데이터에 없다.'),
    hyp('다른 피크를 분석물로 적분(피크 오인)', [!coShift.length && c.others.length && !gradual ? '이 분석물에서만, 일부 주입에서만 나타난다.' : ''], [coShift.length && !noShift.length ? '모든 분석물이 같은 방향으로 이동한다(개별 오인으로는 설명하기 어렵다).' : ''], '이온비와 크로마토그램이 없어 확인할 수 없다.'),
  ];
  return { title: '머무름 시간이 허용 범위를 벗어남', observations: obs, hypotheses: hyps,
    checks: ['시스템 압력 추이', '이동상 잔량과 조제일, 조성', '컬럼 오븐 온도 기록', '내부표준의 머무름 시간(입력 데이터에 없음)', '확인 이온의 이온비'],
    verifications: ['배치 끝에 표준을 다시 주입해 머무름 시간 확인', '이동이 큰 주입의 크로마토그램에서 피크 모양과 이온비 확인', '컬럼 평형 시간을 늘려 재현 여부 확인', 'SANTE/11312/2021처럼 동위원소 표지 내부표준과 머무름 시간·피크 모양이 일치하면 더 큰 편차를 허용하는 규정도 있으므로 적용 분석법의 조건 확인'],
    conclusion: conclude(hyps, coShift.length && !noShift.length ? '모든 분석물이 함께 이동해 시스템 수준의 변화와 일관되지만, 이동상·온도·컬럼 중 무엇인지는 장비 기록 없이는 구별되지 않는다.' : null) };
};

function precisionCard(f, g, c) {
  const items = f.details.items; const isQc = f.code === 'QC_PRECISION'; const lv = f.details.level;
  let areaRsd = null, respRsd = null, isRsd = null, nearLloq = false;
  if (isQc) { const rows = g.rows.filter(x => items.some(i => i.row === x.rec.row)); areaRsd = rsd(rows.map(x => x.rec.area).filter(isNum)); respRsd = rsd(rows.map(x => x.q.response).filter(isNum)); isRsd = rsd(rows.map(x => x.rec.isArea).filter(isNum)); nearLloq = lv.nominal <= 3 * g.cal.lloq; }
  else { const it = items[0]; areaRsd = it.areaRsd; respRsd = it.responseRsd; isRsd = it.isAreas && it.isAreas.every(isNum) ? rsd(it.isAreas) : null; nearLloq = it.values.some(v => v < 3 * g.cal.lloq); }
  const obs = [isQc ? 'QC ' + n4(lv.nominal) + '의 반복 ' + lv.n + '개: 평균 ' + n4(lv.mean) + ', 표준편차 ' + n4(lv.sd) + ', RSD ' + p1(lv.rsd) + '% (기준 ' + lv.rsdLimit + '% 이하).' : items.map(i => i.sampleId + ': ' + (i.kind === 'dup' ? 'RPD ' + p1(i.rpd) + '%' : 'RSD ' + p1(i.rsd) + '%') + ' (측정값 ' + i.values.map(n4).join(', ') + '; 기준 ' + i.limit + '% 이하)').join(' / ') + '.',
    isNum(areaRsd) ? '같은 측정들의 분석물 원면적 RSD는 ' + p1(areaRsd) + '%' + (isNum(isRsd) ? ', 내부표준 면적 RSD는 ' + p1(isRsd) + '%' : '') + (isNum(respRsd) ? ', 정량에 쓴 응답값 RSD는 ' + p1(respRsd) + '%' : '') + '이다.' : '',
    nearLloq ? '농도가 LLOQ의 3배 이내다.' : '', c.others.length ? '같은 문제가 나타난 다른 분석물: ' + (c.othersWith(f.code).length ? c.othersWith(f.code).join(', ') : '없음') + '.' : ''].filter(Boolean);
  const isStable = isNum(isRsd) && isRsd < 8; const others = c.othersWith(f.code);
  const hyps = [
    hyp('시료 전처리의 변동 또는 시료 불균질', [isStable ? '내부표준 면적은 안정적(RSD ' + p1(isRsd) + '%)인데 분석물만 변한다.' : '', !others.length && c.others.length ? '이 분석물에서만 나타난다.' : ''], [], '반복이 같은 추출물의 재주입인지 독립 전처리인지 입력 데이터에 없다. 재주입이라면 전처리 변동으로는 설명되지 않는다.'),
    hyp('주입·이온화의 변동', [isNum(isRsd) && !isStable ? '내부표준 면적도 함께 변한다(RSD ' + p1(isRsd) + '%).' : ''], [isStable ? '내부표준 면적이 안정적이다. 주입·이온화 변동이라면 내부표준도 함께 변했을 것이다.' : ''], ''),
    hyp('피크 적분의 변동(낮은 신호 대 잡음비, 간섭 피크)', [nearLloq ? '농도가 정량한계에 가깝다.' : ''], [!nearLloq ? '농도가 정량한계보다 충분히 높다.' : ''], '크로마토그램이 없어 확인할 수 없다.'),
    hyp('내부표준 첨가량의 변동', [isNum(isRsd) && !isStable && isNum(areaRsd) && areaRsd < 8 ? '분석물 원면적은 안정적인데 내부표준이 변한다.' : ''], [isStable ? '내부표준 면적이 안정적이다.' : ''], ''),
  ];
  return { title: isQc ? 'QC 반복 측정의 변동이 큼' : '중복·반복 측정의 차이가 큼', observations: obs, hypotheses: hyps,
    checks: ['반복이 재주입인지 독립 전처리인지', '각 측정의 크로마토그램과 적분', '시료의 균질화 방법', '피펫과 자동 분주기의 점검 기록'],
    verifications: ['같은 추출물을 5회 이상 반복 주입해 주입 정밀도를 따로 확인', '같은 시료를 독립적으로 여러 번 전처리해 전처리 정밀도 확인', '적분 조건을 고정하고 재적분했을 때 변동이 줄어드는지 확인'], conclusion: conclude(hyps) };
}
BUILDERS.QC_PRECISION = precisionCard; BUILDERS.DUP_RPD = precisionCard; BUILDERS.REP_RSD = precisionCard;

BUILDERS.QC_ACCURACY = (f, g, c) => {
  const all = (f.details.all || []).slice().sort((a, b) => a.order - b.order); const bad = f.details.items;
  const levels = g.tables.qcLevels; const signs = levels.filter(l => isNum(l.meanRePct)).map(l => Math.sign(l.meanRePct)); const sameDir = signs.length > 1 && signs.every(s => s === signs[0]);
  const half = Math.floor(all.length / 2); const early = mean(all.slice(0, half).map(i => Math.abs(i.rePct))), late = mean(all.slice(half).map(i => Math.abs(i.rePct)));
  const calIssue = g.findings.filter(x => ['CAL_FAIL', 'CAL_NONLINEAR', 'CAL_OUTLIER', 'CAL_POINT_DEV'].includes(x.code)).map(x => x.label);
  const badLevels = Array.from(new Set(bad.map(i => i.nominal)));
  const obs = ['기준을 벗어난 QC: ' + bad.map(i => i.sampleId + ' ' + sg(i.rePct) + '%').join(', ') + '.', '수준별 평균 상대오차: ' + levels.map(l => n4(l.nominal) + ' → ' + sg(l.meanRePct) + '% (RSD ' + p1(l.rsd) + '%, n = ' + l.n + ')').join(', ') + '.',
    all.length >= 4 ? '주입 순서 전반부의 평균 |상대오차|는 ' + p1(early) + '%, 후반부는 ' + p1(late) + '%이다.' : '', '같은 분석물의 검량선 진단: ' + (calIssue.length ? calIssue.join(', ') : '특이 사항 없음') + '.'].filter(Boolean);
  const hyps = [
    hyp('검량선의 치우침(표준 조제, 이상점, 비선형성)', [calIssue.length ? '검량선에 진단 사항이 있다(' + calIssue.join(', ') + ').' : '', sameDir && levels.length > 1 ? '모든 수준이 같은 방향으로 치우친다.' : ''], [!calIssue.length && !sameDir ? '검량선 진단에 특이 사항이 없고 수준마다 방향이 다르다.' : ''], '검량 표준과 QC가 독립된 원액으로 조제되었는지 입력 데이터에 없다.'),
    hyp('QC 시료의 조제 오류 또는 열화', [badLevels.length === 1 && levels.length > 1 ? '한 수준(' + n4(badLevels[0]) + ')에서만 벗어난다.' : ''], [badLevels.length > 1 ? '여러 수준에서 벗어난다.' : ''], 'QC 조제·보관 기록이 없다.'),
    hyp('배치 진행 중의 장비 표류', [all.length >= 4 && late > 2 * early && late > 5 ? '후반부 QC의 오차가 전반부의 2배를 넘는다.' : ''], [all.length >= 4 && late <= 1.5 * early ? '전반부와 후반부의 오차 크기가 비슷하다.' : ''], c.hasOrder ? '' : '행 순서를 주입 순서로 가정했다.'),
    hyp('개별 QC의 전처리·주입 변동', [levels.some(l => isNum(l.rsd) && l.rsd > 10) ? '같은 수준 안에서 반복 간 변동이 크다.' : ''], [levels.every(l => !isNum(l.rsd) || l.rsd <= 5) ? '같은 수준의 반복은 서로 잘 일치한다(무작위 변동보다는 계통 오차 쪽).' : ''], ''),
  ];
  return { title: 'QC 시료의 정확도가 기준을 벗어남', observations: obs, hypotheses: hyps, checks: ['검량 표준과 QC의 원액이 독립적인지', 'QC 조제일과 보관 조건', '해당 QC 주입의 내부표준 응답과 크로마토그램', '배치 내 QC의 시간 순서별 추이'],
    verifications: ['새로 조제한 QC로 재측정', '검량선 문제를 먼저 해결한 뒤 QC를 다시 평가', 'SOP의 배치 재분석 기준에 따라 처리'], conclusion: conclude(hyps) };
};
BUILDERS.QC_BATCH_FAIL = (f, g, c) => ({ title: 'QC 배치 허용 기준 미달', observations: [f.observed + '. 기준: ' + f.criterion + '.'], hypotheses: [],
  checks: ['개별 QC가 벗어난 이유는 "QC 시료의 정확도" 항목의 가설을 본다'], verifications: ['SOP에 따라 이 배치의 시료 결과를 보고할 수 있는지 판단하고, 필요하면 원인을 조사한 뒤 재분석'], conclusion: '이 항목은 판정 결과이며 원인 가설의 대상이 아니다. 원인은 개별 QC 항목에서 다룬다.' });
BUILDERS.QC_MISSING = (f, g, c) => ({ title: '배치에 필수 QC가 없음', observations: f.details.missing.map(m => m.what + ': ' + m.have + '개 있음, 설정된 최소 ' + m.need + '개.'), hypotheses: [],
  checks: ['해당 QC를 실제로 분석했지만 파일에서 빠졌는지', '시료 유형 표기가 달라 다른 유형으로 분류되지 않았는지(Data Import의 유형 지정 확인)', '이 분석법에서 실제로 요구하는 QC 구성(규칙 설정과 일치하는지)'],
  verifications: ['빠진 QC 데이터를 추가해 다시 올리거나, 분석하지 않았다면 해당 항목은 이 배치로 검증할 수 없음을 보고서에 기록'], conclusion: '원인 진단 대상이 아니다. 없는 QC가 평가했을 항목(' + f.details.missing.map(m => m.what).join(', ') + ')은 이 배치에서 검증되지 않은 상태다.' });
BUILDERS.CAL_FAIL = (f, g, c) => ({ title: '검량선이 적합성 기준을 충족하지 못함', observations: [f.observed + '.', '회귀식 ' + (g.cal.equation || '–') + ', R² ' + (g.cal.fit ? g.cal.fit.r2.toFixed(5) : '–') + ', 가중치 ' + g.weighting + ', ' + (g.method === 'internal' ? '내부표준법' : '외부표준법') + '.'], hypotheses: [],
  checks: ['같은 분석물의 비선형성·이상점·설정 진단 항목'], verifications: ['원인을 확인하기 전에는 이 검량선으로 계산한 시료 농도를 보고값으로 쓰지 않는다', '검량점 제외나 범위 조정은 SOP에 따라 사유를 기록하고 수행'], conclusion: '이 항목은 판정 결과다. 원인 후보는 같은 분석물의 검량선 진단 항목에서 다룬다.' });
BUILDERS.CAL_POINT_DEV = (f, g, c) => {
  const items = f.details.items; const lowEnd = items.filter(i => i.nominal <= 3 * g.cal.lloq).length; const wc = g.cal.diagnostics.weightingComparison.filter(w => !w.error);
  const best = wc.slice().sort((a, b) => a.sumAbsRE - b.sumAbsRE)[0]; const sel = wc.find(w => w.selected);
  const related = g.findings.filter(x => x.code === 'CAL_NONLINEAR' || x.code === 'CAL_OUTLIER').map(x => x.label);
  const hyps = [
    hyp('저농도에서의 신호 대 잡음비 부족', [lowEnd === items.length ? '벗어난 점이 모두 LLOQ의 3배 이내다.' : ''], [lowEnd === 0 ? '벗어난 점이 저농도가 아니다.' : ''], ''),
    hyp('가중치 또는 회귀 모형이 데이터의 분산 구조와 맞지 않음', [best && sel && best.scheme !== sel.scheme && best.sumAbsRE < 0.6 * sel.sumAbsRE ? '가중치 ' + best.scheme + '에서 편차 합이 ' + p1(sel.sumAbsRE) + '% → ' + p1(best.sumAbsRE) + '%로 줄어든다.' : ''], [best && sel && best.scheme === sel.scheme ? '선택한 가중치가 편차 합이 가장 작다.' : ''], '가중치는 밸리데이션에서 정한 것을 써야 한다.'),
    hyp('개별 표준의 조제·주입 변동', [items.length === 1 && !related.length ? '한 점만 벗어난다.' : ''], [g.cal.nonlinear ? '같은 검량선에서 곡률이 유의하다. 한 점의 무작위 변동보다는 계통적인 굽음일 수 있다.' : ''], ''),
  ];
  return { title: '일부 검량점의 역산 편차가 기준을 벗어남', observations: ['벗어난 검량점: ' + items.map(i => n4(i.nominal) + ' → ' + sg(i.devPct) + '% (기준 ±' + i.limit + '%)').join(', ') + '.', '가중치별 |편차| 합: ' + wc.map(w => w.scheme + ' ' + p1(w.sumAbsRE) + '%' + (w.selected ? '(선택)' : '')).join(', ') + '.'].concat(related.length ? ['같은 검량선에 다른 진단이 있다: ' + related.join(', ') + '. 그 항목의 가설을 먼저 본다.'] : []), hypotheses: hyps,
    checks: ['벗어난 점의 크로마토그램과 적분', '분석법에 정해진 가중치와 회귀 모형', '벗어난 점이 범위의 어느 쪽에 몰려 있는지'], verifications: ['해당 수준을 다시 주입하거나 새로 조제해 측정', '가중치·모형 설정을 분석법 문서와 대조'], conclusion: conclude(hyps) };
};

function genericCard(f) { return { title: f.label, observations: [f.observed + (f.criterion && f.criterion !== '–' ? ' (기준: ' + f.criterion + ')' : '')], hypotheses: [], checks: [], verifications: [], conclusion: f.code.startsWith('CAL_CONFIG') || f.code === 'CAL_NO_STANDARDS' ? '설정 또는 데이터 구성의 문제로 보인다. 원인 가설이 아니라 설정 확인이 필요하다.' : '이 항목에는 원인 가설을 만들지 않았다.' }; }

// 결과 전체에 대한 진단 카드 목록. fail·warn만 대상으로 한다.
export function diagnose(result) {
  const cards = [];
  for (const g of result.groups) {
    const c = ctxOf(result, g);
    for (const f of g.findings) {
      if (f.severity === 'info') continue;
      const b = BUILDERS[f.code]; const card = b ? b(f, g, c) : genericCard(f);
      cards.push(Object.assign({ id: 'D|' + f.id, findingId: f.id, code: f.code, label: f.label, severity: f.severity, batchId: g.batchId, analyte: g.analyte, causeStatus: '원인 미확정' }, card));
    }
  }
  return cards;
}

// 결정론적 요약(문장 틀 + 계산값). LLM을 쓰지 않는다.
export function summarize(result) {
  const d = result.dashboard; const lines = [];
  lines.push('배치 ' + d.batches + '개, 분석물 ' + d.analytes + '종, 데이터 ' + d.rows + '행을 분석했다. 기준 미충족 ' + d.fail + '건, 주의 ' + d.warn + '건, 참고 ' + d.info + '건이며 검토가 필요한 시료는 ' + d.reviewSamples + '개다.');
  for (const b of result.batches) {
    const gs = result.groups.filter(g => g.batchId === b); const parts = [];
    for (const g of gs) { const fs = g.findings.filter(f => f.severity !== 'info'); parts.push(g.analyte + ': 검량선 ' + (g.cal.verdict === 'pass' ? '적합' : g.cal.verdict === 'fail' ? '부적합' : '평가 불가') + (fs.length ? ', ' + Array.from(new Set(fs.filter(f => !f.code.startsWith('CAL_FAIL')).map(f => f.label))).join('·') : ', 경고 없음')); }
    lines.push(b + ' — ' + parts.join(' / '));
  }
  return lines;
}
