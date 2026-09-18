import { useState } from "react";
import type { Availability, ForecastCell, Profile } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Disclaimer } from "../../components/ui/Disclaimer";
import { Maybe } from "../../components/ui/Maybe";
import { Measure } from "../../components/ui/Measure";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fmtDate, fmtKes } from "../../lib/format";
import { isKnown } from "../../lib/measure";

const HORIZONS = ["1m", "3m", "6m", "12m"];

export function ForecastCard({ forecast, availability, price, asOf }: { forecast: Profile["forecast"]; availability: Availability; price: number | null; asOf: string | null }) {
  const models = Object.keys(forecast.models ?? {});
  const [model, setModel] = useState(models.includes("ar1") ? "ar1" : (models[0] ?? ""));
  const cells = forecast.models?.[model] ?? {};
  return (
    <Card
      title="Forecasts"
      subtitle="return distributions per horizon — ranges and probabilities, not price targets"
      asOf={asOf}
      span={2}
      actions={
        models.length > 1 ? (
          <div className="controls">
            {models.map((m) => (
              <button key={m} type="button" aria-pressed={m === model} onClick={() => setModel(m)}>
                {m}
              </button>
            ))}
          </div>
        ) : undefined
      }
    >
      {availability.status !== "known" ? (
        <p>
          <StatusBadge status={availability.status} /> <span className="muted">{availability.reason}</span>
          {availability.latest_known_as_of ? <span className="muted"> · last known forecast {fmtDate(availability.latest_known_as_of)}</span> : null}
        </p>
      ) : null}
      {models.length === 0 ? (
        <p className="muted">{forecast.reason ?? "no forecast rows"}</p>
      ) : (
        <div className="table-wrap">
          <table className="small">
            <thead>
              <tr>
                <th>Horizon</th>
                <th className="num">Expected</th>
                <th className="num">q05</th>
                <th className="num">q50</th>
                <th className="num">q95</th>
                <th className="num">P(+)</th>
                <th className="num">P(beat ^NASI)</th>
                <th className="num">P(dd &gt; 20 %)</th>
                {price != null ? <th>Price band (q05 – q95)</th> : null}
              </tr>
            </thead>
            <tbody>
              {HORIZONS.filter((h) => h in cells).map((h) => (
                <ForecastRow key={h} h={h} c={cells[h]} price={price} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Disclaimer text="Stored outputs of statistical models fitted to past monthly returns; quantiles are model ranges, not targets. Not investment advice." />
    </Card>
  );
}

function ForecastRow({ h, c, price }: { h: string; c: ForecastCell; price: number | null }) {
  const known = isKnown(c.expected_return);
  return (
    <tr>
      <td>{h}</td>
      <td className="num">
        <Measure m={c.expected_return} kind="pct" signed showReason={!known} />
      </td>
      <td className="num">{known ? <Maybe v={c.q05} kind="pct" /> : <span className="muted">—</span>}</td>
      <td className="num">{known ? <Maybe v={c.q50} kind="pct" /> : <span className="muted">—</span>}</td>
      <td className="num">{known ? <Maybe v={c.q95} kind="pct" /> : <span className="muted">—</span>}</td>
      <td className="num">{known ? <Maybe v={c.p_positive} kind="pct" /> : <span className="muted">—</span>}</td>
      <td className="num">{known ? <Maybe v={c.p_outperform} kind="pct" /> : <span className="muted">—</span>}</td>
      <td className="num">{known ? <Maybe v={c.p_drawdown} kind="pct" /> : <span className="muted">—</span>}</td>
      {price != null ? <td>{known && c.q05 != null && c.q95 != null ? `${fmtKes(price * (1 + c.q05))} – ${fmtKes(price * (1 + c.q95))}` : <span className="muted">—</span>}</td> : null}
    </tr>
  );
}
