import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EquityPoint } from "../../api/types";
import { fmtDate } from "../../lib/format";
import { chrome } from "../../lib/palette";
import { epochDay } from "../../lib/series";

export function DrawdownChart({ equity, height = 160 }: { equity: EquityPoint[]; height?: number }) {
  if (equity.length === 0) return null;
  const data = equity.map((p) => ({ t: epochDay(p.day), dd: p.drawdown * 100 }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={chrome("grid")} vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t: number) => new Date(t).getUTCFullYear().toString()} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} minTickGap={40} />
        <YAxis domain={["auto", 0]} width={48} stroke={chrome("axis")} tick={{ fill: "#898781", fontSize: 11 }} tickFormatter={(v: number) => `${v.toFixed(0)} %`} />
        <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 12 }} labelFormatter={(t) => fmtDate(new Date(Number(t)).toISOString().slice(0, 10))} formatter={(v) => [typeof v === "number" ? `${v.toFixed(1)} %` : "—", "drawdown"]} />
        <Area type="monotone" dataKey="dd" stroke="var(--neg)" fill="var(--neg)" fillOpacity={0.18} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
