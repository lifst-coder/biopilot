/**
 * Lab profile (2 projects, 42 experiments, six months of decisions).
 * - cross-project recall: the residue project's memory surfaces the organic-acid experiment
 *   that shared its column (UI search), and vice versa (API — the UI has no project switcher yet).
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
