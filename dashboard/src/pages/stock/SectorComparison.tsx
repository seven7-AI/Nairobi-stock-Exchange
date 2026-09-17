import type { SectorComparisonRow } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Maybe } from "../../components/ui/Maybe";
import { Measure, type MeasureKind } from "../../components/ui/Measure";
import { titleCase } from "../../lib/format";

const KIND: Record<string, MeasureKind> = { return_1m: "pct", return_12m: "pct", volatility_annualised: "pct", market_cap: "compactkes", avg_daily_volume: "int", pe: "ratio", pb: "ratio", dividend_yield: "pct", roe: "pct", net_margin: "pct", revenue_growth_1y: "pct" };

export function SectorComparison({ rows, sector }: { rows: SectorComparisonRow[]; sector: string | null }) {
  return (
    <Card title="Versus the sector" subtitle={sector ? `median of ${sector} peers` : "sector medians"} span={2}>
      <div className="table-wrap">
        <table className="small">
          <thead>
            <tr>
              <th>Metric</th>
              <th className="num">Stock</th>
              <th className="num">Sector median</th>
              <th className="num">Peers (known)</th>
              <th className="num">Percentile</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric}>
                <td>{titleCase(r.metric)}</td>
                <td className="num">
                  <Measure m={r.stock} kind={KIND[r.metric] ?? "num"} />
                </td>
                <td className="num">
                  <Measure m={r.sector_median} kind={KIND[r.metric] ?? "num"} />
                </td>
                <td className="num">
                  {r.sector_members} ({r.known_peers})
                </td>
                <td className="num">
                  <Maybe v={r.percentile_in_sector} kind="num" digits={0} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
