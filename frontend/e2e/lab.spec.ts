/**
 * Lab profile (2 projects, 42 experiments, six months of decisions).
 * - cross-project recall: the residue project's memory surfaces the organic-acid experiment
 *   that shared its column (UI search), and vice versa (API).
 * - cross-project recall in the Critic: switch to the organic-acid project, open #OA06 (the
 *   pesticide PSA clean-up carried over) — the residue project's PSA history follows as
 *   evidence above the Critic, and the cross-project search names the other project.
 * - Records: the operator difference (#029/#030), the maintenance gap and the repeated
 *   failure (#014 → #015 → #016) are shown from stored data.
 * - the Critic for #024 cites a rejection reason recorded months earlier (#009 2×2, workload).
 */
import { expect, test } from "@playwright/test";
import { experimentIds, getJson, projects } from "./helpers";

interface Hit {
  code: string;
  field: string;
  snippet: string;
}
interface Critique {
  decision_feedback: Array<{ action: string; rationale: string; note: string }>;
}

test("lab: recall across the two projects", async ({ page, request }) => {
  const [residue, acids] = await projects(request);
  expect(residue && acids).toBeTruthy();
  const acidCodes = Object.keys(await experimentIds(request, acids!.id));
  const residueCodes = Object.keys(await experimentIds(request, residue!.id));
  expect(acidCodes.length).toBe(12);
  expect(residueCodes.length).toBe(30);

  // Residue memory → an organic-acid experiment code (shared C18 column).
  const acidCode = "#OA02";
  const hits = await getJson<Hit[]>(
    request,
    `/api/memory/projects/${residue!.id}/search?q=${encodeURIComponent(acidCode)}`,
  );
  expect(hits.length).toBeGreaterThan(0);
  const linked = hits[0]!.code;
  expect(residueCodes).toContain(linked);

  await page.goto("/overview");
  const search = page.getByRole("combobox", { name: "연구 기억 검색" });
  await search.fill(acidCode);
  await expect(page.getByText(linked).first()).toBeVisible();
  await expect(page.getByText(/유기산 프로젝트/).first()).toBeVisible();

  // Organic-acid memory → residue experiment codes (API: second project).
  let back: Hit[] = [];
  for (const code of residueCodes) {
    back = await getJson<Hit[]>(
      request,
      `/api/memory/projects/${acids!.id}/search?q=${encodeURIComponent(code)}`,
    );
    if (back.some((h) => h.snippet.includes(code))) break;
  }
  expect(back.some((h) => acidCodes.includes(h.code))).toBeTruthy();
});

test("lab: Critic output reflects a rejection reason from the decision history", async ({
  page,
  request,
}) => {
  const [residue] = await projects(request);
  const ids = await experimentIds(request, residue!.id);
  const id024 = ids["#024"]!;
  const critiques = await getJson<Critique[]>(request, `/api/partner/experiments/${id024}/critiques`);
  const reject = critiques[0]!.decision_feedback.find((f) => f.action === "reject");
  expect(reject, "seeded #024 critique carries an earlier rejection").toBeDefined();
  const reasonHead = reject!.rationale.slice(0, 24);

  await page.goto(`/research-ai?exp=${id024}`);
  await expect(page.getByText("반영된 연구자 결정").first()).toBeVisible();
  await expect(page.getByText(reasonHead, { exact: false }).first()).toBeVisible();

  // Re-running the critic keeps citing the old reason and does not re-offer the rejected design.
  await page.getByRole("button", { name: "비판적 검토 실행" }).click();
  await expect(page.getByRole("button", { name: "비판적 검토 실행" })).toBeEnabled();
  const latest = await getJson<Critique[]>(request, `/api/partner/experiments/${id024}/critiques`);
  expect(latest[0]!.decision_feedback.some((f) => f.rationale === reject!.rationale)).toBeTruthy();
  await expect(page.getByText(reasonHead, { exact: false }).first()).toBeVisible();
});

