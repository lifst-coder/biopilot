// BIOPILOT — 결정론적 통계 함수. LLM이나 난수에 의존하지 않는다. 모든 함수는 순수 함수다.

export function isNum(v) { return typeof v === 'number' && Number.isFinite(v); }
// 기준값과의 비교. 부동소수점 오차 때문에 경계값(예: 정확히 15.0%)이 부적합으로 뒤집히지 않도록 아주 작은 여유를 둔다.
export function lte(a, b) { return a <= b + 1e-9 * Math.max(1, Math.abs(b)); }
export function gte(a, b) { return a >= b - 1e-9 * Math.max(1, Math.abs(b)); }
export function mean(a) { if (!a.length) return NaN; let s = 0; for (const v of a) s += v; return s / a.length; }
// 표본 표준편차(n−1). n < 2이면 NaN.
export function sd(a) { const n = a.length; if (n < 2) return NaN; const m = mean(a); let s = 0; for (const v of a) s += (v - m) * (v - m); return Math.sqrt(s / (n - 1)); }
// 상대표준편차(%) = SD / |평균| × 100. 평균이 0이면 NaN.
export function rsd(a) { const m = mean(a); const s = sd(a); return (isNum(s) && m !== 0) ? s / Math.abs(m) * 100 : NaN; }
export function median(a) { if (!a.length) return NaN; const v = a.slice().sort((x, y) => x - y); const h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2; }
// 상대오차(%) = (측정 − 기준) / 기준 × 100
export function relError(measured, nominal) { return (isNum(measured) && isNum(nominal) && nominal !== 0) ? (measured - nominal) / nominal * 100 : NaN; }
// 상대 백분율 차이 RPD(%) = |a − b| / ((a + b)/2) × 100
export function rpd(a, b) { const m = (a + b) / 2; return (isNum(a) && isNum(b) && m !== 0) ? Math.abs(a - b) / Math.abs(m) * 100 : NaN; }
export function recovery(measured, added, background) { const bg = isNum(background) ? background : 0; return (isNum(measured) && isNum(added) && added !== 0) ? (measured - bg) / added * 100 : NaN; }

// ── 가중치 ──
export const WEIGHTINGS = ['none', '1/x', '1/x2', '1/y', '1/y2'];
export const WEIGHTING_LABEL = { 'none': '가중 없음', '1/x': '1/x', '1/x2': '1/x²', '1/y': '1/y', '1/y2': '1/y²' };
// 가중치 벡터. 적용할 수 없는 점(x ≤ 0 또는 y ≤ 0)이 있으면 { error }를 돌려준다.
export function weights(x, y, scheme) {
  const w = [];
  for (let i = 0; i < x.length; i++) {
    let v;
    if (scheme === 'none') v = 1;
    else if (scheme === '1/x') { if (!(x[i] > 0)) return { error: '가중치 1/x는 농도가 0 이하인 점에 적용할 수 없습니다.' }; v = 1 / x[i]; }
    else if (scheme === '1/x2') { if (!(x[i] > 0)) return { error: '가중치 1/x²는 농도가 0 이하인 점에 적용할 수 없습니다.' }; v = 1 / (x[i] * x[i]); }
    else if (scheme === '1/y') { if (!(y[i] > 0)) return { error: '가중치 1/y는 응답값이 0 이하인 점에 적용할 수 없습니다.' }; v = 1 / y[i]; }
    else if (scheme === '1/y2') { if (!(y[i] > 0)) return { error: '가중치 1/y²는 응답값이 0 이하인 점에 적용할 수 없습니다.' }; v = 1 / (y[i] * y[i]); }
    else return { error: '알 수 없는 가중치: ' + scheme };
    w.push(v);
  }
  return { w };
}

