import { api } from "../api/api";
import type { StepRow } from "../api/types";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { KeyValueList } from "../components/ui/KeyValueList";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtAgo, fmtDateTime, fmtInt, fmtNum } from "../lib/format";
import { SourceCard } from "./Overview";

export function System() {
  const { data, error, status, loading, refetch } = useApi("status", (signal) => api.status(signal));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? "no data"} status={status} onRetry={refetch} />;
  const tables = Object.entries(data.store.tables).sort(([a], [b]) => a.localeCompare(b));
  return (
    <>
      <PageHeader title="System" sub="the store, the jobs, the scraper, the schedule" />
      <div className="grid">
        <Card title="Analytics store">
          <KeyValueList
            items={[
              { label: "Revision", value: <code>{data.store.revision ?? "none"}</code> },
              { label: "Head", value: <code>{data.store.head ?? "?"}</code> },
              { label: "Migrated", value: <StatusBadge status={data.store.migrated ? "current" : "behind"} tone={data.store.migrated ? "ok" : "warn"} /> },
              { label: "Open findings", value: fmtInt(data.open_findings) },
              { label: "Store version", value: <code>{data.version.version}</code> },
              { label: "Analytics written", value: `${fmtDateTime(data.version.analytics_updated_at)} (${fmtAgo(data.version.analytics_updated_at)})` },
              { label: "Scraper written", value: `${fmtDateTime(data.version.scraper_updated_at)} (${fmtAgo(data.version.scraper_updated_at)})` },
              ...Object.entries(data.watermarks).map(([k, v]) => ({ label: `watermark ${k}`, value: <code>{v}</code> })),
            ]}
          />
        </Card>
        <SourceCard source={data.source} />
        <Card title="Cron chain" subtitle={data.cron[0]?.timezone}>
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Expression</th>
                  <th>What</th>
                </tr>
              </thead>
              <tbody>
                {data.cron.map((c) => (
                  <tr key={c.pipeline}>
                    <td>{c.pipeline}</td>
                    <td className="mono">{c.expression}</td>
                    <td style={{ whiteSpace: "normal" }}>{c.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Pipelines" subtitle="last run and its steps" span={3}>
          {data.pipelines.map((p) => (
            <details key={p.pipeline} open={p.pipeline === "daily"} style={{ marginBottom: 8 }}>
              <summary>
                <b>{p.pipeline}</b> <span className="mono muted">{p.schedule}</span>{" "}
                {p.last_run ? (
                  <>
                    <StatusBadge status={p.last_run.status} title={p.last_run.error ?? undefined} /> {fmtDateTime(p.last_run.started_at)} · as of {p.last_run.as_of} · {fmtInt(p.last_run.rows_written)} rows
                    {p.last_run.seconds != null ? ` · ${fmtInt(p.last_run.seconds)} s` : ""}
                  </>
                ) : (
                  <StatusBadge status="never run" />
                )}
                {p.last_success && p.last_success.started_at !== p.last_run?.started_at ? <span className="muted"> · last success {fmtDateTime(p.last_success.started_at)}</span> : null}
              </summary>
              {p.last_run?.error ? <p className="neg small">{p.last_run.error}</p> : null}
              {p.steps.length ? <Steps steps={p.steps} /> : <p className="muted small">no step details</p>}
            </details>
          ))}
        </Card>
        <Card title="Tables" subtitle="rows and last update">
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Table</th>
                  <th className="num">Rows</th>
                  <th>Last update</th>
                </tr>
              </thead>
              <tbody>
                {tables.map(([name, rows]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td className="num">{fmtInt(rows)}</td>
                    <td>{data.store.last_update[name] ? fmtDateTime(data.store.last_update[name]) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Jobs" subtitle="last run per job">
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>As of</th>
                  <th className="num">Rows</th>
                  <th className="num">s</th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.map((j) => (
                  <tr key={j.job_name}>
                    <td>{j.job_name}</td>
                    <td>
                      <StatusBadge status={j.status} title={j.error ?? undefined} />
                    </td>
                    <td>{fmtDateTime(j.started_at)}</td>
                    <td>{j.as_of ?? "—"}</td>
                    <td className="num">{fmtInt(j.rows_written)}</td>
                    <td className="num">{j.seconds != null ? fmtNum(j.seconds, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Models" subtitle="registry">
          <div className="table-wrap">
            <table className="small">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Version</th>
                  <th>Kind</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.models.map((m) => (
                  <tr key={`${m.name}-${m.version}`}>
                    <td>{m.name}</td>
                    <td>{m.version}</td>
                    <td>{m.kind}</td>
                    <td>
                      <StatusBadge status={m.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}

function Steps({ steps }: { steps: StepRow[] }) {
  return (
    <div className="table-wrap">
      <table className="small">
        <thead>
          <tr>
            <th>Step</th>
            <th>Status</th>
            <th className="num">Rows</th>
            <th className="num">Seconds</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr key={s.name}>
              <td>{s.name}</td>
              <td>
                <StatusBadge status={s.status} />
              </td>
              <td className="num">{fmtInt(s.rows)}</td>
              <td className="num">{fmtNum(s.seconds, 1)}</td>
              <td style={{ whiteSpace: "normal" }}>{s.reason ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
