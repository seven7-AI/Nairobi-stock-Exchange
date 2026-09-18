import { useSearchParams } from "react-router-dom";
import { api } from "../api/api";
import { DrawdownChart } from "../components/charts/DrawdownChart";
import { EquityCurve } from "../components/charts/EquityCurve";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Disclaimer } from "../components/ui/Disclaimer";
import { KeyValueList } from "../components/ui/KeyValueList";
import { Measure } from "../components/ui/Measure";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtInt, fmtNum, fmtPct, titleCase } from "../lib/format";

export function Backtests() {
  const [params, setParams] = useSearchParams();
  const list = useApi("backtests", (signal) => api.backtests(signal));
  const runs = list.data?.items ?? [];
  const selected = Number(params.get("run") ?? (runs.find((r) => r.purpose === "run")?.run_id ?? runs[0]?.run_id ?? 0));
  const detail = useApi(selected ? `backtest:${selected}` : null, (signal) => api.backtest(selected, signal));
  const registry = useApi("status", (signal) => api.status(signal));
  const modelStatus = (model: string): string | null => {
    const [name, version] = model.split(" v");
    return registry.data?.models.find((m) => m.name === name && m.version === version)?.status ?? null;
  };
  if (list.loading) return <Loading />;
  if (list.error || !list.data) return <ErrorState error={list.error ?? "no data"} status={list.status} onRetry={list.refetch} />;
  const d = detail.data;
  return (
    <>
      <PageHeader title="Backtests" sub="point-in-time simulations of the ranking model on the archive, after modelled costs" />
      <Card title="Stored runs" subtitle="oldest first; benchmark companions are equal-weight portfolios of the same universe">
        <div className="table-wrap">
          <table className="small">
            <thead>
              <tr>
                <th></th>
                <th>Run</th>
                <th>Purpose</th>
                <th>Model</th>
                <th>Period</th>
                <th className="num">Top N</th>
                <th className="num">Cost rate</th>
                <th>Status</th>
                <th className="num">Total return</th>
                <th className="num">CAGR</th>
                <th className="num">Sharpe</th>
                <th className="num">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} style={r.run_id === selected ? { background: "var(--surface-2)" } : undefined}>
                  <td>
                    <button type="button" aria-pressed={r.run_id === selected} onClick={() => setParams({ run: String(r.run_id) })}>
                      view
                    </button>
                  </td>
                  <td>{r.name}</td>
                  <td>{r.purpose}</td>
                  <td>{r.model}</td>
                  <td>
                    {fmtDate(r.start_date)} → {fmtDate(r.end_date)}
                  </td>
                  <td className="num">{r.top_n}</td>
                  <td className="num">{fmtPct(r.cost_rate, 2)}</td>
                  <td>
                    <StatusBadge status={r.status} title={r.reason ?? undefined} />
                  </td>
                  <td className="num">
                    <Measure m={r.linked_total_return} kind="pct" signed />
                  </td>
                  <td className="num">
                    <Measure m={r.first_segment.cagr} kind="pct" signed />
                  </td>
                  <td className="num">
                    <Measure m={r.first_segment.sharpe} kind="num" />
                  </td>
                  <td className="num">
                    <Measure m={r.first_segment.max_drawdown} kind="pct" signed />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid" style={{ marginTop: 16 }}>
        {detail.loading && !d ? (
          <Loading />
        ) : detail.error ? (
          <ErrorState error={detail.error} status={detail.status} onRetry={detail.refetch} />
        ) : d ? (
          <>
            <Card title={`${d.run.name} · equity vs benchmarks`} subtitle="rebased to 100 at the first day; benchmarks break where the index archive has holes" span={3}>
              <EquityCurve equity={d.equity} benchmarks={d.run.benchmarks} />
              <DrawdownChart equity={d.equity} />
            </Card>
            <Card title="Headline" subtitle="first segment, portfolio series">
              <KeyValueList
                items={Object.entries(d.results["1"]?.portfolio ?? {})
                  .filter(([k]) => ["total_return", "cagr", "annualised_return", "volatility", "sharpe", "sortino", "calmar", "max_drawdown", "monthly_win_rate", "best_year", "worst_year", "avg_monthly_turnover", "costs_paid", "alpha_vs_^NASI", "beta_vs_^NASI", "information_ratio_vs_^NASI"].includes(k))
                  .map(([k, m]) => ({ label: titleCase(k), value: <Measure m={m} kind={["sharpe", "sortino", "calmar", "beta_vs_^NASI", "information_ratio_vs_^NASI"].includes(k) ? "num" : k === "costs_paid" ? "compactkes" : "pct"} signed={k !== "costs_paid"} /> }))}
              />
              <p className="small" style={{ marginTop: 8 }}>
                model {d.run.model} <StatusBadge status={modelStatus(d.run.model) ?? "unregistered"} title="registry status: a candidate model is not used live" /> · max drawdown from the curve <Measure m={d.max_drawdown} kind="pct" signed />
              </p>
            </Card>
            <Card title="Benchmarks" subtitle="the same metrics for each benchmark series">
              <div className="table-wrap">
                <table className="small">
                  <thead>
                    <tr>
                      <th>Series</th>
                      <th className="num">Total return</th>
                      <th className="num">CAGR</th>
                      <th className="num">Volatility</th>
                      <th className="num">Sharpe</th>
                      <th className="num">Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.results["1"] ?? {}).map(([series, metrics]) => (
                      <tr key={series}>
                        <td>{series}</td>
                        <td className="num">
                          <Measure m={metrics.total_return} kind="pct" signed />
                        </td>
                        <td className="num">
                          <Measure m={metrics.cagr} kind="pct" signed />
                        </td>
                        <td className="num">
                          <Measure m={metrics.volatility} kind="pct" />
                        </td>
                        <td className="num">
                          <Measure m={metrics.sharpe} kind="num" />
                        </td>
                        <td className="num">
                          <Measure m={metrics.max_drawdown} kind="pct" signed />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Configuration" subtitle="factor weights and cost model">
              <KeyValueList
                items={[
                  ...Object.entries(d.weights).map(([k, v]) => ({ label: `weight ${k}`, value: fmtPct(v, 0) })),
                  ...Object.entries(d.costs).map(([k, v]) => ({ label: `cost ${k}`, value: fmtPct(v, 2) })),
                  { label: "Rebalances", value: fmtInt(d.turnover.length) },
                  { label: "Costs paid", value: <Measure m={d.results["1"]?.portfolio?.costs_paid} kind="compactkes" /> },
                  { label: "Average trades per rebalance", value: d.turnover.length ? fmtNum(d.turnover.reduce((s, t) => s + t.buys + t.sells + t.exits, 0) / d.turnover.length, 1) : "—" },
                ]}
              />
              <Disclaimer text={d.disclaimer} />
            </Card>
          </>
        ) : (
          <Card title="No runs">
            <p className="muted">no backtest has been stored yet</p>
          </Card>
        )}
      </div>
    </>
  );
}
