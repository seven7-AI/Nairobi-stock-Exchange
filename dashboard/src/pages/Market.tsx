import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/api";
import type { Quote } from "../api/types";
import { BarList } from "../components/charts/BarList";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { DataTable, type Column } from "../components/ui/DataTable";
import { KeyValueList } from "../components/ui/KeyValueList";
import { Measure } from "../components/ui/Measure";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtInt, fmtNum } from "../lib/format";
import { valueOf } from "../lib/measure";

const WINDOWS: ("1d" | "1w" | "1m")[] = ["1d", "1w", "1m"];

export function Market() {
  const { data, error, status, loading, refetch } = useApi("market", (signal) => api.market(undefined, signal));
  const [window_, setWindow] = useState<"1d" | "1w" | "1m">("1d");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  const sectors = data.performance[window_] ?? [];
  const metric = `return_${window_}`;
  const cov = data.coverage[metric] ?? {};
  const known = (cov.known ?? 0) + (cov.zero ?? 0);
  const total = Object.values(cov).reduce((s, v) => s + v, 0);
  return (
    <>
      <PageHeader title="Market" sub={`prices as scraped on ${fmtDate(data.latest_market_date)} · ${data.stocks_with_data} of ${data.universe} instruments with a price · metrics as of ${fmtDate(data.as_of)}`} />
      <div className="grid">
        <Card title="Indices" subtitle="benchmarks the engine measures against">
          <KeyValueList
            items={Object.entries(data.index).map(([symbol, i]) => ({
              label: symbol,
              value:
                i.status === "known" ? (
                  <>
                    {i.last != null ? fmtNum(i.last, 2) : "—"} <span className="muted small">on {fmtDate(i.latest_known_as_of)}</span>
                  </>
                ) : (
                  <>
                    <StatusBadge status="unavailable" title={i.reason ?? undefined} /> <span className="muted small">{i.reason}</span>
                    {i.last != null ? (
                      <div className="muted small">
                        last level {fmtNum(i.last, 2)} on {fmtDate(i.latest_known_as_of)}
                      </div>
                    ) : null}
                  </>
                ),
            }))}
          />
        </Card>
        <Card
          title="Sector performance"
          subtitle={`median ${metric} · ${known} of ${total} instruments have a value`}
          actions={
            <div className="controls">
              {WINDOWS.map((w) => (
                <button key={w} type="button" aria-pressed={w === window_} onClick={() => setWindow(w)}>
                  {w}
                </button>
              ))}
            </div>
          }
          span={2}
        >
          <BarList
            items={sectors.map((s) => ({
              key: s.sector,
              label: (
                <span>
                  {s.sector} <span className="muted small">{s.known_members}/{s.members}</span>
                </span>
              ),
              value: s.median,
              hint: `${s.known_members} of ${s.members} members with a known ${metric}`,
            }))}
          />
        </Card>
        <Card title="Top movers" subtitle="scraped daily change">
          <Movers quotes={data.top_movers} />
        </Card>
        <Card title="Bottom movers" subtitle="scraped daily change">
          <Movers quotes={data.bottom_movers} />
        </Card>
        <Card title="Prices" subtitle="every classified equity" span={3}>
          <DataTable rows={data.quotes} rowKey={(q) => q.ticker_symbol} columns={QUOTE_COLUMNS} searchable searchText={(q) => `${q.ticker_symbol} ${q.company_name ?? ""} ${q.sector ?? ""}`} initialSort="ticker" dense />
        </Card>
      </div>
    </>
  );
}

function Movers({ quotes }: { quotes: Quote[] }) {
  if (quotes.length === 0) return <p className="muted">no scraped changes today</p>;
  return (
    <BarList
      items={quotes.map((q) => ({
        key: q.ticker_symbol,
        label: (
          <Link to={`/stocks/${q.ticker_symbol}`} title={q.company_name ?? undefined}>
            {q.ticker_symbol}
          </Link>
        ),
        value: q.change_pct,
      }))}
      kind="pctpoints"
    />
  );
}

export const QUOTE_COLUMNS: Column<Quote>[] = [
  { key: "ticker", header: "Ticker", cell: (q) => <Link to={`/stocks/${q.ticker_symbol}`}>{q.ticker_symbol}</Link>, sortValue: (q) => q.ticker_symbol },
  { key: "name", header: "Company", cell: (q) => q.company_name ?? <span className="muted">—</span>, sortValue: (q) => q.company_name ?? null },
  { key: "sector", header: "Sector", cell: (q) => q.sector ?? <span className="muted">—</span>, sortValue: (q) => q.sector ?? null },
  { key: "price", header: "Price", cell: (q) => <Measure m={q.price} kind="kes" />, sortValue: (q) => valueOf(q.price), align: "right" },
  { key: "change", header: "Change", cell: (q) => <Measure m={q.change_pct} kind="pctpoints" signed />, sortValue: (q) => valueOf(q.change_pct), align: "right" },
  { key: "volume", header: "Volume", cell: (q) => <Measure m={q.volume} kind="int" />, sortValue: (q) => valueOf(q.volume), align: "right" },
  { key: "range", header: "52-week", cell: (q) => <span className="small">{valueOf(q.low_52w) != null && valueOf(q.high_52w) != null ? `${fmtNum(q.low_52w.value!, 2)} – ${fmtNum(q.high_52w.value!, 2)}` : <Measure m={q.low_52w} />}</span> },
  { key: "cap", header: "Market cap", cell: (q) => <Measure m={q.market_cap} kind="compactkes" />, sortValue: (q) => valueOf(q.market_cap), align: "right" },
  { key: "close", header: "Last close", cell: (q) => <span className="small">{valueOf(q.close) != null ? `${fmtNum(q.close.value!, 2)} · ${fmtDate(q.close_date)}` : <Measure m={q.close} />}</span> },
  { key: "src", header: "Source", cell: (q) => <span className="muted small">{q.source === "stockanalysis_stocks" ? "scrape" : q.source === "stock_observations" ? "archive" : "none"}</span> },
];

export function fmtCount(n: number): string {
  return fmtInt(n);
}
