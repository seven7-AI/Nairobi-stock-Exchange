import { describe, expect, it } from "vitest";
import { insertGapBreaks, toPriceBand } from "../lib/series";
import prices from "./fixtures/prices-KCB-max.json";

describe("series helpers", () => {
  it("inserts exactly one null point per gap, in order", () => {
    const out = insertGapBreaks(prices.points, prices.gaps);
    const nulls = out.filter((p) => p.close === null);
    expect(nulls).toHaveLength(prices.gaps.length);
    expect(prices.gaps[0].days).toBe(572);
    for (let i = 1; i < out.length; i++) expect(out[i].t).toBeGreaterThanOrEqual(out[i - 1].t);
    const gapT = Date.parse(`${prices.gaps[0].after}T00:00:00Z`) + 86_400_000;
    expect(nulls[0].t).toBe(gapT);
  });
  it("maps quantile returns to prices", () => {
    const band = toPriceBand(90, { q05: -0.475, q25: null, q50: -0.032, q75: null, q95: 0.785 });
    expect(band.q05).toBeCloseTo(47.25, 2);
    expect(band.q25).toBeNull();
    expect(band.q95).toBeCloseTo(160.65, 2);
  });
});
