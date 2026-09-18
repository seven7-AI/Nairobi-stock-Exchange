import type { Profile } from "../../api/types";
import { RangeBar } from "../../components/charts/RangeBar";
import { Card } from "../../components/ui/Card";
import { KeyValueList } from "../../components/ui/KeyValueList";
import { Maybe } from "../../components/ui/Maybe";
import { Measure } from "../../components/ui/Measure";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { titleCase } from "../../lib/format";

export function ValuationCard({ valuation, asOf }: { valuation: Profile["valuation"]; asOf: string | null }) {
  if (!valuation.intrinsic) {
    return (
      <Card title="Valuation" asOf={asOf}>
        <StatusBadge status={valuation.status ?? "unavailable"} /> <span className="muted">{valuation.reason}</span>
      </Card>
    );
  }
  const methods = Object.entries(valuation.methods ?? {});
  return (
    <Card title="Valuation" subtitle="blended intrinsic value against the price" asOf={asOf} span={2}>
      <RangeBar bear={valuation.fair_low} base={valuation.intrinsic.value} bull={valuation.fair_high} price={valuation.price} />
      <KeyValueList
        items={[
          { label: "Intrinsic", value: <Measure m={valuation.intrinsic} kind="kes" showReason /> },
          { label: "Price", value: <Maybe v={valuation.price} kind="kes" /> },
          { label: "Upside", value: <Maybe v={valuation.upside} kind="pct" /> },
          { label: "Margin of safety", value: <Maybe v={valuation.margin_of_safety} kind="pct" /> },
          { label: "Uncertainty", value: <Maybe v={valuation.uncertainty} kind="num" /> },
          { label: "Actionable", value: valuation.actionable == null ? "—" : valuation.actionable ? "yes" : "no" },
        ]}
      />
      {methods.length ? (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="small">
            <thead>
              <tr>
                <th>Method</th>
                <th>Status</th>
                <th className="num">Bear</th>
                <th className="num">Base</th>
                <th className="num">Bull</th>
                <th>Assumptions</th>
              </tr>
            </thead>
            <tbody>
              {methods.map(([name, m]) => (
                <tr key={name}>
                  <td>{titleCase(name)}</td>
                  <td>
                    <StatusBadge status={m.status} title={m.reason ?? undefined} />
                  </td>
                  <td className="num">
                    <Maybe v={m.bear} kind="kes" reason={m.reason ?? undefined} />
                  </td>
                  <td className="num">
                    <Maybe v={m.base} kind="kes" reason={m.reason ?? undefined} />
                  </td>
                  <td className="num">
                    <Maybe v={m.bull} kind="kes" reason={m.reason ?? undefined} />
                  </td>
                  <td style={{ whiteSpace: "normal", maxWidth: 360 }} className="muted">
                    {m.reason ?? summarise(m.assumptions)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
}

function summarise(a: Record<string, unknown>): string {
  return Object.entries(a)
    .filter(([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean")
    .slice(0, 6)
    .map(([k, v]) => `${k}=${typeof v === "number" ? Number(v.toFixed(4)) : String(v)}`)
    .join(" · ");
}
