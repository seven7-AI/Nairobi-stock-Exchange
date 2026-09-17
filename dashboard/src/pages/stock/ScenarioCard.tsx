import type { Profile } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Maybe } from "../../components/ui/Maybe";
import { Measure } from "../../components/ui/Measure";
import { StatusBadge } from "../../components/ui/StatusBadge";

const ORDER = ["bear", "base", "bull"];

export function ScenarioCard({ scenarios, asOf }: { scenarios: Profile["scenarios"]; asOf: string | null }) {
  const outcomes = scenarios.outcomes ?? {};
  const names = [...ORDER.filter((n) => n in outcomes), ...Object.keys(outcomes).filter((n) => !ORDER.includes(n))];
  return (
    <Card title="Scenarios" subtitle="one-year outcomes under stated assumptions" asOf={asOf}>
      {names.length === 0 ? (
        <p>
          <StatusBadge status={scenarios.status ?? "unavailable"} /> <span className="muted">{scenarios.reason}</span>
        </p>
      ) : (
        <div className="table-wrap">
          <table className="small">
            <thead>
              <tr>
                <th>Scenario</th>
                <th className="num">Return</th>
                <th className="num">Implied price</th>
                <th>Assumptions</th>
              </tr>
            </thead>
            <tbody>
              {names.map((n) => {
                const o = outcomes[n];
                const a = o.assumptions ?? {};
                return (
                  <tr key={n}>
                    <td>{n}</td>
                    <td className="num">
                      <Measure m={o.implied_return} kind="pct" signed showReason />
                    </td>
                    <td className="num">
                      <Maybe v={o.implied_price} kind="kes" />
                    </td>
                    <td style={{ whiteSpace: "normal", maxWidth: 380 }} className="muted">
                      {typeof a.description === "string" ? a.description : ""}
                      {typeof a.market_return === "number" ? ` · market ${(a.market_return * 100).toFixed(0)} %` : ""}
                      {typeof a.multiple_change === "number" ? ` · multiple ${(a.multiple_change * 100).toFixed(0)} %` : ""}
                      {typeof a.earnings_growth === "number" ? ` · earnings ${(a.earnings_growth * 100).toFixed(0)} %` : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
