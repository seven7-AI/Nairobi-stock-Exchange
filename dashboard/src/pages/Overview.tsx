import { api } from "../api/api";
import type { Pipeline, SourceHealth, TableCoverage } from "../api/types";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { KeyValueList } from "../components/ui/KeyValueList";
import { StatTile } from "../components/ui/StatTile";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtAgo, fmtDate, fmtDateTime, fmtInt, titleCase } from "../lib/format";

export function Overview() {
  const { data, error, status, loading, refetch } = useApi("overview", (signal) => api.overview(signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  const forecasts = data.forecasts;
  const findings = data.open_findings;
  return (
    <>
      <PageHeader title="Overview" sub={`What the engine knows as of ${fmtDate(data.latest_market_date)}`} />
      <div className="tiles">
        <StatTile label="Tracked stocks" value={fmtInt(data.tracked_stocks)} hint={`${data.scraped_stocks} enriched by the scraper`} />
        <StatTile label="Latest market date" value={fmtDate(data.latest_market_date)} hint={`${data.stocks_with_data_on_latest} instruments have a price`} />
        <StatTile label="Ranked stocks" value={<CoverageValue c={data.analytics.stock_rankings} />} hint={<CoverageHint c={data.analytics.stock_rankings} />} />
        <StatTile label="Forecasts" value={<CoverageValue c={forecasts} />} hint={<CoverageHint c={forecasts} />} />
        <StatTile
          label="Open findings"
          value={
            <span className="chips">
              <StatusBadge status={`${findings.error} error`} tone={findings.error ? "error" : "muted"} />
              <StatusBadge status={`${findings.warning} warning`} tone={findings.warning ? "warn" : "muted"} />
              <StatusBadge status={`${findings.info} info`} tone="muted" />
            </span>
          }
          hint="data-quality findings still open"
        />
        <StatTile label="Store" value={<StatusBadge status={data.store_migrated ? "migrated" : "behind"} tone={data.store_migrated ? "ok" : "warn"} />} hint={data.store_revision ?? "no store"} />
      </div>
      <div className="grid">
        <SourceCard source={data.source} />
        <Card title="Pipelines" subtitle="last run per pipeline (cron, Africa/Nairobi)" span={2}>
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>Schedule</th>
                  <th>Last run</th>
                  <th>Status</th>
                  <th>As of</th>
                  <th className="num">Rows</th>
                  <th className="num">Seconds</th>
                  <th>Last success</th>
                </tr>
              </thead>
              <tbody>
                {data.pipelines.map((p) => (
                  <PipelineRow key={p.pipeline} p={p} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Analytics calculated" subtitle="status counts on each table's latest date">
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Latest</th>
                  <th className="num">Known</th>
                  <th className="num">Other</th>
                  <th>Last known date</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.analytics).map(([name, c]) => (
                  <tr key={name}>
                    <td>{titleCase(name)}</td>
                    <td>{fmtDate(c.as_of)}</td>
                    <td className="num">{fmtInt((c.counts.known ?? 0) + (c.counts.zero ?? 0))}</td>
                    <td className="num" title={Object.entries(c.counts).filter(([k]) => k !== "known" && k !== "zero").map(([k, v]) => `${k}: ${v}`).join(", ")}>
                      {fmtInt(Object.entries(c.counts).filter(([k]) => k !== "known" && k !== "zero").reduce((s, [, v]) => s + v, 0))}
                    </td>
                    <td>{fmtDate(c.latest_known_as_of)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Live">
          <KeyValueList
            items={[
              { label: "Last data update", value: `${fmtDateTime(data.version.scraper_updated_at)} (${fmtAgo(data.version.scraper_updated_at)})` },
              { label: "Last analytics run", value: `${fmtDateTime(data.version.analytics_updated_at)} (${fmtAgo(data.version.analytics_updated_at)})` },
              { label: "Latest analytics date", value: fmtDate(data.version.latest_analytics_date) },
              { label: "Latest forecast date", value: fmtDate(forecasts.as_of) },
              { label: "Store version", value: <code>{data.version.version}</code> },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

function CoverageValue({ c }: { c: TableCoverage }) {
  if (!c.as_of) return <span className="measure--na">none</span>;
  const known = (c.counts.known ?? 0) + (c.counts.zero ?? 0);
  const total = Object.values(c.counts).reduce((s, v) => s + v, 0);
  return (
    <>
      {fmtInt(known)} <span className="muted small">/ {fmtInt(total)}</span>
    </>
  );
}

function CoverageHint({ c }: { c: TableCoverage }) {
  if (!c.as_of) return "not computed yet";
  const known = (c.counts.known ?? 0) + (c.counts.zero ?? 0);
  if (known === 0 && c.latest_known_as_of) return `all unavailable on ${fmtDate(c.as_of)}; last known ${fmtDate(c.latest_known_as_of)}`;
  return `known on ${fmtDate(c.as_of)}`;
}

function PipelineRow({ p }: { p: Pipeline }) {
  const run = p.last_run;
  return (
    <tr>
      <td>{p.pipeline}</td>
      <td className="mono" title={p.description}>
        {p.schedule}
      </td>
      <td>{run ? fmtDateTime(run.started_at) : "never"}</td>
      <td>{run ? <StatusBadge status={run.status} title={run.error ?? undefined} /> : <StatusBadge status="never run" />}</td>
      <td>{run?.as_of ?? "—"}</td>
      <td className="num">{run ? fmtInt(run.rows_written) : "—"}</td>
      <td className="num">{run?.seconds != null ? fmtInt(run.seconds) : "—"}</td>
      <td>{p.last_success ? `${fmtDate(p.last_success.as_of)} (${fmtAgo(p.last_success.finished_at)})` : "never"}</td>
    </tr>
  );
}

export function SourceCard({ source }: { source: SourceHealth }) {
  return (
    <Card title="Data source" subtitle={source.name}>
      <KeyValueList
        items={[
          { label: "Status", value: <StatusBadge status={source.status} title={source.detail || undefined} /> },
          { label: "Newest scrape", value: `${fmtDateTime(source.newest_scraped_at)} (${fmtAgo(source.newest_scraped_at)})` },
          { label: "Age", value: source.age_hours != null ? `${fmtInt(source.age_hours)} h` : "—" },
          { label: "Quality gate", value: source.quality_ok == null ? "unknown" : source.quality_ok ? "OK" : "failed" },
          ...source.tables.map((t) => ({ label: t.name, value: `${fmtInt(t.row_count)} rows` })),
        ]}
      />
    </Card>
  );
}
