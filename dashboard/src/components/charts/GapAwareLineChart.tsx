import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Gap, PricePoint } from "../../api/types";
import { fmtDate, fmtKes } from "../../lib/format";
import { chrome, series } from "../../lib/palette";
import { epochDay, insertGapBreaks } from "../../lib/series";

/**
 * A close-price line that breaks at every gap and shades the gap itself, so the
 * 572-day hole (2024-12-31 → 2026-07-26) is visible instead of bridged.
 */
export function GapAwareLineChart({ points, gaps, missingStart, height = 260 }: { points: PricePoint[]; gaps: Gap[]; missingStart?: { from: string; to: string; days: number } | null; height?: number }) {
  const data = insertGapBreaks(points, gaps);
  const color = series(0);
  const holes = [
    ...gaps.map((g) => ({ from: epochDay(g.after), to: epochDay(g.before), days: g.days, key: g.after })),
    ...(missingStart ? [{ from: epochDay(missingStart.from), to: epochDay(missingStart.to), days: missingStart.days, key: `start-${missingStart.from}` }] : []),
  ];
  if (data.length === 0) return <p className="muted">no observations in this window</p>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={chrome("grid")} vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t: number) => fmtDate(new Date(t).toISOString().slice(0, 10))} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} minTickGap={40} />
        <YAxis domain={["auto", "auto"]} width={58} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} tickFormatter={(v: number) => v.toLocaleString("en-KE", { maximumFractionDigits: 0 })} />
        <Tooltip
          contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 12 }}
          labelFormatter={(t) => fmtDate(new Date(Number(t)).toISOString().slice(0, 10))}
          formatter={(v) => [typeof v === "number" ? fmtKes(v) : "—", "close"]}
        />
        {holes.map((h) => (
          <ReferenceArea key={h.key} x1={h.from} x2={h.to} fill={chrome("gap")} strokeOpacity={0} label={{ value: `no data · ${h.days} d`, position: "insideTop", fill: "#898781", fontSize: 11 }} />
        ))}
        <Line type="monotone" dataKey="close" stroke={color} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
