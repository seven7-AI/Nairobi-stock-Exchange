import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/api";
import type { SignalItem, ValuationItem } from "../api/types";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Disclaimer } from "../components/ui/Disclaimer";
import { Maybe } from "../components/ui/Maybe";
import { Measure } from "../components/ui/Measure";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtNum } from "../lib/format";

export function Signals() {
  const [params] = useSearchParams();
  const asOf = params.get("as_of") ?? undefined;
  const { data, error, status, loading, refetch } = useApi(`signals:${asOf ?? "latest"}`, (signal) => api.signals(asOf, signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  return (
    <>
      <PageHeader title="Research signals" sub={`${data.model} · ${data.scored} of ${data.universe} instruments scored on ${fmtDate(data.as_of)} · every row links to the numbers behind it`} />
      <Disclaimer text={data.disclaimer} />
      <div className="grid" style={{ marginTop: 16 }}>
        <SignalCard title="Buy candidates" items={data.buy_candidates} tone="ok" />
        <SignalCard title="Watch" items={data.watch} tone="info" />
        <SignalCard title="Neutral / weak / avoid" items={[...data.neutral, ...data.weak, ...data.avoid]} tone="warn" />
        <SignalCard
          title="Potential value traps"
          items={data.value_traps}
          tone="error"
          extra={(i) => (
            <>
              <StatusBadge status={`${i.extra.risk_label ?? "?"} risk`} tone={i.extra.risk === 2 ? "error" : "warn"} />
              <span className="chips" style={{ marginTop: 4 }}>
                {(i.extra.signals ?? []).map((s) => (
                  <span key={s} className="chip">
                    {s}
                  </span>
                ))}
              </span>
            </>
          )}
        />
        <SignalCard
          title={`Potential compounders (≥ ${data.compounder_threshold})`}
          items={data.compounders}
          tone="ok"
          extra={(i) => (
            <>
              <b>{typeof i.extra.compounder_score === "number" ? fmtNum(i.extra.compounder_score, 0) : "?"}</b> <span className="muted small">{i.extra.reason}</span>
              <span className="chips" style={{ marginTop: 4 }}>
                {(i.extra.criteria_met ?? []).map((s) => (
                  <span key={s} className="chip">
                    {s}
                  </span>
                ))}
              </span>
            </>
          )}
        />
        <ValuationCard title="Valuation upside" items={data.valuation_upside} />
        <ValuationCard title="Valuation downside" items={data.valuation_downside} />
        <SignalCard title="Positive factor combinations" items={data.factor_combinations.positive} tone="ok" />
        <SignalCard title="Negative factor combinations" items={data.factor_combinations.negative} tone="error" />
        <Card title="Risk flags" subtitle={`${data.risk_flags.length} open error / warning findings and unscored factors`} span={3}>
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
            <table className="small">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Check</th>
                  <th>Ticker</th>
                  <th>Date</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.risk_flags.map((f, i) => (
                  <tr key={`${f.kind}-${f.ticker_symbol}-${f.check_name}-${i}`}>
                    <td>
                      <StatusBadge status={f.severity} />
                    </td>
                    <td>{f.check_name ?? f.kind}</td>
                    <td>{f.ticker_symbol ? <Link to={`/stocks/${f.ticker_symbol}`}>{f.ticker_symbol}</Link> : <span className="muted">market</span>}</td>
                    <td>{fmtDate(f.trade_date)}</td>
                    <td style={{ whiteSpace: "normal" }}>{f.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Not scored" subtitle={`${data.unscored} instruments, by reason`} span={3}>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {Object.entries(data.unscored_reasons).map(([reason, n]) => (
              <li key={reason}>
                <b>{n}</b> — {reason}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Disclaimer text={data.disclaimer} />
    </>
  );
}

function SignalCard({ title, items, tone, extra }: { title: string; items: SignalItem[]; tone: "ok" | "info" | "warn" | "error"; extra?: (i: SignalItem) => ReactNode }) {
  return (
    <Card title={title} subtitle={`${items.length} instrument${items.length === 1 ? "" : "s"}`}>
      {items.length === 0 ? (
        <p className="muted">none on this date</p>
      ) : (
        items.map((i) => (
          <details key={i.ticker_symbol} style={{ marginBottom: 6 }}>
            <summary>
              <Link to={i.link}>{i.ticker_symbol}</Link> <span className="muted small">{i.sector}</span> <StatusBadge status={i.classification ?? "unscored"} tone={i.classification ? undefined : "muted"} /> score <Measure m={i.overall_score} kind="score" /> <span className="muted small">#{i.market_rank ?? "—"} · conf {fmtNum(i.confidence, 2)}</span>
            </summary>
            <div className="small" style={{ padding: "4px 0 4px 16px" }}>
              {extra ? <div style={{ marginBottom: 4 }}>{extra(i)}</div> : null}
              {i.positive_factors.map((f) => (
                <div key={f} className="pos">
                  + {f}
                </div>
              ))}
              {i.negative_factors.map((f) => (
                <div key={f} className="neg">
                  − {f}
                </div>
              ))}
              <span className={`badge badge--${tone}`} style={{ marginTop: 4 }}>
                {title}
              </span>
            </div>
          </details>
        ))
      )}
    </Card>
  );
}

function ValuationCard({ title, items }: { title: string; items: ValuationItem[] }) {
  return (
    <Card title={title} subtitle="known blended valuations">
      {items.length === 0 ? (
        <p className="muted">none on this date</p>
      ) : (
        <div className="table-wrap">
          <table className="small">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Price</th>
                <th className="num">Intrinsic</th>
                <th className="num">Upside</th>
                <th className="num">MoS</th>
                <th className="num">Uncert.</th>
                <th>Methods</th>
              </tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.ticker_symbol}>
                  <td>
                    <Link to={v.link}>{v.ticker_symbol}</Link> {v.actionable ? "" : <span className="muted small">(not actionable)</span>}
                  </td>
                  <td className="num">
                    <Maybe v={v.price} kind="kes" />
                  </td>
                  <td className="num">
                    <Measure m={v.intrinsic} kind="kes" />
                  </td>
                  <td className="num">
                    <Maybe v={v.upside} kind="pct" />
                  </td>
                  <td className="num">
                    <Maybe v={v.margin_of_safety} kind="pct" />
                  </td>
                  <td className="num">
                    <Maybe v={v.uncertainty} kind="num" />
                  </td>
                  <td className="muted">{v.methods_used.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
