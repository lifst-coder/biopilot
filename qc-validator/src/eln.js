// BIOPILOT QC 검증 도구 → BioPilot 본편(ELN) 연결.
// 검증한 배치의 원자료를 본편의 데이터셋 계약(backend/app/eln/schemas.py 의 DATASET_KIND_REGISTRY)에 맞는 CSV로 내보낸다.
// 값은 파일에서 읽은 그대로 옮기고 계산 결과는 넣지 않는다: 본편은 원본에서 스스로 다시 계산한다(L3 Analysis).
import { isNum } from './stats.js';
import { toCsv } from './parse.js';

// 계약: calibration@1, recovery@1 의 필수 열(순서 포함). 본편 계약이 바뀌면 여기와 tests/eln.test.mjs 를 함께 고친다.
export const ELN_CONTRACT = {
  calibration: { kind: 'calibration@1', columns: ['injection_id', 'level_ng_ml', 'analyte', 'analyte_area', 'is_area'] },
  recovery: { kind: 'recovery@1', columns: ['injection_id', 'sample_id', 'analyte', 'spike_ng_g', 'analyte_area', 'is_area'] },
};

const validAreas = r => isNum(r.area) && r.area >= 0 && isNum(r.isArea) && r.isArea > 0;

// 한 배치를 본편 계약 형식으로 변환한다. 옮길 수 없는 행은 사유와 함께 skipped 에 남긴다(값을 지어내지 않는다).
// 반환: { batchId, calibration: { rows, skipped }, recovery: { rows, skipped }, notes }
export function elnExport(result, batchId) {
  const groups = result.groups.filter(g => g.batchId === batchId);
  const cal = { rows: [ELN_CONTRACT.calibration.columns.slice()], skipped: [] };
  const rec = { rows: [ELN_CONTRACT.recovery.columns.slice()], skipped: [] };
  const notes = [];
  const skip = (bucket, x, reason) => bucket.skipped.push({ sampleId: x.rec.sampleId, analyte: x.rec.analyte, row: x.rec.row, reason });
  const ordered = [];
  for (const g of groups) for (const x of g.rows) ordered.push({ g, x });
  ordered.sort((a, b) => a.x.rec.order - b.x.rec.order || a.x.rec.row - b.x.rec.row);
  for (const { g, x } of ordered) {
    const r = x.rec;
    if (r.type === 'STD') {
      if (!isNum(r.nominal) || r.nominal <= 0) skip(cal, x, '명목 농도가 없거나 0 이하');
      else if (!validAreas(r)) skip(cal, x, '분석물 면적 또는 내부표준 면적이 없음(본편 계약은 두 값이 모두 필요)');
      else cal.rows.push([r.sampleId, r.nominal, r.analyte, r.area, r.isArea]);
    } else if (r.type === 'SPIKE') {
      const item = (g.tables.spikes || []).find(i => i.row === r.row);
      if (!isNum(r.nominal) || r.nominal <= 0) skip(rec, x, '첨가 농도(명목 농도)가 없음');
      else if (!validAreas(r)) skip(rec, x, '분석물 면적 또는 내부표준 면적이 없음');
      else if (item && item.parentId) skip(rec, x, '원시료(' + item.parentId + ')가 연결된 매질 첨가: 본편 회수율 계산은 원시료 농도를 빼지 않으므로 그대로 옮기면 회수율이 달라진다');
      else if (isNum(r.dilution) && r.dilution !== 1) skip(rec, x, '희석배수 ' + r.dilution + ': 본편 recovery 계약에는 희석배수 열이 없다');
      else rec.rows.push([r.sampleId, r.sampleId, r.analyte, r.nominal, r.area, r.isArea]);
    }
  }
  const excluded = [];
  for (const g of groups) for (const p of g.cal.points) if (p.excludedBy === 'user') excluded.push(g.analyte + ' ' + p.sampleId + ' (' + p.reason + ')');
  if (excluded.length) notes.push('이 도구에서 사용자가 회귀에서 제외한 검량점도 원본이므로 그대로 내보냈다: ' + excluded.join(', ') + '. 제외 판단과 사유는 본편의 실험 메모나 보충 기록에 적어야 한다.');
  notes.push('농도 값은 파일의 숫자를 그대로 옮겼다. 본편 계약의 단위는 검량 ng/mL, 첨가 ng/g이다. 본편은 조건 블록의 추출 부피와 시료 질량으로 ng/g을 환산하므로, 파일의 첨가 농도가 바이알 내 농도라면 환산 계수가 1이 되도록 조건을 입력하거나 값을 ng/g으로 바꿔 올린다.');
  if (groups.some(g => g.method === 'external')) notes.push('이 배치에는 외부표준법으로 계산한 분석물이 있다. 본편 calibration 계약은 내부표준 면적이 필수라서 내부표준 면적이 없는 행은 옮기지 못했다.');
  notes.push('QC 시료, 바탕, 중복, 미지 시료는 본편의 calibration·recovery 계약에 해당 열이 없어 옮기지 않았다. 이 도구의 정량 결과 표(CSV)를 실험 첨부로 올릴 수 있다.');
  return { batchId, calibration: cal, recovery: rec, notes };
}
export function elnCsv(part) { return toCsv(part.rows); }
