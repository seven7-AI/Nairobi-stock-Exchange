import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EquityPoint } from "../../api/types";
import { fmtDate } from "../../lib/format";
import { chrome, series } from "../../lib/palette";
import { epochDay } from "../../lib/series";

/** Portfolio and benchmarks rebased to 100 at the first day. */
export function EquityCurve({ equity, benchmarks, height = 280 }: { equity: EquityPoint[]; benchmarks: string[]; height?: number }) {
  if (equity.length === 0) return <p className="muted">no equity curve stored</p>;
  const first = equity[0];
  const base: Record<string, number | null> = { portfolio: first.equity };
  for (const b of benchmarks) base[b] = first.benchmarks[b] ?? null;
  const data = equity.map((p) => {
    const row: Record<string, number | null> = { t: epochDay(p.day), portfolio: (p.equity / first.equity) * 100 };
    for (const b of benchmarks) {
      const v = p.benchmarks[b];
      const b0 = base[b];
      row[b] = v == null || b0 == null || b0 === 0 ? null : (v / b0) * 100;
    }
    return row;
  });
  const keys = ["portfolio", ...benchmarks];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={chrome("grid")} vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t: number) => new Date(t).getUTCFullYear().toString()} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} minTickGap={40} />
        <YAxis domain={["auto", "auto"]} width={48} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 12 }} labelFormatter={(t) => fmtDate(new Date(Number(t)).toISOString().slice(0, 10))} formatter={(v, name) => [typeof v === "number" ? v.toFixed(1) : "—", String(name)]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {keys.map((k, i) => (
          <Line key={k} type="monotone" dataKey={k} stroke={series(i)} strokeWidth={k === "portfolio" ? 2 : 1.5} dot={false} connectNulls={false} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
