import type { Statements } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Measure, type MeasureKind } from "../../components/ui/Measure";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { titleCase } from "../../lib/format";

const KIND: Record<string, MeasureKind> = { revenue: "compactkes", net_income: "compactkes", equity: "compactkes", total_assets: "compactkes", ocf: "compactkes", fcf: "compactkes", eps: "kes", dps: "kes" };

export function StatementsTable({ statements }: { statements: Statements }) {
  if (statements.years.length === 0) {
    return (
      <Card title="Financial statements" asOf={statements.as_of}>
        <StatusBadge status={statements.availability.status} /> <span className="muted">{statements.availability.reason}</span>
      </Card>
    );
  }
  const currency = statements.years[0].currency;
  return (
    <Card title="Financial statements" subtitle={`annual, point-in-time${currency && currency !== "KES" ? ` · reported in ${currency}` : ""}`} asOf={statements.as_of} span={3}>
      <div className="table-wrap">
        <table className="small">
          <thead>
            <tr>
              <th>Concept</th>
              {statements.years.map((y) => (
                <th key={y.period_end} className="num" title={y.period_end}>
                  {y.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {statements.concepts.map((c) => (
              <tr key={c}>
                <td>{titleCase(c)}</td>
                {statements.years.map((y) => (
                  <td key={y.period_end} className="num">
                    <Measure m={y.values[c]} kind={KIND[c] ?? "num"} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
