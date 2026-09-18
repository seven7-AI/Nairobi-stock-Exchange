import { Link } from "react-router-dom";
import { api } from "../api/api";
import type { StockRow } from "../api/types";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Maybe } from "../components/ui/Maybe";
import { Measure } from "../components/ui/Measure";
import { Percentile } from "../components/ui/Percentile";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate } from "../lib/format";
import { valueOf } from "../lib/measure";

export function Stocks() {
  const { data, error, status, loading, refetch } = useApi("stocks", (signal) => api.stocks({ limit: 200 }, signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  return (
    <>
      <PageHeader title="Stocks" sub={`${data.total} classified equities · ranking as of ${fmtDate(data.as_of)} · search, sort (unknown values always last), click for the profile`} />
      <Card>
        <DataTable rows={data.items} rowKey={(r) => r.ticker_symbol} columns={COLUMNS} searchable searchText={(r) => `${r.ticker_symbol} ${r.company_name ?? ""} ${r.sector ?? ""} ${r.industry ?? ""}`} initialSort="ticker" dense />
      </Card>
    </>
  );
}

const COLUMNS: Column<StockRow>[] = [
  { key: "ticker", header: "Ticker", cell: (r) => <Link to={`/stocks/${r.ticker_symbol}`}>{r.ticker_symbol}</Link>, sortValue: (r) => r.ticker_symbol },
  { key: "name", header: "Company", cell: (r) => r.company_name ?? <span className="muted">—</span>, sortValue: (r) => r.company_name ?? null },
  { key: "sector", header: "Sector", cell: (r) => r.sector ?? <span className="muted">—</span>, sortValue: (r) => r.sector ?? null },
  { key: "price", header: "Price", cell: (r) => <Measure m={r.price} kind="kes" />, sortValue: (r) => valueOf(r.price), align: "right" },
  { key: "change", header: "Change", cell: (r) => <Measure m={r.change_pct} kind="pctpoints" signed />, sortValue: (r) => valueOf(r.change_pct), align: "right" },
  { key: "volume", header: "Volume", cell: (r) => <Measure m={r.volume} kind="int" />, sortValue: (r) => valueOf(r.volume), align: "right" },
  { key: "cap", header: "Mkt cap", cell: (r) => <Measure m={r.market_cap} kind="compactkes" />, sortValue: (r) => valueOf(r.market_cap), align: "right" },
  { key: "pe", header: "P/E", cell: (r) => <Measure m={r.pe} kind="ratio" />, sortValue: (r) => valueOf(r.pe), align: "right" },
  { key: "pb", header: "P/B", cell: (r) => <Measure m={r.pb} kind="ratio" />, sortValue: (r) => valueOf(r.pb), align: "right" },
  { key: "yield", header: "Yield", cell: (r) => <Measure m={r.dividend_yield} kind="pct" />, sortValue: (r) => valueOf(r.dividend_yield), align: "right" },
  { key: "quality", header: "Quality", cell: (r) => <Percentile value={r.factor_percentiles.quality} label="quality percentile (market)" />, sortValue: (r) => r.factor_percentiles.quality },
  { key: "growth", header: "Growth", cell: (r) => <Percentile value={r.factor_percentiles.growth} label="growth percentile (market)" />, sortValue: (r) => r.factor_percentiles.growth },
  { key: "value", header: "Value", cell: (r) => <Percentile value={r.factor_percentiles.value} label="value percentile (market)" />, sortValue: (r) => r.factor_percentiles.value },
  { key: "momentum", header: "Momentum", cell: (r) => <Percentile value={r.factor_percentiles.momentum} label="momentum percentile (market)" />, sortValue: (r) => r.factor_percentiles.momentum },
  { key: "score", header: "Score", cell: (r) => <Measure m={r.overall_score} kind="score" />, sortValue: (r) => valueOf(r.overall_score), align: "right", title: "composite score (factor-model v1)" },
  { key: "class", header: "Class", cell: (r) => (r.classification ? <StatusBadge status={r.classification} /> : <Measure m={r.overall_score} />), sortValue: (r) => r.classification ?? null },
  { key: "rank", header: "Rank", cell: (r) => <Maybe v={r.market_rank} kind="int" />, sortValue: (r) => r.market_rank, align: "right" },
];
