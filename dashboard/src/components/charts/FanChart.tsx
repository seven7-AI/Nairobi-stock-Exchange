import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastCell } from "../../api/types";
import { fmtKes } from "../../lib/format";
import { isKnown } from "../../lib/measure";
import { chrome, series } from "../../lib/palette";

const HORIZONS: [string, number][] = [
  ["1m", 1],
  ["3m", 3],
  ["6m", 6],
  ["12m", 12],
];

/** q05–q95 and q25–q75 bands with the median, as prices from the reference close. */
export function FanChart({ price, cells, height = 240 }: { price: number; cells: Record<string, ForecastCell>; height?: number }) {
  const rows = [{ m: 0, lo: price, hi: price, ilo: price, ihi: price, med: price }];
  for (const [h, months] of HORIZONS) {
    const c = cells[h];
    if (!c || !isKnown(c.expected_return) || c.q05 == null || c.q95 == null || c.q50 == null) continue;
    rows.push({ m: months, lo: price * (1 + c.q05), hi: price * (1 + c.q95), ilo: price * (1 + (c.q25 ?? c.q05)), ihi: price * (1 + (c.q75 ?? c.q95)), med: price * (1 + c.q50) });
  }
  if (rows.length < 2) return <p className="muted">no known quantiles to draw</p>;
  const color = series(0);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={chrome("grid")} vertical={false} />
        <XAxis dataKey="m" type="number" domain={[0, 12]} ticks={[0, 1, 3, 6, 12]} tickFormatter={(m: number) => (m === 0 ? "now" : `${m}m`)} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} />
        <YAxis domain={["auto", "auto"]} width={62} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} tickFormatter={(v: number) => v.toLocaleString("en-KE", { maximumFractionDigits: 0 })} />
        <Tooltip
          contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 12 }}
          labelFormatter={(m) => (Number(m) === 0 ? "now" : `${m} months`)}
          formatter={(v, name) => [typeof v === "number" ? fmtKes(v) : "—", String(name)]}
        />
        <Area type="monotone" dataKey="hi" stroke="none" fill={color} fillOpacity={0.12} isAnimationActive={false} name="q95" />
        <Area type="monotone" dataKey="lo" stroke="none" fill="var(--surface)" fillOpacity={1} isAnimationActive={false} name="q05" />
        <Area type="monotone" dataKey="ihi" stroke="none" fill={color} fillOpacity={0.2} isAnimationActive={false} name="q75" />
        <Area type="monotone" dataKey="ilo" stroke="none" fill="var(--surface)" fillOpacity={1} isAnimationActive={false} name="q25" />
        <Line type="monotone" dataKey="med" stroke={color} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} name="median" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
