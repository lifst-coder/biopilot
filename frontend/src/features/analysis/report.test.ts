import { afterEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("@/api/client", () => ({ api: { GET } }));

const { fetchReport, filenameFrom, saveText } = await import("./report");

afterEach(() => vi.restoreAllMocks());

describe("report export", () => {
  it("parses the download filename", () => {
    expect(filenameFrom('attachment; filename="biopilot-024-analysis.md"', "markdown")).toBe(
      "biopilot-024-analysis.md",
    );
    expect(filenameFrom(null, "csv")).toBe("analysis-report.csv");
    expect(filenameFrom(null, "markdown")).toBe("analysis-report.md");
  });

  it("requests the backend report as text with the chosen format", async () => {
    GET.mockResolvedValueOnce({
      data: "section,result_id\n",
      response: new Response("", {
        headers: { "content-disposition": 'attachment; filename="x.csv"', "content-type": "text/csv" },
      }),
    });
    const report = await fetchReport(7, "csv");
    expect(GET).toHaveBeenCalledWith("/api/analysis/experiments/{experiment_id}/report", {
      params: { path: { experiment_id: 7 }, query: { format: "csv" } },
      parseAs: "text",
    });
    expect(report).toEqual({ text: "section,result_id\n", filename: "x.csv", mediaType: "text/csv" });
  });

  it("throws on API errors", async () => {
    GET.mockResolvedValueOnce({ error: { code: "not_found" }, response: new Response("", { status: 404 }) });
    await expect(fetchReport(99, "markdown")).rejects.toThrow("HTTP 404");
  });

  it("saves text through an object URL", () => {
    const create = vi.fn(() => "blob:1");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    saveText("# r", "r.md", "text/markdown");
    expect(create).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith("blob:1");
  });
});
