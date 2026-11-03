/**
 * Reference profile (7 experiments): the core demo loop through the real UI.
 * #024 열기 → #018과 비교 → Analysis 확인 → Critic → 제안 기각 + 사유 → 재질의에 반영 확인.
 * Every expected number is read from the API and formatted with the UI's own formatter.
 */
import { expect, test } from "@playwright/test";
import { formatWithUnit } from "../src/lib/format";
import { experimentIds, getJson, projects } from "./helpers";

interface Comparison {
  recovery_delta_pct_points: number | null;
  metrics_a: { recovery_mean_pct: number | null };
  metrics_b: { recovery_mean_pct: number | null };
}
interface Metrics {
  recovery_mean_pct: number | null;
  flags: Array<{ code: string }>;
}
interface Proposal {
  id: number;
  title: string;
  status: string;
}

const REASON = "E2E 기각: 블랭크 사과 매트릭스 재고가 없어 이번 달에는 진행할 수 없다";

test("reference: #024 → compare #018 → Analysis → Critic → reject with reason → re-ask", async ({
  page,
  request,
}) => {
  const [project] = await projects(request);
  expect(project).toBeDefined();
  const ids = await experimentIds(request, project!.id);
  const id024 = ids["#024"]!;
  const id018 = ids["#018"]!;
  expect(id024 && id018).toBeTruthy();

  await test.step("open #024 in the Notebook", async () => {
    await page.goto(`/notebook?exp=${id024}`);
    await expect(page.getByRole("heading", { name: /#024/ }).first()).toBeVisible();
  });

  await test.step("compare with #018 (Memory diff + stored Analysis deltas)", async () => {
    const cmp = await getJson<Comparison>(request, `/api/analysis/compare?a=${id018}&b=${id024}`);
    await page.getByRole("button", { name: "과거 실험과 비교" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("기준(과거) 실험").selectOption(String(id018));
    await expect(dialog.getByText("추출 시간 (min)")).toBeVisible();
    await expect(dialog.getByText("정제 흡착제 (d-SPE)")).toBeVisible();
    await expect(dialog.getByText(formatWithUnit(cmp.recovery_delta_pct_points, "%p")).first()).toBeVisible();
    await expect(dialog.getByText(formatWithUnit(cmp.metrics_a.recovery_mean_pct, "%")).first()).toBeVisible();
    await expect(dialog.getByText("현재 실험 미분석")).toHaveCount(0);
    await page.keyboard.press("Escape");
    if (await dialog.isVisible()) await dialog.getByRole("button", { name: /닫기|×/ }).first().click();
  });

  await test.step("Analysis tab shows the stored metrics and QC flags", async () => {
    const m = await getJson<Metrics>(request, `/api/analysis/experiments/${id024}/metrics`);
    expect(m.flags.some((f) => f.code === "recovery_out_of_range")).toBeTruthy();
    await page.goto(`/analysis?exp=${id024}`);
    const tile = page.getByText("평균 회수율", { exact: true }).first().locator("..");
    await expect(tile).toContainText(formatWithUnit(m.recovery_mean_pct, "%"));
    await expect(page.getByText("회수율 범위 이탈").first()).toBeVisible();
  });

  let rejected: Proposal;
  await test.step("run the Research Critic", async () => {
    await page.goto(`/research-ai?exp=${id024}`);
    await page.getByRole("button", { name: "비판적 검토 실행" }).click();
    await expect(page.getByRole("button", { name: "비판적 검토 실행" })).toBeEnabled();
    const pending = await getJson<Proposal[]>(
      request,
      `/api/partner/proposals?project_id=${project!.id}&experiment_id=${id024}&status=pending`,
    );
    expect(pending.length).toBeGreaterThan(0);
    rejected = pending[0]!;
    await expect(page.getByText(rejected.title).first()).toBeVisible();
  });

  await test.step("reject a proposal with a reason", async () => {
    const card = page.locator("article").filter({ hasText: rejected.title }).first();
    await card.getByRole("radio", { name: "기각" }).click();
    await card.getByPlaceholder(/결정 사유/).fill(REASON);
    await card.getByRole("button", { name: "결정 기록" }).click();
    await expect(page.getByText(`사유: ${REASON}`).first()).toBeVisible();
    const stored = await getJson<Proposal & { decision: { action: string; rationale: string } }>(
      request,
      `/api/partner/proposals/${rejected.id}`,
    );
    expect(stored.status).toBe("rejected");
    expect(stored.decision.rationale).toBe(REASON);
  });

  await test.step("re-ask: the answer and the new critique cite the rejection reason", async () => {
    const box = page.getByPlaceholder("예: #024 회수율이 왜 낮나?");
    await box.fill("#024 다음 실험은 무엇을 해야 하나?");
    await page.getByRole("button", { name: "질문", exact: true }).click();
    await expect(page.getByText(/결정 반영:.*블랭크 사과 매트릭스 재고가 없어/).first()).toBeVisible();

    await page.getByRole("button", { name: "비판적 검토 실행" }).click();
    await expect(page.getByText("반영된 연구자 결정").first()).toBeVisible();
    await expect(page.getByText(/블랭크 사과 매트릭스 재고가 없어/).first()).toBeVisible();
    const after = await getJson<Proposal[]>(
      request,
      `/api/partner/proposals?project_id=${project!.id}&experiment_id=${id024}&status=pending`,
    );
    expect(after.map((p) => p.title)).not.toContain(rejected.title);
  });
});
