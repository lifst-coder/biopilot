import { describe, expect, it } from "vitest";
import {
  formatConditionValue,
  formatEvidenceValue,
  formatNumber,
  formatPValue,
  formatWithUnit,
} from "./format";

describe("format", () => {
  it("renders missing values as an em dash", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatWithUnit(null, "%")).toBe("—");
  });

  it("formats with fixed digits and units", () => {
    expect(formatNumber(89.123, 1)).toBe("89.1");
    expect(formatWithUnit(-27.06, "%p")).toBe("-27.1%p");
  });

  it("formats p-values with thresholds", () => {
    expect(formatPValue(1e-21)).toBe("p < 0.001");
    expect(formatPValue(0.0423)).toBe("p = 0.042");
  });

  it("formats evidence values by magnitude", () => {
    expect(formatEvidenceValue(3, null)).toBe("3");
    expect(formatEvidenceValue(4.6e-21, null)).toBe("4.6e-21");
    expect(formatEvidenceValue(0.99931, null)).toBe("0.9993");
    expect(formatEvidenceValue(61.98, "%")).toBe("62.0%");
  });

  it("keeps condition values verbatim", () => {
    expect(formatConditionValue(5)).toBe("5");
    expect(formatConditionValue("PSA 50 mg")).toBe("PSA 50 mg");
    expect(formatConditionValue(null)).toBe("—");
  });
});
