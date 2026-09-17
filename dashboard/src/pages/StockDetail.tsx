import { useState, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, type PriceRange } from "../api/api";
import { GapAwareLineChart } from "../components/charts/GapAwareLineChart";
import { PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Disclaimer } from "../components/ui/Disclaimer";
import { KeyValueList } from "../components/ui/KeyValueList";
import { Maybe } from "../components/ui/Maybe";
import { Measure } from "../components/ui/Measure";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ErrorState, Loading } from "../components/ui/States";
import { useApi } from "../hooks/useApi";
import { fmtDate, fmtNum } from "../lib/format";
import { CompanyFacts } from "./stock/CompanyFacts";
import { FactorScores } from "./stock/FactorScores";
import { ForecastCard } from "./stock/ForecastCard";
import { MetricBlocks } from "./stock/MetricBlocks";
import { ScenarioCard } from "./stock/ScenarioCard";
import { SectorComparison } from "./stock/SectorComparison";
import { StatementsTable } from "./stock/StatementsTable";
import { ValuationCard } from "./stock/ValuationCard";

const RANGES: PriceRange[] = ["1y", "3y", "5y", "max"];
const TRAP: Record<number, string> = { 0: "low", 1: "medium", 2: "high" };

export function StockDetail() {
  const { ticker = "" } = useParams();
  // keyed by ticker so per-stock state (tabs) resets on navigation
  return <StockDetailInner key={ticker.toUpperCase()} symbol={ticker.toUpperCase()} />;
}