// ── 가중 선형 회귀 y = slope·x + intercept ──
// 반환: slope, intercept, r2(가중 결정계수), n, sse(가중 잔차제곱합), s(잔차 표준오차), seSlope, seIntercept, leverage[], fitted[], residuals[]
export function wls(x, y, w) {
  const n = x.length;
  if (n !== y.length || n !== w.length) return { error: '입력 길이가 다릅니다.' };
  if (n < 2) return { error: '회귀에는 최소 2개 점이 필요합니다.' };
  let W = 0, sx = 0, sy = 0;
  for (let i = 0; i < n; i++) { if (!isNum(x[i]) || !isNum(y[i]) || !(w[i] > 0)) return { error: '유효하지 않은 값이 있습니다.' }; W += w[i]; sx += w[i] * x[i]; sy += w[i] * y[i]; }
  const xb = sx / W, yb = sy / W; let sxx = 0, sxy = 0, sst = 0;
  for (let i = 0; i < n; i++) { const dx = x[i] - xb, dy = y[i] - yb; sxx += w[i] * dx * dx; sxy += w[i] * dx * dy; sst += w[i] * dy * dy; }
  if (!(sxx > 0)) return { error: '농도가 모두 같아 기울기를 계산할 수 없습니다.' };
  const slope = sxy / sxx, intercept = yb - slope * xb;
  const fitted = [], residuals = [], leverage = []; let sse = 0;
  for (let i = 0; i < n; i++) { const f = slope * x[i] + intercept; fitted.push(f); residuals.push(y[i] - f); sse += w[i] * (y[i] - f) * (y[i] - f); leverage.push(w[i] * (1 / W + (x[i] - xb) * (x[i] - xb) / sxx)); }
  const df = n - 2; const s = df > 0 ? Math.sqrt(sse / df) : NaN;
  return { slope, intercept, r2: sst > 0 ? 1 - sse / sst : NaN, n, df, sse, sst, s, seSlope: df > 0 ? s / Math.sqrt(sxx) : NaN,
    seIntercept: df > 0 ? s * Math.sqrt(1 / W + xb * xb / sxx) : NaN, fitted, residuals, leverage, xbar: xb, ybar: yb };
}
// 외적 스튜던트화 잔차(각 점을 뺀 회귀의 잔차 척도 기준). df = n − 3.
export function studentized(fit, w) {
  const n = fit.n, out = [];
  for (let i = 0; i < n; i++) {
    const h = Math.min(fit.leverage[i], 1 - 1e-12);
    const r = Math.sqrt(w[i]) * fit.residuals[i] / (fit.s * Math.sqrt(1 - h));
    const denom = n - 2 - r * r;
    out.push((n > 3 && denom > 0) ? r * Math.sqrt((n - 3) / denom) : (isNum(r) ? Math.sign(r) * Infinity : NaN));
  }
  return out;
}

// ── 가중 2차 회귀 y = a + b·x + c·x² (비선형성 진단 전용. 정량에는 쓰지 않는다) ──
export function wlsQuadratic(x, y, w) {
  const n = x.length; if (n < 4) return { error: '2차 항 검정에는 최소 4개 점이 필요합니다.' };
  // 수치 안정성을 위해 x를 최댓값으로 나눠 척도화한다.
  const xm = Math.max.apply(null, x.map(Math.abs)) || 1;
  const S = [0, 0, 0, 0, 0], T = [0, 0, 0];
  for (let i = 0; i < n; i++) { const u = x[i] / xm; let p = w[i]; for (let k = 0; k < 5; k++) { S[k] += p; if (k < 3) T[k] += p * y[i]; p *= u; } }
  const A = [[S[0], S[1], S[2], T[0]], [S[1], S[2], S[3], T[1]], [S[2], S[3], S[4], T[2]]];
  for (let c = 0; c < 3; c++) {           // 부분 피벗 가우스 소거
    let p = c; for (let r = c + 1; r < 3; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-300) return { error: '2차 회귀 행렬이 특이합니다(농도 수준이 3개 미만).' };
    const t = A[c]; A[c] = A[p]; A[p] = t;
    for (let r = 0; r < 3; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let k = c; k < 4; k++) A[r][k] -= f * A[c][k]; }
  }
  const a = A[0][3] / A[0][0], bu = A[1][3] / A[1][1], cu = A[2][3] / A[2][2];
  let sse = 0; for (let i = 0; i < n; i++) { const u = x[i] / xm; const f = a + bu * u + cu * u * u; sse += w[i] * (y[i] - f) * (y[i] - f); }
  return { a, b: bu / xm, c: cu / (xm * xm), sse, n, df: n - 3 };
}
// 선형 모형에 2차 항을 추가했을 때의 F 검정. p가 작으면 직선으로 설명되지 않는 곡률이 있다.
export function curvatureTest(x, y, w) {
  const lin = wls(x, y, w); if (lin.error) return { error: lin.error };
  const q = wlsQuadratic(x, y, w); if (q.error) return { error: q.error };
  if (!(q.df > 0)) return { error: '자유도가 부족합니다.' };
  const F = q.sse > 0 ? (lin.sse - q.sse) / (q.sse / q.df) : Infinity;
  const p = F === Infinity ? 0 : 2 * (1 - tCdf(Math.sqrt(Math.max(0, F)), q.df));
  const xmax = Math.max.apply(null, x);
  // 곡률의 크기: 최고 농도에서 2차 항이 1차 항에 대해 차지하는 비율(%)
  const curvaturePct = (q.b !== 0) ? (q.c * xmax * xmax) / (q.b * xmax) * 100 : NaN;
  return { F, p, df: q.df, quad: q, curvaturePct };
}

