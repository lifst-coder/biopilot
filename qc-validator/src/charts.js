// BIOPILOT — 의존성 없는 SVG 점 그래프. 검량선, 잔차(역산 편차), 주입 순서별 추이에 쓴다. 색은 CSS 토큰을 따른다.
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
function niceTicks(lo, hi, count) {
  if (!(hi > lo)) { const pad = Math.abs(lo) > 0 ? Math.abs(lo) * 0.1 : 1; lo -= pad; hi += pad; }
  const raw = (hi - lo) / Math.max(1, count); const mag = Math.pow(10, Math.floor(Math.log10(raw))); const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag; const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step; const ticks = [];
  for (let v = a; v <= b + step * 1e-6; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  return { ticks, min: a, max: b };
}
function logTicks(lo, hi) { const a = Math.floor(Math.log10(lo) + 1e-9), b = Math.ceil(Math.log10(hi) - 1e-9); const ticks = []; for (let e = a; e <= b; e++) ticks.push(Math.pow(10, e)); return { ticks, min: Math.pow(10, a), max: Math.pow(10, b) }; }
const tickText = v => { const a = Math.abs(v); if (a === 0) return '0'; if (a >= 1e5 || a < 1e-3) return v.toExponential(0).replace('e+', 'e'); return Number(v.toPrecision(4)).toString(); };

// opts: { points:[{x,y,state:'ok'|'bad'|'off',tip}], lines:[{x1,y1,x2,y2,cls}], fn:{f(x), cls}, hlines:[{y,cls,label}], steps:[{x1,x2,y,cls}], xLog, yLog, xLabel, yLabel, height, ariaLabel, yPad }
export function pointChart(host, opts) {
  const tip = document.createElement('div'); tip.className = 'chart-tip'; tip.hidden = true;
  const wrap = document.createElement('div'); host.innerHTML = ''; host.classList.add('chart'); host.appendChild(wrap); host.appendChild(tip);
  function draw() {
    const o = opts; const W = Math.max(260, Math.floor(host.clientWidth || 480)), H = o.height || 250; const m = { l: 58, r: 14, t: 12, b: 40 }; const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const xs = o.points.map(p => p.x).filter(v => !o.xLog || v > 0), ys = o.points.map(p => p.y).filter(v => !o.yLog || v > 0);
    for (const h of o.hlines || []) ys.push(h.y); for (const s of o.steps || []) ys.push(s.y);
    if (!xs.length || !ys.length) { wrap.innerHTML = '<p class="note">표시할 점이 없습니다.</p>'; return; }
    let x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (!o.xLog) { const pad = (x1 - x0) * 0.04 || 1; x0 = o.xZero ? Math.min(0, x0) : x0 - pad; x1 += pad; }
    if (!o.yLog) { const pad = (y1 - y0) * (o.yPad || 0.08) || 1; y0 = o.yZero ? Math.min(0, y0) : y0 - pad; y1 += pad; }
    const xt = o.xLog ? logTicks(x0 * 0.8, x1 * 1.25) : niceTicks(x0, x1, W < 380 ? 4 : 6), yt = o.yLog ? logTicks(y0 * 0.8, y1 * 1.25) : niceTicks(y0, y1, 5);
    const sx = v => o.xLog ? Math.log10(v) : v, sy = v => o.yLog ? Math.log10(v) : v;
    const X = v => m.l + iw * (sx(v) - sx(xt.min)) / (sx(xt.max) - sx(xt.min)), Y = v => m.t + ih * (1 - (sy(v) - sy(yt.min)) / (sy(yt.max) - sy(yt.min)));
    let g = '';
    for (const t of yt.ticks) g += '<line class="grid" x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + Y(t).toFixed(1) + '" y2="' + Y(t).toFixed(1) + '"/><text class="tick" x="' + (m.l - 6) + '" y="' + (Y(t) + 3.5).toFixed(1) + '" text-anchor="end">' + esc(tickText(t)) + '</text>';
    for (const t of xt.ticks) g += '<line class="grid" x1="' + X(t).toFixed(1) + '" x2="' + X(t).toFixed(1) + '" y1="' + m.t + '" y2="' + (m.t + ih) + '"/><text class="tick" x="' + X(t).toFixed(1) + '" y="' + (m.t + ih + 14) + '" text-anchor="middle">' + esc(tickText(t)) + '</text>';
    g += '<text class="axis-title" x="' + (m.l + iw / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' + esc(o.xLabel || '') + '</text><text class="axis-title" transform="translate(12 ' + (m.t + ih / 2) + ') rotate(-90)" text-anchor="middle">' + esc(o.yLabel || '') + '</text>';
    const clipId = 'c' + Math.random().toString(36).slice(2, 9);
    g += '<clipPath id="' + clipId + '"><rect x="' + m.l + '" y="' + m.t + '" width="' + iw + '" height="' + ih + '"/></clipPath><g clip-path="url(#' + clipId + ')">';
    for (const h of o.hlines || []) g += '<line class="' + (h.cls || 'limit') + '" x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + Y(h.y).toFixed(1) + '" y2="' + Y(h.y).toFixed(1) + '"/>';
    for (const s of o.steps || []) g += '<line class="' + (s.cls || 'limit') + '" x1="' + X(s.x1).toFixed(1) + '" x2="' + X(s.x2).toFixed(1) + '" y1="' + Y(s.y).toFixed(1) + '" y2="' + Y(s.y).toFixed(1) + '"/>';
    if (o.fn) { let d = ''; const N = 80; for (let i = 0; i <= N; i++) { const xv = o.xLog ? Math.pow(10, sx(xt.min) + (sx(xt.max) - sx(xt.min)) * i / N) : xt.min + (xt.max - xt.min) * i / N; const yv = o.fn.f(xv); if (o.yLog && !(yv > 0)) continue; d += (d ? 'L' : 'M') + X(xv).toFixed(1) + ' ' + Y(yv).toFixed(1); } g += '<path class="' + (o.fn.cls || 'fit') + '" d="' + d + '" fill="none"/>'; }
    g += '</g>';
    for (const h of o.hlines || []) if (h.label) g += '<text class="limit-label" x="' + (m.l + iw - 4) + '" y="' + (Y(h.y) - 4).toFixed(1) + '" text-anchor="end">' + esc(h.label) + '</text>';
    const pts = o.points.map((p, i) => ({ p, i, cx: (!o.xLog || p.x > 0) ? X(p.x) : null, cy: (!o.yLog || p.y > 0) ? Y(p.y) : null })).filter(q => q.cx != null && q.cy != null);
    for (const q of pts) {
      const c = q.cx.toFixed(1) + ' ' + q.cy.toFixed(1);
      if (q.p.state === 'bad') g += '<path class="pt pt-bad" d="M' + q.cx.toFixed(1) + ' ' + (q.cy - 6).toFixed(1) + 'L' + (q.cx + 6).toFixed(1) + ' ' + q.cy.toFixed(1) + 'L' + q.cx.toFixed(1) + ' ' + (q.cy + 6).toFixed(1) + 'L' + (q.cx - 6).toFixed(1) + ' ' + q.cy.toFixed(1) + 'Z"/>';
      else if (q.p.state === 'off') g += '<circle class="pt pt-off" cx="' + q.cx.toFixed(1) + '" cy="' + q.cy.toFixed(1) + '" r="4.5"/>';
      else g += '<circle class="pt pt-ok" cx="' + q.cx.toFixed(1) + '" cy="' + q.cy.toFixed(1) + '" r="4.5"/>';
      void c;
    }
    g += '<rect class="hit" x="' + m.l + '" y="' + m.t + '" width="' + iw + '" height="' + ih + '" fill="transparent"/>';
    wrap.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(o.ariaLabel || '') + '">' + g + '</svg>';
    const svg = wrap.firstChild; const hit = svg.querySelector('.hit');
    const move = ev => { const r = svg.getBoundingClientRect(); const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left, py = (ev.touches ? ev.touches[0].clientY : ev.clientY) - r.top; let best = null, bd = 30 * 30;
      for (const q of pts) { const d = (q.cx - px) * (q.cx - px) + (q.cy - py) * (q.cy - py); if (d < bd) { bd = d; best = q; } }
      if (!best) { tip.hidden = true; return; } tip.innerHTML = best.p.tip || ''; tip.hidden = false; const tw = tip.offsetWidth; let left = best.cx + 12; if (left + tw > W - 4) left = best.cx - tw - 12; tip.style.left = Math.max(0, left) + 'px'; tip.style.top = Math.max(0, best.cy - 10) + 'px'; };
    hit.addEventListener('mousemove', move); hit.addEventListener('mouseleave', () => { tip.hidden = true; }); hit.addEventListener('touchstart', move, { passive: true });
  }
  draw(); let lastW = host.clientWidth;
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => { if (host.clientWidth !== lastW && host.clientWidth > 0) { lastW = host.clientWidth; draw(); } }).observe(host);
}
