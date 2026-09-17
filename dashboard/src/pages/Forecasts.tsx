import { useSearchParams } from "react-router-dom";
import { api } from "../api/api";
import type { HorizonAccuracy } from "../api/types";
import { FanChart } from "../components/charts/FanChart";
import { PageHeader } from "../components/layout/PageHeader";
import { AsOfSelector } from "../components/ui/AsOfSelector";
import { Card } from "../components/ui/Card";
import { Disclaimer } from "../components/ui/Disclaimer";
import { KeyValueList } from "../components/ui/KeyValueList";
import { Maybe } from "../components/ui/Maybe";
import { Measure } from "../components/ui/Measure";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtKes } from "../lib/format";
import { isKnown } from "../lib/measure";

export function Forecasts() {
  const [params, setParams] = useSearchParams();
  const asOf = params.get("as_of") ?? undefined;
  const ticker = (params.get("ticker") ?? "KCB").toUpperCase();
  const listing = useApi("forecast-tickers", (signal) => api.forecasts({}, signal));
  const { data, error, status, loading, refetch } = useApi(`forecasts:${ticker}:${asOf ?? "latest"}`, (signal) => api.forecasts({ ticker, as_of: asOf }, signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  const item = data.items[0];
  const tickers = listing.data?.tickers ?? data.tickers;
  const setTicker = (t: string) => {
    const next = new URLSearchParams(params);
    next.set("ticker", t);
    setParams(next);
  };
  return (
    <>
      <PageHeader title="Forecasts" sub={<span>ranges and probabilities from stored model runs — never price targets</span>}>
        <label className="controls small">
          ticker
          <select value={ticker} onChange={(e) => setTicker(e.target.value)} aria-label="Ticker">
            {(tickers.includes(ticker) ? tickers : [ticker, ...tickers]).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <AsOfSelector dates={data.available_dates} current={data.as_of} />
      </PageHeader>
      <Disclaimer text={data.disclaimer} />
      <div className="grid" style={{ marginTop: 16 }}>
        <Card title={`${ticker} · availability`} asOf={data.as_of}>
          <KeyValueList
            items={[
              { label: "Status", value: <StatusBadge status={data.availability.status} title={data.availability.reason ?? undefined} /> },
              { label: "Reason", value: data.availability.reason ?? "—" },
              { label: "Last known forecast", value: fmtDate(data.latest_known_as_of) },
              { label: "Reference price", value: item?.price != null ? fmtKes(item.price) : "—" },
            ]}
          />
          {data.availability.status !== "known" && data.latest_known_as_of && data.latest_known_as_of !== data.as_of ? (
            <p className="small">
              <button
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.set("as_of", data.latest_known_as_of!);
                  setParams(next);
                }}
              >
                Show the last known forecast ({fmtDate(data.latest_known_as_of)})
              </button>
            </p>
          ) : null}
        </Card>
        {item ? (
          Object.entries(item.models).map(([model, cells]) => (
            <Card key={model} title={`${model}`} subtitle="return distribution per horizon" asOf={item.as_of} span={2}>
              {item.price != null && Object.values(cells).some((c) => isKnown(c.expected_return)) ? <FanChart price={item.price} cells={cells} /> : null}
              <div className="table-wrap" style={{ marginTop: 8 }}>
                <table className="small">
                  <thead>
                    <tr>
                      <th>Horizon</th>
                      <th className="num">Expected</th>
                      <th className="num">q05</th>
                      <th className="num">q25</th>
                      <th className="num">q50</th>
                      <th className="num">q75</th>
                      <th className="num">q95</th>
                      <th className="num">P(+)</th>
                      <th className="num">P(beat)</th>
                      <th className="num">P(dd)</th>
                      <th className="num">Vol</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(cells).map(([h, c]) => {
                      const known = isKnown(c.expected_return);
                      const cell = (v: number | null) => (known ? <Maybe v={v} kind="pct" /> : <span className="muted">—</span>);
                      return (
                        <tr key={h}>
                          <td>{h}</td>
                          <td className="num">
                            <Measure m={c.expected_return} kind="pct" signed showReason={!known} />
                          </td>
                          <td className="num">{cell(c.q05)}</td>
                          <td className="num">{cell(c.q25)}</td>
                          <td className="num">{cell(c.q50)}</td>
                          <td className="num">{cell(c.q75)}</td>
                          <td className="num">{cell(c.q95)}</td>
                          <td className="num">{cell(c.p_positive)}</td>
                          <td className="num">{cell(c.p_outperform)}</td>
                          <td className="num">{cell(c.p_drawdown)}</td>
                          <td className="num">{cell(c.expected_vol)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          ))
        ) : (
          <Card title="No forecast rows">
            <p className="muted">nothing stored for {ticker} on this date</p>
          </Card>
        )}
        <Card title="Scenarios" subtitle="one-year outcomes under stated assumptions" asOf={item?.scenarios?.as_of}>
          {item?.scenarios ? (
            <div className="table-wrap">
              <table className="small">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th className="num">Return</th>
                    <th className="num">Implied price</th>
                  </tr>
                </thead>
                <tbody>
                  {["bear", "base", "bull"].filter((n) => n in item.scenarios!.outcomes).map((n) => {
                    const o = item.scenarios!.outcomes[n];
                    return (
                      <tr key={n}>
                        <td title={typeof o.assumptions.description === "string" ? o.assumptions.description : undefined}>{n}</td>
                        <td className="num">
                          <Measure m={o.implied_return} kind="pct" signed showReason />
                        </td>
                        <td className="num">
                          <Maybe v={o.implied_price} kind="kes" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">no scenario rows for this ticker</p>
          )}
        </Card>
        <Card title="Market regime" subtitle={typeof data.regime.index === "string" ? data.regime.index : undefined} asOf={typeof data.regime.as_of === "string" ? data.regime.as_of : undefined}>
          <KeyValueList
            items={[
              { label: "Status", value: <StatusBadge status={data.regime.status} title={data.regime.reason ?? undefined} /> },
              { label: "Label", value: data.regime.label ?? <span className="muted small">{data.regime.reason}</span> },
              { label: "Trend / volatility / risk", value: [data.regime.trend, data.regime.volatility, data.regime.risk].filter(Boolean).join(" / ") || "—" },
            ]}
          />
        </Card>
        <Card title="Model accuracy" subtitle="walk-forward evaluation of matured forecasts (5 tickers, 120 monthly origins)" span={3}>
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Horizon</th>
                  <th className="num">n</th>
                  <th className="num">MAE</th>
                  <th className="num">RMSE</th>
                  <th className="num">Directional accuracy</th>
                  <th className="num">Benchmark hit rate</th>
                  <th className="num">90 % interval coverage</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.accuracy).flatMap(([model, horizons]) =>
                  Object.entries(horizons).map(([h, a]: [string, HorizonAccuracy]) => (
                    <tr key={`${model}-${h}`}>
                      <td>{model}</td>
                      <td>{h}</td>
                      <td className="num">{a.n}</td>
                      <td className="num">
                        <Measure m={a.mae} kind="pct" />
                      </td>
                      <td className="num">
                        <Measure m={a.rmse} kind="pct" />
                      </td>
                      <td className="num">
                        <Measure m={a.directional_accuracy} kind="pct" />
                      </td>
                      <td className="num">
                        <Measure m={a.benchmark_hit_rate} kind="pct" />
                      </td>
                      <td className="num">
                        <Measure m={a.interval_coverage} kind="pct" />
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
          <div className="chips" style={{ marginTop: 8 }}>
            {data.models.map((m) => (
              <span key={`${m.name}${m.version}`} className="chip">
                {m.name} v{m.version} · <StatusBadge status={m.status} />
              </span>
            ))}
          </div>
        </Card>
      </div>
      <Disclaimer text={data.disclaimer} />
    </>
  );
}
