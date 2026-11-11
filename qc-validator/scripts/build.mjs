// BIOPILOT QC 검증 도구 — 단일 파일 빌드. 의존성 없음.  node scripts/build.mjs
//  dist/index.html    : 더블클릭으로 열리는 완전한 문서 (저장소에 커밋한다. tests/build.test.mjs가 소스와 일치하는지 검사)
//  dist/artifact.html : 게시용 조각(doctype/html/head/body 없음, 커밋하지 않는다)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
// 운영체제와 git 설정에 따라 줄바꿈이 달라져도 같은 결과가 나오도록 LF로 통일한다.
const read = p => readFileSync(join(root, p), 'utf8').replace(/\r\n/g, '\n');
const MODULES = ['stats.js', 'parse.js', 'rules.js', 'calibration.js', 'qc.js', 'analyze.js', 'diagnose.js', 'llm.js', 'report.js', 'synth.js', 'pipeline.js', 'charts.js', 'eln.js', 'app.js'];   // 의존 순서

function wrap(name) {
  let src = read('src/' + name);
  const exported = [];
  // import { a, b } from './x.js';  →  const { a, b } = __m['x.js'];
  src = src.replace(/^import\s*\{([^}]*)\}\s*from\s*'\.\/([\w.-]+)';?\s*$/gm, (_, names, file) => 'const {' + names + "} = __m['" + file + "'];");
  if (/^import\s/m.test(src)) throw new Error(name + ': 지원하지 않는 import 형식');
  src = src.replace(/^export\s+(const|let|function|async function)\s+([A-Za-z_$][\w$]*)/gm, (_, kind, id) => { exported.push(id); return kind + ' ' + id; });
  if (/^export\s/m.test(src)) throw new Error(name + ': 지원하지 않는 export 형식');
  return "__m['" + name + "'] = (function () {\n" + src + '\nreturn { ' + exported.join(', ') + ' };\n})();\n';
}

// 소스에서 두 가지 출력물을 문자열로 만든다(파일을 쓰지 않는다).
export function buildPages() {
  const js = '(function () {\n"use strict";\nconst __m = {};\n' + MODULES.map(wrap).join('\n') + '})();';
  if (js.includes('</script')) throw new Error('스크립트 안에 </script 문자열이 있습니다');
  const artifact = read('src/page.html').replace('/*__CSS__*/', () => read('src/styles.css')).replace('/*__JS__*/', () => js);
  const cut = artifact.indexOf('<header');
  const full = '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' +
    artifact.slice(0, cut) + '</head>\n<body>\n' + artifact.slice(cut) + '\n</body>\n</html>\n';
  return { artifact, full };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { artifact, full } = buildPages();
  mkdirSync(join(root, 'dist'), { recursive: true });
  writeFileSync(join(root, 'dist/artifact.html'), artifact);
  writeFileSync(join(root, 'dist/index.html'), full);
  console.log('built dist/index.html (' + (full.length / 1024).toFixed(0) + ' KB), dist/artifact.html');
}
