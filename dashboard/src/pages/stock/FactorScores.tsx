import type { FactorScore } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Maybe } from "../../components/ui/Maybe";
import { Measure } from "../../components/ui/Measure";
import { Percentile } from "../../components/ui/Percentile";
import { titleCase } from "../../lib/format";

export function FactorScores({ factors, asOf }: { factors: Record<string, FactorScore>; asOf: string | null }) {
  const names = Object.keys(factors);
  if (names.length === 0) return null;
  return (
    <Card title="Factor scores" subtitle="score and percentile within market / sector / industry" asOf={asOf} span={2}>
      <div className="table-wrap">
        <table className="small">
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Score</th>
              <th className="num">Coverage</th>
              <th>Market</th>
              <th>Sector</th>
              <th>Industry</th>
            </tr>
          </thead>
          <tbody>
            {names.map((name) => {
              const f = factors[name];
              return (
                <tr key={name}>
                  <td>{titleCase(name)}</td>
                  <td className="num">
                    <Measure m={f.score} kind="score" showReason />
                  </td>
                  <td className="num">
                    <Maybe v={f.coverage} kind="pct" />
                  </td>
                  <td>
                    <Percentile value={f.percentile_market} label="market" />
                  </td>
                  <td>
                    <Percentile value={f.percentile_sector} label="sector" />
                  </td>
                  <td>
                    <Percentile value={f.percentile_industry} label="industry" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