test("lab: #OA06 recalls the residue project's PSA history across projects", async ({ page, request }) => {
  const [residue, acids] = await projects(request);
  const acidIds = await experimentIds(request, acids!.id);
  const residueIds = await experimentIds(request, residue!.id);
  const oa06 = acidIds["#OA06"]!;

  // The API ties the two projects together: PSA usage in the residue project, before #OA06.
  const precedents = await getJson<{
    condition_usage: Array<{ project_id: number; value: string; experiments: Array<{ code: string }>; fail_count: number }>;
  }>(request, `/api/partner/experiments/${oa06}/precedents`);
  const usage = precedents.condition_usage.find((u) => u.project_id === residue!.id);
  expect(usage, "#OA06 finds the residue project's PSA d-SPE").toBeDefined();
  expect(usage!.value).toContain("PSA");
  expect(usage!.fail_count).toBe(0);
  const psaCode = usage!.experiments[0]!.code;
  expect(Object.keys(residueIds)).toContain(psaCode);

  // UI: switch project in the header, open #OA06 in Research AI.
  await page.goto("/overview");
  await page.getByRole("combobox", { name: "프로젝트 전환" }).selectOption(String(acids!.id));
  await expect(page.getByRole("heading", { level: 1 })).toContainText("유기산");
  await page.getByRole("link", { name: "Research AI" }).click();
  await page.getByRole("combobox", { name: /실험/ }).first().selectOption(String(oa06));
  const card = page.getByTestId("precedents");
  await expect(card.getByRole("heading", { name: "과거에 같은 증상이 있었다" })).toBeVisible();
  await expect(card.getByText(/다른 프로젝트에서 같은 정제 흡착제/)).toBeVisible();
  const chip = card.getByRole("link", { name: new RegExp(`${psaCode}.*잔류농약`) }).first();
  await expect(chip).toBeVisible();
  await expect(card.getByRole("heading", { name: "그때 내린 결론" }).first()).toBeVisible();

  // The evidence chip opens the residue experiment in its own project.
  await chip.click();
  await expect(page).toHaveURL(new RegExp(`project=${residue!.id}&exp=${residueIds[psaCode]}`));
  await expect(page.getByRole("combobox", { name: "프로젝트 전환" })).toHaveValue(String(residue!.id));

  // Cross-project search from the organic-acid project names the residue project.
  await page.goto(`/overview?project=${acids!.id}`);
  await page.getByRole("combobox", { name: "연구 기억 검색" }).fill("PSA");
  const related = page.getByRole("list", { name: "관련 실험" });
  await expect(related.getByText("#OA06").first()).toBeVisible();
  await expect(related.getByText("잔류농약").first()).toBeVisible();
});

test("lab: Records shows what only the accumulated records reveal", async ({ page }) => {
  await page.goto("/records");
  await expect(page.getByText("이 화면의 질문 · 지금까지 쌓인 기록에서 무엇이 보이는가?")).toBeVisible();
  const headline = page.getByRole("region", { name: /같은 조건인데 작업자에 따라/ });
  await expect(headline).toBeVisible();
  await expect(headline.getByRole("link", { name: /#029/ })).toBeVisible();
  await expect(headline.getByRole("link", { name: /#030/ })).toBeVisible();

  await page.getByText("기간별 추이와 공백").click();
  await expect(page.getByText(/기록 공백 \d+일/).first()).toBeVisible();

  await page.getByRole("button", { name: "실패 아카이브" }).click();
  await expect(page.getByText("이 화면의 질문 · 같은 실패를 반복하고 있지 않은가?")).toBeVisible();
  await expect(page.getByRole("region", { name: /미달이 이어진 실험에서 되풀이됐다/ })).toBeVisible();
  const chain = page.getByRole("group", { name: "실패 순서" }).filter({ hasText: "#014" });
  await expect(chain).toContainText("#015");
  await expect(chain).toContainText("#016");

  await page.getByText(/실패 기록 \d+건/).click();
  await expect(page.getByText("원인 가설 (규칙 기반)").first()).toBeVisible();
  await expect(page.getByText(/MgSO4 새 lot/).first()).toBeVisible();
});
