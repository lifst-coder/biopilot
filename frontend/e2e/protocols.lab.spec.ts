/**
 * Lab profile · Protocols tab (runs after lab.spec.ts: it adds a protocol version and an
 * experiment to the residue project).
 * - lineage: SOP v1 → v1.1 → v1.2 → v2 with the stored QC pass counts per version
 * - paste → condition extraction → confirm → save (original text kept, nothing guessed)
 * - run the saved version at phone width: check steps, record a different actual value,
 *   save the run as an experiment whose condition block and note carry the difference
 */
import { expect, test } from "@playwright/test";
import { getJson, projects } from "./helpers";

interface Group {
  value: number;
  pass_count: number;
  analyzed_count: number;
}
interface Lineage {
  lineages: Array<{ name: string; versions: Array<{ template: { template_id: number; display_version: string } }> }>;
}
interface Template {
  id: number;
  name: string;
  display_version: string;
  source_text: string;
  extraction: { engine: string; items: Array<{ key: string; outcome: string }> } | null;
}

const PASTE = [
  "잔류농약 QuEChERS SOP (현장 메모)",
  "1. 균질화한 사과 10 g을 50 mL 원심관에 칭량한다.",
  "2. 1% 아세트산 아세토니트릴 10 mL를 넣고 추출 10분 진탕한다.",
  "3. 아세테이트 완충염 (AOAC 2007.01) 첨가 후 1분 진탕, 원심분리 4000 rpm 5분.",
  "4. 상등액을 d-SPE 튜브(PSA 50 mg + C18 50 mg + MgSO4 150 mg)로 옮긴다.",
  "5. LC-MS/MS (ESI+, MRM), 컬럼 C18 2.1×100 mm, 1.8 µm, 컬럼 온도 35–40 °C",
].join("\n");