function StockDetailInner({ symbol }: { symbol: string }) {
  const [params, setParams] = useSearchParams();
  const range = (RANGES.includes(params.get("range") as PriceRange) ? params.get("range") : "5y") as PriceRange;
  const interval = range === "max" || range === "5y" ? "weekly" : "daily";
  const detail = useApi(symbol ? `stock:${symbol}` : null, (signal) => api.stock(symbol, undefined, signal));
  const prices = useApi(symbol ? `prices:${symbol}:${range}` : null, (signal) => api.prices(symbol, range, interval, signal));
  const [tab, setTab] = useState<"metrics" | "fundamentals">("metrics");

  if (detail.loading) return <Loading rows={8} />;
  if (detail.error || !detail.data) return <ErrorState error={detail.error ?? "no data"} status={detail.status} onRetry={detail.refetch} />;
  const d = detail.data;
  const p = d.profile;
  const score = p.score;
  const overall = score.overall;
  const ranks = score.ranks;
  const explanation = score.explanation ?? {};
  const series = prices.data;
  return (
    <>
      <PageHeader
        title={`${symbol} · ${d.facts.company_name ?? d.quote.company_name ?? ""}`}
        sub={
          <span>
            {d.facts.sector ?? "unclassified"}
            {d.facts.industry ? ` · ${d.facts.industry}` : ""} · price <Measure m={d.quote.price} kind="kes" /> <Measure m={d.quote.change_pct} kind="pctpoints" signed /> <span className="muted">scraped {fmtDate(d.quote.scraped_at?.slice(0, 10))}</span>
          </span>
        }
      >
        {score.classification ? <StatusBadge status={score.classification} /> : <StatusBadge status={score.status ?? "unscored"} title={score.reason} />}
      </PageHeader>

      <div className="tiles">
        <Tile label="Composite score" value={<Measure m={overall} kind="score" />} hint={overall?.reason ?? (typeof score.confidence === "number" ? `confidence ${fmtNum(score.confidence, 2)}` : undefined)} />
        <Tile label="Ranks (market · sector · industry)" value={ranks ? `${ranks.market ?? "—"} · ${ranks.sector ?? "—"} · ${ranks.industry ?? "—"}` : "—"} />
        <Tile label="Value-trap risk" value={typeof score.value_trap_risk === "number" ? TRAP[score.value_trap_risk] ?? String(score.value_trap_risk) : "—"} hint={(explanation.value_trap as { signals?: string[] } | undefined)?.signals?.join("; ")} />
        <Tile label="Compounder" value={<Maybe v={score.compounder_score} kind="score" />} hint={(explanation.compounder as { criteria_met?: string[] } | undefined)?.criteria_met?.join(", ")} />
        <Tile label="52-week range" value={<span>{d.quote.low_52w.value != null && d.quote.high_52w.value != null ? `${fmtNum(d.quote.low_52w.value, 2)} – ${fmtNum(d.quote.high_52w.value, 2)}` : <Measure m={d.quote.low_52w} />}</span>} />
        <Tile label="Market cap" value={<Measure m={d.quote.market_cap} kind="compactkes" />} hint={d.quote.volume.value != null ? `volume ${fmtNum(d.quote.volume.value, 0)}` : undefined} />
      </div>

      {explanation.positive_factors?.length || explanation.negative_factors?.length ? (
        <Card title="Why" subtitle="from the ranking's explanation">
          <div className="chips">
            {(explanation.positive_factors ?? []).map((f) => (
              <span key={f} className="chip pos">
                + {f}
              </span>
            ))}
            {(explanation.negative_factors ?? []).map((f) => (
              <span key={f} className="chip neg">
                − {f}
              </span>
            ))}
          </div>
        </Card>
      ) : null}

      <div className="grid" style={{ marginTop: 16 }}>
        <Card
          title="Price"
          subtitle={series ? `${series.n_observations} observations · ${series.interval} · ${series.availability.status}${series.availability.reason ? ` — ${series.availability.reason}` : ""}` : "loading"}
          span={3}
          actions={
            <div className="controls">
              {RANGES.map((r) => (
                <button key={r} type="button" aria-pressed={r === range} onClick={() => setParams({ range: r })}>
                  {r}
                </button>
              ))}
            </div>
          }
        >
          {prices.loading && !series ? <Loading rows={3} /> : prices.error ? <ErrorState error={prices.error} onRetry={prices.refetch} /> : series ? <GapAwareLineChart points={series.points} gaps={series.gaps} missingStart={series.missing_start} height={280} /> : null}
          {series?.gaps.length ? (
            <p className="muted small" style={{ marginTop: 6 }}>
              {series.gaps.map((g) => `no observations ${fmtDate(g.after)} → ${fmtDate(g.before)} (${g.days} d)`).join(" · ")}
            </p>
          ) : null}
        </Card>

        <div className="span-3 controls">
          <button type="button" aria-pressed={tab === "metrics"} onClick={() => setTab("metrics")}>
            Market metrics
          </button>
          <button type="button" aria-pressed={tab === "fundamentals"} onClick={() => setTab("fundamentals")}>
            Fundamentals
          </button>
        </div>
        <MetricBlocks metrics={tab === "metrics" ? pick(p.metrics, ["returns", "momentum", "risk", "liquidity"]) : pick(p.metrics, ["quality", "growth", "value", "dividend"])} asOf={p.as_of} />

        <FactorScores factors={p.factors} asOf={p.as_of.ranking ?? null} />
        <ValuationCard valuation={p.valuation} asOf={p.as_of.valuation ?? null} />
        <ForecastCard forecast={p.forecast} availability={d.forecast_availability} price={d.quote.price.value} asOf={p.as_of.forecast ?? null} />
        <ScenarioCard scenarios={p.scenarios} asOf={p.as_of.simulation ?? null} />
        <Card title="Market regime" subtitle={typeof p.regime.index === "string" ? `${p.regime.index}` : undefined}>
          <KeyValueList
            items={[
              { label: "Status", value: <StatusBadge status={p.regime.status} title={p.regime.reason ?? undefined} /> },
              { label: "Label", value: p.regime.label ?? <span className="muted small">{p.regime.reason}</span> },
              { label: "Trend / volatility / risk", value: [p.regime.trend, p.regime.volatility, p.regime.risk].filter(Boolean).join(" / ") || "—" },
            ]}
          />
        </Card>
        <SectorComparison rows={d.sector_comparison} sector={d.facts.sector ?? null} />
        <CompanyFacts facts={d.facts} geographic={d.geographic} quote={d.quote} />
        <StatementsTable statements={d.statements} />
        <Card title="Models" span={3}>
          <div className="chips">
            {p.models.map((m) => (
              <span key={`${m.name}${m.version}`} className="chip">
                {m.name} v{m.version} · {m.kind} · <StatusBadge status={m.status} />
              </span>
            ))}
          </div>
          {p.notes.length ? (
            <ul className="muted small">
              {p.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          <Disclaimer text={p.disclaimer} />
        </Card>
      </div>
    </>
  );
}

function pick<T>(obj: Record<string, T>, keys: string[]): Record<string, T> {
  return Object.fromEntries(keys.filter((k) => k in obj).map((k) => [k, obj[k]]));
}

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? (
        <div className="hint" title={hint}>
          {hint.length > 90 ? `${hint.slice(0, 90)}…` : hint}
        </div>
      ) : null}
    </div>
  );
}
