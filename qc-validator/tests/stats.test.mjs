// 계산 단위 시험. 기준값은 NumPy/SciPy로 따로 계산한 값이다(scripts 밖의 독립 구현).
import test from 'node:test';
import assert from 'node:assert/strict';
import { mean, sd, rsd, median, relError, rpd, recovery, weights, wls, studentized, curvatureTest, tCdf, tTwoSidedP, incBeta, trend, rng, WEIGHTINGS } from '../src/stats.js';

const X = [1, 2, 5, 10, 50, 100, 250, 500], Y = [0.0102, 0.0195, 0.0519, 0.0987, 0.512, 0.985, 2.61, 4.93];
const REF = {
  'none': { slope: 0.009942288075636007, intercept: 0.011284943320768289, r2: 0.9992425589194889 },
  '1/x': { slope: 0.010039324603687567, intercept: 0.00015000172685154483, r2: 0.9992946152871482 },
  '1/x2': { slope: 0.01007182479144818, intercept: 8.388708286793088e-06, r2: 0.9990648105889331 },
  '1/y': { slope: 0.010032629283447642, intercept: 0.00015159322620424712, r2: 0.999308205981331 },
  '1/y2': { slope: 0.01005795554579626, intercept: 1.364925086414736e-05, r2: 0.9990686200628013 },
};
const near = (a, b, rel) => assert.ok(Math.abs(a - b) <= (rel || 1e-9) * Math.max(1, Math.abs(b)), a + ' ≠ ' + b);

test('기술통계: 평균·표준편차(n−1)·RSD', () => {
  const a = [98.2, 101.5, 99.7, 103.1, 97.4];
  near(mean(a), 99.98); near(sd(a), 2.342434630891539); near(rsd(a), 2.342903211533846);
  assert.ok(Number.isNaN(sd([5]))); assert.ok(Number.isNaN(mean([]))); assert.ok(Number.isNaN(rsd([0, 0, 0])));
  assert.equal(median([3, 1, 2]), 2); assert.equal(median([4, 1, 2, 3]), 2.5);
});
test('상대오차·RPD·회수율', () => {
  near(relError(115, 100), 15); near(relError(85, 100), -15); assert.ok(Number.isNaN(relError(1, 0)));
  near(rpd(110, 90), 20); near(rpd(90, 110), 20); assert.ok(Number.isNaN(rpd(0, 0)));
  near(recovery(45, 50), 90); near(recovery(60, 50, 12), 96); assert.ok(Number.isNaN(recovery(10, 0)));
});
for (const scheme of WEIGHTINGS) test('가중 선형 회귀 ' + scheme + ': 기울기·절편·R²가 NumPy 기준값과 일치', () => {
  const w = weights(X, Y, scheme).w; const f = wls(X, Y, w);
  near(f.slope, REF[scheme].slope, 1e-10); near(f.intercept, REF[scheme].intercept, 1e-9); near(f.r2, REF[scheme].r2, 1e-10);
});
test('가중치: 농도 0에는 1/x를, 응답 0에는 1/y를 적용할 수 없다', () => {
  assert.match(weights([0, 1], [1, 2], '1/x').error, /0 이하/); assert.match(weights([1, 2], [0, 2], '1/y2').error, /0 이하/);
  assert.match(weights([1], [1], 'bogus').error, /알 수 없는/); assert.deepEqual(weights([0, 1], [0, 1], 'none').w, [1, 1]);
});
test('회귀: 잘못된 입력은 오류를 돌려주고 값을 만들지 않는다', () => {
  assert.ok(wls([1], [1], [1]).error); assert.ok(wls([2, 2, 2], [1, 2, 3], [1, 1, 1]).error); assert.ok(wls([1, 2], [1, NaN], [1, 1]).error); assert.ok(wls([1, 2], [1, 2], [1, 0]).error);
});
test('회귀: 완전한 직선은 R² = 1, 잔차 0', () => {
  const x = [1, 2, 3, 4], y = x.map(v => 3 * v + 2); const f = wls(x, y, [1, 1, 1, 1]);
  near(f.slope, 3); near(f.intercept, 2); near(f.r2, 1); assert.ok(f.residuals.every(r => Math.abs(r) < 1e-12));
});
test('곡률 검정: 직선 데이터는 유의하지 않고, 기준값(F, p)과 일치', () => {
  const c = curvatureTest(X, Y, weights(X, Y, '1/x2').w);
  near(c.F, 0.04678207982380512, 1e-6); near(c.p, 0.8373078527202982, 1e-6); near(c.quad.c, -1.6584824556670962e-07, 1e-6); near(c.quad.b, 0.01009963072714849, 1e-8);
});
test('곡률 검정: 포화 곡선은 유의하고 방향이 음수', () => {
  const y = X.map(v => 0.01 * v / (1 + v / 1000)); const c = curvatureTest(X, y, weights(X, y, '1/x2').w);
  assert.ok(c.p < 0.001); assert.ok(c.curvaturePct < -15);
});
test('t 분포 누적확률이 SciPy 값과 일치', () => {
  near(tCdf(2.228138852, 10), 0.975, 1e-8); near(tCdf(1, 3), 0.8044988905221148, 1e-9); near(tCdf(-2, 7), 0.04280966428148802, 1e-9); near(tTwoSidedP(3.5, 5), 0.01728443178529335, 1e-9);
  near(tCdf(0, 4), 0.5); assert.equal(tTwoSidedP(Infinity, 5), 0); near(incBeta(0.5, 2, 2), 0.5);
});
test('스튜던트화 잔차: 한 점만 벗어난 경우 그 점이 가장 크다', () => {
  const x = [1, 2, 3, 4, 5, 6, 7, 8], y = x.map(v => 2 * v + 0.01 * ((v * 7) % 3 - 1)); y[4] += 3;
  const w = x.map(() => 1); const f = wls(x, y, w); const t = studentized(f, w).map(Math.abs);
  assert.equal(t.indexOf(Math.max.apply(null, t)), 4); assert.ok(t[4] > 10);
});
test('추세: 단조 증가는 유의, 4점 미만은 평가하지 않음', () => {
  const t = trend([1, 2, 3, 4, 5, 6], [100, 111, 119, 131, 140, 152]); assert.ok(t.p < 0.001); assert.ok(t.changePct > 40 && t.changePct < 60);
  assert.ok(trend([1, 2, 3], [1, 2, 3]).error);
});
test('난수 발생기는 seed가 같으면 같은 수열', () => {
  const a = rng(42), b = rng(42), c = rng(43); const s1 = [a.u(), a.normal(), a.u()], s2 = [b.u(), b.normal(), b.u()];
  assert.deepEqual(s1, s2); assert.notEqual(c.u(), s1[0]);
});
