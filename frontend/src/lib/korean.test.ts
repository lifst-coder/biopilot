import { describe, expect, it } from "vitest";
import { josa } from "./korean";

describe("josa", () => {
  it("picks the particle from the last digit's reading", () => {
    expect(josa("#018", "과/와")).toBe("#018과");
    expect(josa("#019", "과/와")).toBe("#019와");
    expect(josa("#018", "은/는")).toBe("#018은");
    expect(josa("#024", "은/는")).toBe("#024는");
  });
});
