import type { Gap, PricePoint } from "../api/types";

export interface ChartPoint {
  t: number; // epoch ms
  close: number | null;
  volume?: number | null;
}

/** One null point inside each gap so the line breaks instead of bridging it. */
export function insertGapBreaks(points: PricePoint[], gaps: Gap[]): ChartPoint[] {
  const out: ChartPoint[] = points.map((p) => ({ t: Date.parse(`${p.date}T00:00:00Z`), close: p.close, volume: p.volume }));
  for (const gap of gaps) {
    const t = Date.parse(`${gap.after}T00:00:00Z`) + 24 * 3600 * 1000;
    out.push({ t, close: null });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

/** Quantile returns applied to a price → price band. */
export function toPriceBand(price: number, q: { q05: number | null; q25: number | null; q50: number | null; q75: number | null; q95: number | null }) {
  const at = (r: number | null) => (r === null ? null : price * (1 + r));
  return { q05: at(q.q05), q25: at(q.q25), q50: at(q.q50), q75: at(q.q75), q95: at(q.q95) };
}

export function epochDay(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}
