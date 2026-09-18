import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/api";
import type { AnalyticsRow } from "../api/types";
import { PageHeader } from "../components/layout/PageHeader";
import { AsOfSelector } from "../components/ui/AsOfSelector";
import { Card } from "../components/ui/Card";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Maybe } from "../components/ui/Maybe";
import { Measure } from "../components/ui/Measure";
import { Percentile } from "../components/ui/Percentile";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtNum, titleCase } from "../lib/format";
import { valueOf } from "../lib/measure";

const TRAP: Record<number, string> = { 0: "low", 1: "medium", 2: "high" };

export function Analytics() {
  const [params] = useSearchParams();
  const asOf = params.get("as_of") ?? undefined;
  const { data, error, status, loading, refetch } = useApi(`analytics:${asOf ?? "latest"}`, (signal) => api.analytics(asOf, undefined, signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  const scored = data.rows.filter((r) => r.market_rank !== null).length;
  const factorCols: Column<AnalyticsRow>[] = data.factor_names.map((f) => ({
    key: `f:${f}`,
    header: titleCase(f),
    cell: (r) => {
      const cell = r.factors[f];
      return cell?.score.status === "known" ? (
        <span title={`score ${fmtNum(cell.score.value ?? 0, 1)} · sector P${cell.percentile_sector ?? "?"}`}>
          <Percentile value={cell.percentile_market} label={`${f} (market)`} />
        </span>
      ) : (
        <Measure m={cell?.score} />
      );
    },
    sortValue: (r) => r.factors[f]?.percentile_market ?? null,
  }));
  const relativeCols: Column<AnalyticsRow>[] = ["relative_1m_vs_market", "relative_1m_vs_sector", "relative_12m_vs_market", "relative_12m_vs_sector"].map((m) => ({
    key: m,
    header: m.replace("relative_", "").replace("_vs_", " vs "),
    cell: (r) => <Measure m={r.relative[m]} kind="pct" signed />,
    sortValue: (r) => valueOf(r.relative[m]),
    align: "right",
  }));
  return (
    <>
      <PageHeader title="Analytics" sub={`${data.model} · ${scored} of ${data.rows.length} instruments scored on ${fmtDate(data.as_of)}${data.latest_known_as_of && data.latest_known_as_of !== data.as_of ? ` · last known scores ${fmtDate(data.latest_known_as_of)}` : ""}`}>
        <AsOfSelector dates={data.available_dates} current={data.as_of} />
      </PageHeader>
      <Card title="Coverage" subtitle="factor scores by status on this date">
        <div className="chips">
          {Object.entries(data.coverage).map(([f, c]) => (
            <span key={f} className="chip" title={Object.entries(c).map(([k, v]) => `${k}: ${v}`).join(", ")}>
              {titleCase(f)} {(c.known ?? 0) + (c.zero ?? 0)}/{Object.values(c).reduce((s, v) => s + v, 0)}
            </span>
          ))}
        </div>
      </Card>
      <div style={{ height: 16 }} />
      <Card title="Composite ranking and factors" subtitle="rank order; unscored rows last with their reason; percentiles within the market">
        <DataTable
          rows={data.rows}
          rowKey={(r) => r.ticker_symbol}
          searchable
          searchText={(r) => `${r.ticker_symbol} ${r.sector ?? ""} ${r.classification ?? ""}`}
          initialSort="rank"
          dense
          columns={[
            { key: "rank", header: "#", cell: (r) => <Maybe v={r.market_rank} kind="int" />, sortValue: (r) => r.market_rank, align: "right" },
            { key: "ticker", header: "Ticker", cell: (r) => <Link to={`/stocks/${r.ticker_symbol}`}>{r.ticker_symbol}</Link>, sortValue: (r) => r.ticker_symbol },
            { key: "sector", header: "Sector", cell: (r) => r.sector ?? <span className="muted">—</span>, sortValue: (r) => r.sector ?? null },
            { key: "score", header: "Score", cell: (r) => <Measure m={r.overall} kind="score" showReason={r.overall.status !== "known"} />, sortValue: (r) => valueOf(r.overall), align: "right" },
            { key: "class", header: "Class", cell: (r) => (r.classification ? <StatusBadge status={r.classification} /> : <span className="muted">—</span>), sortValue: (r) => r.classification ?? null },
            { key: "conf", header: "Conf.", cell: (r) => <Maybe v={r.confidence} kind="num" digits={2} />, sortValue: (r) => r.confidence, align: "right" },
            { key: "trap", header: "Trap", cell: (r) => (r.value_trap_risk == null ? <span className="muted">—</span> : TRAP[r.value_trap_risk]), sortValue: (r) => r.value_trap_risk },
            { key: "comp", header: "Compounder", cell: (r) => <Maybe v={r.compounder_score} kind="score" />, sortValue: (r) => r.compounder_score, align: "right" },
            ...factorCols,
            ...relativeCols,
          ]}
        />
      </Card>
    </>
  );
}
