import { describe, expect, it } from "vitest";
import { fmtAgo, fmtCompactKes, fmtDate, fmtPct, fmtRatio } from "../lib/format";

describe("format", () => {
  it("formats KES compactly", () => {
    expect(fmtCompactKes(289_211_653_350)).toBe("KES 289.2 bn");
    expect(fmtCompactKes(1_500_000)).toBe("KES 1.5 m");
    expect(fmtCompactKes(92.25)).toMatch(/92\.25/);
  });
  it("formats fractions as percentages with optional sign", () => {
    expect(fmtPct(0.0542)).toBe("5.4 %");
    expect(fmtPct(0.079, 1, true)).toBe("+7.9 %");
    expect(fmtPct(-0.265, 1, true)).toBe("-26.5 %");
  });
  it("formats ratios and dates", () => {
    expect(fmtRatio(4.4351)).toBe("4.44×");
    expect(fmtDate("2026-09-16")).toBe("16 Sept 2026");
    expect(fmtDate(null)).toBe("—");
  });
  it("formats relative time", () => {
    const now = new Date("2026-09-17T10:00:00Z");
    expect(fmtAgo("2026-09-17T09:57:00Z", now)).toBe("3 min ago");
    expect(fmtAgo("2026-09-17T07:00:00Z", now)).toBe("3 h ago");
    expect(fmtAgo("2026-09-10T07:00:00Z", now)).toBe("7 d ago");
    expect(fmtAgo(null, now)).toBe("never");
  });
});