test("lab: SOP lineage shows stored QC pass counts per version", async ({ page, request }) => {
  const [residue] = await projects(request);
  const lineage = await getJson<Lineage>(request, `/api/eln/projects/${residue!.id}/protocol-lineage`);
  const versions = lineage.lineages[0]!.versions;
  expect(versions.map((v) => v.template.display_version)).toEqual(["v1", "v1.1", "v1.2", "v2"]);
  const records = await getJson<{ groups: Group[] }>(
    request,
    `/api/analysis/records/protocols?project_id=${residue!.id}`,
  );
  const latest = records.groups.find((g) => g.value === versions[3]!.template.template_id)!;

  await page.goto("/protocols");
  await expect(page.getByText("이 화면의 질문 · 어느 프로토콜 버전으로 한 실험이 QC를 잘 통과했나?")).toBeVisible();
  await expect(page.getByText(/QC 통과율이 가장 높은 버전은/)).toBeVisible();
  await expect(page.getByText(`${latest.pass_count}/${latest.analyzed_count} 통과`).first()).toBeVisible();
  await page.locator("summary", { hasText: "SOP v2" }).click();
  await expect(page.getByText("이전 버전 대비 바뀐 조건").last()).toBeVisible();
  await expect(page.getByRole("link", { name: /#024/ }).first()).toBeVisible();
});

test("lab: paste → extract conditions → confirm → save, then run it at phone width", async ({ page, request }) => {
  const [residue] = await projects(request);

  // 1) paste and extract
  await page.goto("/protocols");
  await page.getByRole("button", { name: "+ 붙여넣어 새 프로토콜" }).click();
  await expect(page.getByText("이 화면의 질문 · 붙여넣은 프로토콜에서 조건이 제대로 읽혔나?")).toBeVisible();
  await page.getByLabel("프로토콜 원문").fill(PASTE);
  await page.getByRole("button", { name: "조건 추출" }).click();
  await expect(page.getByText(/조건 \d+개 중 \d+개를 읽었습니다/)).toBeVisible();
  await expect(page.getByLabel(/추출 시간/)).toHaveValue("10");
  // a range is never resolved to one value
  await expect(page.getByLabel(/컬럼 온도/)).toHaveValue("");
  await expect(page.getByText(/범위나 여러 값/)).toBeVisible();

  // 2) confirm: fill one key the paste did not contain, save as the next SOP version
  await page.locator("summary", { hasText: "인식하지 못한 조건" }).click();
  await page.getByLabel("pH").fill("5.0");
  await page.getByLabel(/컬럼 온도/).fill("40");
  await page.getByLabel("프로토콜 이름").fill("잔류농약 QuEChERS SOP");
  await page.getByLabel("버전 이름").fill("v2.1");
  await expect(page.getByText("같은 이름의 프로토콜이 있어 그 다음 버전으로 저장됩니다.")).toBeVisible();
  await page.getByRole("button", { name: "확인하고 저장" }).click();
  await expect(page.getByText("저장되었습니다")).toBeVisible();

  const all = await getJson<{ items: Template[] }>(
    request,
    `/api/eln/projects/${residue!.id}/protocol-templates?all_versions=true`,
  );
  const saved = all.items.find((t) => t.display_version === "v2.1")!;
  expect(saved.source_text).toBe(PASTE); // the pasted original is kept as is
  const outcomes = Object.fromEntries(saved.extraction!.items.map((i) => [i.key, i.outcome]));
  expect(outcomes.extraction_time_min).toBe("accepted");
  expect(outcomes.ph).toBe("added");
  expect(outcomes.column_temp_c).toBe("added");
  const audit = await getJson<Array<{ entity_type: string; entity_id: number }>>(
    request,
    `/api/audit?project_id=${residue!.id}&entity_type=eln.ProtocolTemplate&entity_id=${saved.id}`,
  );
  expect(audit.length).toBe(1);

  // 3) run it on a phone
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("작업자").fill("김연구");
  await page.getByRole("button", { name: "이 프로토콜로 실험 시작" }).click();
  await expect(page.getByText("이 화면의 질문 · 지금 할 단계와 그 조건값은?")).toBeVisible();
  await page.getByRole("button", { name: "✓ 이 단계 완료" }).click(); // 준비 — 조건 확인
  await page.locator("summary", { hasText: "전체 단계" }).click();
  await page.getByRole("button", { name: /추출 10분/ }).click();
  await page.locator("li", { hasText: "추출 시간" }).getByRole("button", { name: "값이 달랐음" }).click();
  await page.getByLabel(/실제 추출 시간/).fill("7");
  await page.getByLabel("이유 (선택)").fill("타이머 오작동");
  await page.getByRole("button", { name: "기록", exact: true }).click();
  await expect(page.getByText(/추출 시간 \(min\) 10 min → 7 min \(타이머 오작동\)/).first()).toBeVisible();
  await page.getByRole("button", { name: "✓ 이 단계 완료" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);

  // 4) save the run as an experiment
  await page.locator("summary", { hasText: "실험 기록으로 저장" }).click();
  await page.getByRole("button", { name: "저장 전 미리보기" }).click();
  await expect(page.getByText("저장될 원본 메모 (저장 후 변경 불가)")).toBeVisible();
  await page.getByRole("button", { name: "실험 기록으로 저장" }).click();
  await expect(page).toHaveURL(/\/notebook\?.*exp=\d+/);
  const expId = Number(new URL(page.url()).searchParams.get("exp"));
  const exp = await getJson<{
    condition_block: Record<string, unknown>;
    raw_note: string;
    protocol_template_id: number;
  }>(request, `/api/eln/experiments/${expId}`);
  expect(exp.condition_block.extraction_time_min).toBe(7);
  expect(exp.protocol_template_id).toBe(saved.id);
  expect(exp.raw_note).toContain("프로토콜과 다른 점:");
  await expect(page.getByText("프로토콜 잔류농약 QuEChERS SOP v2.1", { exact: false })).toBeVisible();
  await expect(page.getByText(/10 min → 7 min/).first()).toBeVisible();
});
