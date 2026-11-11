// BIOPILOT — 브라우저 통합 시험. 헤드리스 Chrome으로 dist/index.html을 열어 실제 파일 업로드와 화면 조작을 재현한다.
//   node tests/browser.mjs [폭]
import { readFileSync, writeFileSync, existsSync, mkdtempSync, rmSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..'); const width = Number(process.argv[2]) || 1280;
const CHROME = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(c => c && existsSync(c));
if (!CHROME) { console.log('Chrome/Edge를 찾지 못했습니다. CHROME_PATH 환경변수로 실행 파일 경로를 지정하세요.'); process.exit(2); }
const b64 = p => readFileSync(join(root, p)).toString('base64');
const FIX = { csv: b64('data/scenarios/S4_B04-SPIKE.csv'), xlsx: b64('data/test_inputs/excel_saved_S2.xlsx'), cp949: b64('data/test_inputs/korean_headers_cp949.csv'), bad: b64('data/test_inputs/bad_values.csv'), missing: b64('data/test_inputs/missing_required_column.csv'), xls: b64('data/test_inputs/legacy_format.xls'), nois: b64('data/test_inputs/no_is_no_rt_columns.csv') };

const probe = `
<script>
(function () {
  var FIX = ${JSON.stringify(FIX)};
  var errors = [], out = [];
  window.addEventListener('error', function (e) { errors.push(String(e.message)); });
  window.addEventListener('unhandledrejection', function (e) { errors.push('rejection: ' + String(e.reason && e.reason.message || e.reason)); });
  var $ = function (id) { return document.getElementById(id); };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var flush = function (done) { var pre = $('__test') || document.body.appendChild(Object.assign(document.createElement('pre'), { id: '__test', hidden: true })); pre.textContent = JSON.stringify(done ? out : out.concat([{ name: '시험이 끝까지 실행되지 않음', ok: false, detail: errors.join(' | ') }])); };
  var check = function (name, ok, detail) { out.push({ name: name, ok: !!ok, detail: detail === undefined ? '' : String(detail) }); flush(false); };
  var bytes = function (b) { var s = atob(b), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; };
  var upload = async function (name, b) { var dt = new DataTransfer(); dt.items.add(new File([bytes(b)], name)); var inp = $('file-input'); inp.files = dt.files; inp.dispatchEvent(new Event('change', { bubbles: true })); await wait(700); };
  var setVal = function (el, v) { el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); };
  var txt = function (id) { return $(id).textContent; };
  var overflow = function () { return document.documentElement.scrollWidth - window.innerWidth; };
  var tiles = function () { return Array.prototype.map.call(document.querySelectorAll('#dash-tiles .t-val'), function (e) { return e.textContent; }); };
  async function run() {
    await wait(300);
    check('시작 상태: 합성 예시 데이터로 대시보드가 채워짐', tiles().join(',').indexOf('9,3,') === 0, tiles().join(','));
    check('Dashboard: 배치 × 분석물 표 9행 3열', document.querySelectorAll('#dash-matrix tbody tr').length === 9 && document.querySelectorAll('#dash-matrix thead th').length === 4);
    check('Dashboard: 예시 데이터 표시', txt('source-strip').indexOf('합성 예시 데이터') >= 0);
    check('Dashboard: 검토 필요 시료 목록', document.querySelectorAll('#dash-review tbody tr').length === Number(tiles()[3]), tiles()[3]);
    check('Dashboard: 가로 넘침 없음', overflow() <= 0, overflow());

    // ── 실제 파일 업로드 ──
    $('tab-import').click(); await wait(100);
    await upload('S4_B04-SPIKE.csv', FIX.csv);
    check('업로드(CSV): 파일 정보와 13개 항목 매핑 표', txt('import-body').indexOf('S4_B04-SPIKE.csv') >= 0 && document.querySelectorAll('#import-body [data-map]').length === 13);
    check('업로드(CSV): 자동 매핑이 모두 연결됨', document.querySelectorAll('#import-body .maprow .pill.fail').length === 0 && $('map-area').value === '6' && $('map-isArea').value === '7');
    check('업로드(CSV): 미리보기 15행', document.querySelectorAll('#import-body .panel:last-child tbody tr').length === 15);
    check('업로드(CSV): 예시 표시가 사라짐', txt('source-strip').indexOf('합성 예시') < 0 && txt('source-strip').indexOf('S4_B04-SPIKE.csv') >= 0);
    $('tab-dashboard').click(); await wait(150);
    check('업로드(CSV): 분석 결과 반영(배치 1, 분석물 3, 낮은 회수율 탐지)', tiles()[0] === '1' && tiles()[1] === '3' && txt('dash-top').indexOf('첨가 회수율 낮음') >= 0, tiles().join(','));

    $('tab-import').click(); await wait(50); await upload('excel_saved_S2.xlsx', FIX.xlsx);
    check('업로드(XLSX, Excel 저장본): 읽기 성공', txt('import-body').indexOf('XLSX') >= 0 && txt('import-error') === '', txt('import-error'));
    $('tab-dashboard').click(); await wait(150);
    check('업로드(XLSX): 검량점 이상치 탐지', txt('dash-top').indexOf('검량점 이상치 후보') >= 0);

    $('tab-import').click(); await wait(50); await upload('legacy.xls', FIX.xls);
    check('지원하지 않는 형식(.xls): 오류 표시, 기존 데이터 유지', txt('import-error').indexOf('지원하지 않는 형식') >= 0 && txt('source-strip').indexOf('excel_saved_S2.xlsx') >= 0, txt('import-error').slice(0, 80));

    await upload('korean_cp949.csv', FIX.cp949);
    check('업로드(CP949 한글 머리글): 인코딩 판별과 자동 매핑', txt('import-body').indexOf('CP949') >= 0 && $('map-sampleId').value === '1' && $('map-nominal').value === '5' && document.querySelectorAll('#import-body .maprow .pill.fail').length === 0, txt('import-error'));

    await upload('missing_col.csv', FIX.missing);
    check('필수 열 누락: 분석 차단과 안내', txt('import-body').indexOf('필수 항목 없음') >= 0 && txt('import-body').indexOf('분석할 수 없습니다') >= 0 && txt('source-strip').indexOf('분석 불가') >= 0);
    $('tab-dashboard').click(); await wait(100);
    check('필수 열 누락: 대시보드는 결과 대신 안내를 보여 줌(가짜 수치 없음)', tiles().length === 0 && txt('dash-banners').indexOf('분석 결과가 없습니다') >= 0);
    $('tab-import').click(); await wait(50);
    setVal($('map-area'), '6'); await wait(200);   // Internal Standard Area 열을 면적으로 잘못 지정해도 분석은 실행된다(사용자 지정)
    check('컬럼 매핑 변경: 즉시 다시 검증·분석', txt('source-strip').indexOf('분석 불가') < 0 && txt('import-body').indexOf('분석 결과 보기') >= 0);

    await upload('bad_values.csv', FIX.bad);
    var ib = txt('import-body');
    check('비정상 값: 숫자가 아닌 값·음수·누락을 행 번호와 함께 표시', ib.indexOf('숫자가 아닌 값 3개') >= 0 && ib.indexOf('피크 면적이 음수') >= 0 && ib.indexOf('인식하지 못했습니다') >= 0 && ib.indexOf('행 번호: 4, 6, 9') >= 0);
    check('비정상 값: 인식하지 못한 유형 지정 UI', !!document.querySelector('[data-type="Mystery"]'));
    var before = txt('source-strip'); setVal(document.querySelector('[data-type="Mystery"]'), 'QC'); await wait(200);
    check('유형 지정: 제외 행 수가 줄어듦', txt('source-strip') !== before && !document.querySelector('#import-body') .textContent.match(/"Mystery"을\\(를\\) 인식하지/), txt('source-strip'));
    check('희석배수 누락: 기본은 채우지 않음', ib.indexOf('해당 행의 최종 농도는 계산하지 않습니다') >= 0);
    $('assume-dil').click(); await wait(200);
    check('희석배수 누락: 사용자가 켜면 1로 계산한다고 표시', txt('import-body').indexOf('사용자 선택에 따라 1로 계산') >= 0);

    await upload('no_is_no_rt.csv', FIX.nois);
    $('tab-calibration').click(); await wait(200);
    check('내부표준 열 없음: 외부표준법으로 자동 설정', $('cal-method').value === 'external' && txt('cal-body').indexOf('피크 면적') >= 0);

    // ── 예시 데이터로 돌아가 화면별 기능 ──
    $('tab-import').click(); await wait(50); $('demo-load').click(); await wait(300);
    check('예시 불러오기: 대시보드로 이동', !$('view-dashboard').hidden && tiles()[0] === '9');
    document.querySelector('#dash-matrix [data-cell="B01-NONLINEAR||Caffeine"]').click(); await wait(200);
    check('Dashboard → QC Review: 선택한 배치·분석물로 필터', !$('view-qc').hidden && $('qc-batch').value === 'B01-NONLINEAR' && $('qc-analyte').value === 'Caffeine' && txt('qc-table').indexOf('검량선 비선형성') >= 0);
    check('QC Review: 기준·출처·계산 근거 표시', txt('qc-table').indexOf('예시 기준') >= 0 && txt('qc-table').indexOf('출처:') >= 0 && txt('qc-table').indexOf('계산:') >= 0);
    check('QC Review: 세부 표와 그래프 2개', document.querySelectorAll('#qc-detail svg').length >= 2 && txt('qc-detail').indexOf('QC 시료 통계') >= 0);
    document.querySelector('#qc-table [data-tocal]').click(); await wait(200);
    check('QC Review → Calibration 이동', !$('view-calibration').hidden && $('cal-batch').value === 'B01-NONLINEAR');
    check('Calibration: 검량선·잔차 그래프, 회귀식, 역산 표', document.querySelectorAll('#cal-plot svg, #dev-plot svg').length === 2 && txt('cal-body').indexOf('면적비 =') >= 0 && document.querySelectorAll('#cal-body table')[0].querySelectorAll('tbody tr').length === 8);
    check('Calibration: 부적합 판정과 R² 참고 표시', txt('cal-body').indexOf('검량선 부적합') >= 0 && txt('cal-body').indexOf('R² (참고)') >= 0 && txt('cal-body').indexOf('비선형성 경고') >= 0);
    var nanPath = Array.prototype.some.call(document.querySelectorAll('#view-calibration svg path, #view-calibration svg circle, #view-calibration svg line'), function (p) { return /NaN|Infinity/.test((p.getAttribute('d') || '') + (p.getAttribute('cx') || '') + (p.getAttribute('cy') || '') + (p.getAttribute('y1') || '')); });
    check('Calibration: 그래프 좌표에 NaN 없음', !nanPath);
    var eq0 = txt('cal-body').match(/면적비 = [^R]*/)[0]; setVal($('cal-weight'), 'none'); await wait(200);
    check('Calibration: 가중치 변경이 회귀식을 바꿈', txt('cal-body').match(/면적비 = [^R]*/)[0] !== eq0);
    setVal($('cal-method'), 'external'); await wait(200);
    check('Calibration: 외부표준법 전환', txt('cal-body').indexOf('면적 = ') >= 0 && txt('cal-body').indexOf('면적비 =') < 0);
    setVal($('cal-method'), 'internal'); setVal($('cal-weight'), '1/x2'); await wait(200);
    setVal($('cal-batch'), 'B02-OUTLIER'); await wait(100); setVal($('cal-analyte'), 'Carbamazepine'); await wait(200);
    check('Calibration: 이상점 후보 표시', txt('cal-body').indexOf('이상점 후보: 50') >= 0, txt('cal-body').slice(txt('cal-body').indexOf('이상점'), txt('cal-body').indexOf('이상점') + 40));
    var exBtn = Array.prototype.filter.call(document.querySelectorAll('#cal-body [data-ex]'), function (b) { return b.closest('tr').textContent.indexOf('기준 밖') >= 0; })[0]; exBtn.click(); await wait(100);
    document.querySelector('[data-exok]').click(); await wait(100);
    check('검량점 제외: 사유가 없으면 제외하지 않음', !!$('ex-reason') && txt('cal-body').indexOf('되돌리기') < 0);
    $('ex-reason').value = '재주입 결과 조제 오류로 확인'; document.querySelector('[data-exok]').click(); await wait(250);
    check('검량점 제외: 사유와 함께 제외되고 다시 적합', txt('cal-body').indexOf('되돌리기') >= 0 && txt('cal-body').indexOf('재주입 결과 조제 오류로 확인') >= 0 && txt('cal-body').indexOf('사용한 점7개') >= 0, txt('cal-body').match(/사용한 점[^정]*/));
    document.querySelector('[data-restore]').click(); await wait(250);
    check('검량점 제외 취소', txt('cal-body').indexOf('사용한 점8개') >= 0);

    $('tab-qc').click(); await wait(200); setVal($('qc-batch'), ''); setVal($('qc-analyte'), ''); await wait(150);
    var nAll = document.querySelectorAll('#qc-table tbody tr').length; setVal($('qc-sev'), 'fail'); await wait(100);
    check('QC Review: 판정 필터', document.querySelectorAll('#qc-table tbody tr').length < nAll && document.querySelectorAll('#qc-table .pill.warn').length === 0, nAll + ' → ' + document.querySelectorAll('#qc-table tbody tr').length);
    setVal($('qc-sev'), ''); await wait(100);
    $('rules-panel').open = true; var spikeRows = function () { return (txt('qc-table').match(/첨가 회수율 낮음/g) || []).length; }; var s0 = spikeRows();
    setVal($('rule-spike-minPct'), '40'); await wait(300);
    check('QC 기준 변경: 회수율 하한 70 → 40이면 낮은 회수율 경고가 사라짐', s0 >= 1 && spikeRows() === 0 && txt('rules-state').indexOf('사용자 정의') >= 0, s0 + ' → ' + spikeRows());
    setVal($('rule-spike-minPct'), 'abc'); await wait(100);
    check('QC 기준: 잘못된 값은 거부하고 기존 값 유지', txt('rules-msg').indexOf('숫자를 입력') >= 0 && $('rule-spike-minPct').value === '40');
    $('rules-apply-profile').click(); await wait(300);
    check('QC 기준 묶음 적용: 예시 기본값으로 복원', spikeRows() === s0 && $('rule-spike-minPct').value === '70');
    check('QC 기준 표: 모든 항목에 출처·비고', document.querySelectorAll('#rules-table tbody tr').length >= 28 && txt('rules-note').indexOf('예시') >= 0);
    var sel = document.querySelector('#qc-table [data-review]'); var fid = sel.dataset.review; setVal(sel, 'action'); var note = document.querySelector('#qc-table [data-note="' + fid + '"]'); setVal(note, '표준 재조제 후 재분석');
    check('QC Review: 가로 넘침 없음', overflow() <= 0, overflow());

    $('tab-assistant').click(); await wait(200);
    var cards = document.querySelectorAll('#as-cards .card');
    check('Assistant: 진단 카드가 관측 사실과 가설을 분리', cards.length >= 8 && document.querySelectorAll('#as-cards .fact').length === cards.length && document.querySelectorAll('#as-cards .hypo').length === cards.length, cards.length);
    check('Assistant: 모든 카드가 "원인 미확정"', Array.prototype.every.call(cards, function (c) { return c.textContent.indexOf('원인 미확정') >= 0; }));
    check('Assistant: 근거·맞지 않는 점·판단할 수 없는 부분·추가 확인·권장 검증', ['이 데이터 안의 근거', '맞지 않는 점', '판단할 수 없는 부분', '추가 확인 항목', '권장 검증'].every(function (k) { return txt('as-cards').indexOf(k) >= 0; }));
    check('Assistant: LLM이 없을 때 버튼 비활성과 안내', $('llm-run').disabled && txt('llm-state').indexOf('LLM 연결을 쓸 수 없습니다') >= 0);
    check('Assistant: 요약 문장', document.querySelectorAll('#as-summary li').length === 10);
    $('as-only').click(); await wait(100);
    check('Assistant: 가설 없는 항목도 표시 전환', document.querySelectorAll('#as-cards .card').length > cards.length);
    check('Assistant: 가로 넘침 없음', overflow() <= 0, overflow());

    $('tab-report').click(); await wait(200);
    var rp = txt('report-preview');
    check('Report: 분석 요약·검량선·QC 결과·검토 기록', ['분석 요약', '검량선', 'QC 결과', '검토 기록'].every(function (k) { return rp.indexOf(k) >= 0; }));
    check('Report: 검토 상태와 메모가 반영됨', rp.indexOf('조치 필요') >= 0 && rp.indexOf('표준 재조제 후 재분석') >= 0);
    check('Report: 검토 기록에 조작 이력(기준 변경, 검량점 제외, 가중치 변경)', ['QC 기준 변경', '검량점 제외', '가중치 변경', '검토 상태 변경'].every(function (k) { return rp.indexOf(k) >= 0; }));
    $('memo-text').value = '11/11 배치 B02 재분석 결정'; $('memo-add').click(); await wait(100);
    check('Report: 검토 메모 추가', txt('report-preview').indexOf('11/11 배치 B02 재분석 결정') >= 0);
    var saved = []; var origCreate = URL.createObjectURL; URL.createObjectURL = function (blob) { saved.push(blob); return origCreate.call(URL, blob); };
    var clicks = document.querySelectorAll('[data-export]'); for (var i = 0; i < clicks.length; i++) { clicks[i].click(); await wait(80); }
    var texts = []; for (var j = 0; j < saved.length; j++) texts.push(await saved[j].text());
    check('Report: 내보내기 4종 생성(HTML·JSON·CSV 2개)', saved.length === 4 && texts[0].indexOf('<!doctype html>') === 0 && texts[0].indexOf('5. 이상 원인 진단 (가설)') > 0, saved.length);
    var js = null; try { js = JSON.parse(texts[1]); } catch (e) {}
    check('Report: JSON은 구조화되어 있고 검토 기록 포함', js && js.findings.length > 0 && js.calibrations.length === 27 && js.reviewLog.length >= 5 && js.diagnosis.every(function (d) { return d.causeStatus === '원인 미확정'; }));
    check('Report: CSV 2개의 머리글', texts[2].indexOf('판정,오류 코드,오류 유형') >= 0 && texts[3].indexOf('장비 측정 농도') >= 0);
    var nSaved = saved.length; document.querySelector('[data-eln="calibration"]').click(); await wait(80); document.querySelector('[data-eln="recovery"]').click(); await wait(80);
    var elnTxt = saved.length > nSaved ? await saved[nSaved].text() : '';
    check('Report: 본편 ELN 형식 내보내기 2종(원자료만)', saved.length === nSaved + 2 && elnTxt.indexOf('injection_id,level_ng_ml,analyte,analyte_area,is_area') === 0 && txt('eln-summary').indexOf('calibration@1') >= 0 && document.querySelectorAll('#eln-batch option').length === 9, saved.length - nSaved);
    check('Report: 인쇄 버튼(로컬에서만)', !$('print-btn').hidden);
    check('Report: 가로 넘침 없음', overflow() <= 0, overflow());

    location.hash = 'calibration'; await wait(150);
    check('해시 라우팅', !$('view-calibration').hidden);
    check('스크립트 오류 없음', errors.length === 0, errors.join(' | '));
    flush(true); window.__biopilotTestDone = true;
  }
  window.addEventListener('load', function () { run().catch(function (e) { var pre = document.createElement('pre'); pre.id = '__test'; pre.textContent = JSON.stringify(out.concat([{ name: '시험 실행 중 예외', ok: false, detail: String(e && e.stack || e) }])); var old = $('__test'); if (old) old.remove(); document.body.appendChild(pre); window.__biopilotTestDone = true; }); });
})();
</script>`;

const page = readFileSync(join(root, 'dist/index.html'), 'utf8'); const cut = page.lastIndexOf('</body>');   // 번들 안에도 '</body>' 문자열이 있으므로 마지막 것을 쓴다
const html = page.slice(0, cut) + probe + '\n' + page.slice(cut);
const testFile = join(root, 'dist/_test.html'); writeFileSync(testFile, html);
// 파일 읽기(Blob, 압축 해제)는 Chrome의 가상 시간과 함께 쓰면 멈추므로, 실제 시간으로 실행하고 DevTools 프로토콜로 결과를 읽는다.
const port = 9300 + Math.floor(Math.random() * 500); const profile = mkdtempSync(join(tmpdir(), 'biopilot-chrome-'));
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=' + width + ',900', '--remote-debugging-port=' + port, '--user-data-dir=' + profile, pathToFileURL(testFile).href], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function readResult() {
  let target = null;
  for (let i = 0; i < 60 && !target; i++) { await sleep(500); try { const list = await (await fetch('http://127.0.0.1:' + port + '/json')).json(); target = list.find(t => t.type === 'page' && t.url.includes('_test.html')); } catch (e) { /* 아직 뜨는 중 */ } }
  if (!target) throw new Error('브라우저에 연결하지 못했습니다.');
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('DevTools 연결 실패')); });
  let id = 0; const pending = new Map(); ws.onmessage = ev => { const msg = JSON.parse(ev.data); if (pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); } };
  const evaluate = expr => new Promise(res => { const n = ++id; pending.set(n, m => res(m.result && m.result.result ? m.result.result.value : null)); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } })); });
  let text = null;
  for (let i = 0; i < 360; i++) { await sleep(500); const done = await evaluate('window.__biopilotTestDone === true'); text = await evaluate('(document.getElementById("__test") || {}).textContent || null'); if (done) break; }
  ws.close(); return text;
}
let raw = null; try { raw = await readResult(); } catch (e) { console.log(String(e.message || e)); } finally { chrome.kill(); await sleep(300); try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* 프로필 폴더 정리 실패는 무시 */ } }
if (!raw) { console.log('시험 결과를 읽지 못했습니다 (페이지가 끝까지 실행되지 않음).'); process.exit(1); }
const results = JSON.parse(raw); writeFileSync(join(root, 'tests', 'last-browser-' + width + '.json'), JSON.stringify(results, null, 1));
let fail = 0; for (const r of results) { if (!r.ok) fail++; console.log((r.ok ? '  PASS ' : '  FAIL ') + r.name + (r.detail ? '  — ' + r.detail : '')); }
console.log('\n브라우저 시험(폭 ' + width + 'px): ' + (results.length - fail) + '/' + results.length + ' 통과');
process.exit(fail ? 1 : 0);