// ── 분포 함수 ──
function lgamma(z) {
  const g = 7, c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - lgamma(1 - z);
  z -= 1; let x = c[0]; for (let i = 1; i < g + 2; i++) x += c[i] / (z + i);
  const t = z + g + 0.5; return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}
// 정규화 불완전 베타 함수 I_x(a, b) (연분수 전개)
export function incBeta(x, a, b) {
  if (x <= 0) return 0; if (x >= 1) return 1;
  const bt = Math.exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log(1 - x));
  const cf = (xx, aa, bb) => {
    const EPS = 1e-14, FPMIN = 1e-300; let c = 1, d = 1 - (aa + bb) * xx / (aa + 1); if (Math.abs(d) < FPMIN) d = FPMIN; d = 1 / d; let h = d;
    for (let m = 1; m <= 300; m++) {
      const m2 = 2 * m; let an = m * (bb - m) * xx / ((aa + m2 - 1) * (aa + m2));
      d = 1 + an * d; if (Math.abs(d) < FPMIN) d = FPMIN; c = 1 + an / c; if (Math.abs(c) < FPMIN) c = FPMIN; d = 1 / d; h *= d * c;
      an = -(aa + m) * (aa + bb + m) * xx / ((aa + m2) * (aa + m2 + 1));
      d = 1 + an * d; if (Math.abs(d) < FPMIN) d = FPMIN; c = 1 + an / c; if (Math.abs(c) < FPMIN) c = FPMIN; d = 1 / d; const del = d * c; h *= del;
      if (Math.abs(del - 1) < EPS) break;
    }
    return h;
  };
  return x < (a + 1) / (a + b + 2) ? bt * cf(x, a, b) / a : 1 - bt * cf(1 - x, b, a) / b;
}
// 스튜던트 t 누적분포
export function tCdf(t, df) {
  if (!isNum(t)) return t > 0 ? 1 : (t < 0 ? 0 : NaN);
  if (!(df > 0)) return NaN;
  const x = df / (df + t * t); const p = 0.5 * incBeta(x, df / 2, 0.5);
  return t >= 0 ? 1 - p : p;
}
export function tTwoSidedP(t, df) { return isNum(t) ? 2 * (1 - tCdf(Math.abs(t), df)) : (Math.abs(t) === Infinity ? 0 : NaN); }

// 단순 선형 추세(비가중)와 기울기의 p값. 주입 순서에 따른 표류 판단에 쓴다.
export function trend(x, y) {
  const n = x.length; if (n < 4) return { error: '추세 평가에는 최소 4개 점이 필요합니다.' };
  const f = wls(x, y, x.map(() => 1)); if (f.error) return { error: f.error };
  const t = f.seSlope > 0 ? f.slope / f.seSlope : (f.slope === 0 ? 0 : Infinity);
  const first = f.intercept + f.slope * Math.min.apply(null, x), last = f.intercept + f.slope * Math.max.apply(null, x);
  return { slope: f.slope, intercept: f.intercept, p: tTwoSidedP(t, n - 2), changePct: first !== 0 ? (last - first) / Math.abs(first) * 100 : NaN, n };
}

// 재현 가능한 난수(합성 데이터 전용)
export function rng(seed) {
  let a = seed >>> 0;
  const u = () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const normal = () => { let p = 0; while (p === 0) p = u(); return Math.sqrt(-2 * Math.log(p)) * Math.cos(2 * Math.PI * u()); };
  return { u, normal };
}
