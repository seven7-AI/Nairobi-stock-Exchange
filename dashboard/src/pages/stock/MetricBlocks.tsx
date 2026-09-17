import type { Measure as MeasureT } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Measure, type MeasureKind } from "../../components/ui/Measure";
import { titleCase } from "../../lib/format";

const BLOCK_ORDER = ["returns", "momentum", "risk", "liquidity", "quality", "growth", "value", "dividend"];

/** How each stored metric is displayed; anything not listed is a plain number. */
const KIND: Record<string, MeasureKind> = {
  return_1d: "pct", return_1w: "pct", return_1m: "pct", return_3m: "pct", return_6m: "pct", return_12m: "pct", return_ytd: "pct", return_yoy: "pct", return_24m: "pct", return_36m: "pct",
  momentum_1m: "pct", momentum_3m: "pct", momentum_6m: "pct", momentum_12m: "pct", momentum_12m_1m: "pct", relative_12m_vs_market: "pct", relative_12m_vs_sector: "pct",
  price_to_ma_50: "ratio", price_to_ma_200: "ratio", trend_strength_6m: "num", distance_from_52w_high: "pct", distance_from_52w_low: "pct", momentum_persistence_12m: "pct",
  volatility_daily: "pct", volatility_annualised: "pct", max_drawdown_36m: "pct", drawdown_current: "pct", beta_12m: "num", beta_36m: "num", correlation_market_12m: "num", sharpe_12m: "num", sortino_12m: "num",
  avg_daily_volume: "int", avg_daily_turnover: "compactkes", trading_frequency: "pct", zero_volume_share: "pct", market_cap: "compactkes", liquidity_score: "score", liquidity_bucket: "int",
  roe: "pct", roa: "pct", net_margin: "pct", gross_margin: "pct", operating_margin: "pct", fcf: "compactkes", fcf_margin: "pct", debt_to_equity: "ratio", interest_coverage: "ratio", asset_turnover: "ratio", roe_trend: "num", net_margin_trend: "num", debt_to_equity_trend: "num",
  revenue_growth_1y: "pct", eps_growth_1y: "pct", net_income_growth_1y: "pct", fcf_growth_1y: "pct", revenue_cagr_3y: "pct", eps_cagr_3y: "pct", revenue_cagr_5y: "pct", eps_cagr_5y: "pct", revenue_growth_1y_vs_sector: "pct",
  price: "kes", pe: "ratio", pe_ttm: "ratio", pb: "ratio", ps: "ratio", ev_ebitda: "ratio", fcf_yield: "pct", pe_vs_history: "pct", pe_vs_sector: "pct", pe_vs_market: "pct", pb_vs_sector: "pct", pb_vs_market: "pct",
  dividend_yield: "pct", dividend_yield_ttm: "pct", payout_ratio: "pct", dividend_years_paid: "int", dividend_consistency: "pct", dividend_cut: "int", fcf_dividend_coverage: "ratio", dividend_class: "int", dividend_cagr_3y: "pct",
};
const SIGNED = new Set(["return_1d", "return_1w", "return_1m", "return_3m", "return_6m", "return_12m", "return_ytd", "return_yoy", "return_24m", "return_36m", "momentum_1m", "momentum_3m", "momentum_6m", "momentum_12m", "momentum_12m_1m", "relative_12m_vs_market", "relative_12m_vs_sector", "revenue_growth_1y", "eps_growth_1y", "net_income_growth_1y", "fcf_growth_1y", "pe_vs_history", "pe_vs_sector", "pe_vs_market", "pb_vs_sector", "pb_vs_market", "revenue_growth_1y_vs_sector", "max_drawdown_36m", "drawdown_current"]);

export function MetricBlocks({ metrics, asOf }: { metrics: Record<string, Record<string, MeasureT>>; asOf: Record<string, string | null> }) {
  const blocks = [...BLOCK_ORDER.filter((b) => b in metrics), ...Object.keys(metrics).filter((b) => !BLOCK_ORDER.includes(b))];
  return (
    <>
      {blocks.map((block) => {
        const source = ["quality", "growth", "value", "dividend"].includes(block) ? "fundamental_metrics" : "market_metrics";
        const rows = Object.entries(metrics[block]);
        const unknown = rows.filter(([, m]) => m.status !== "known" && m.status !== "zero").length;
        return (
          <Card key={block} title={titleCase(block)} subtitle={unknown ? `${rows.length - unknown} of ${rows.length} known` : `${rows.length} known`} asOf={asOf[source]}>
            <dl className="kv">
              {rows.map(([name, m]) => (
                <div key={name} style={{ display: "contents" }}>
                  <dt>{titleCase(name)}</dt>
                  <dd>
                    <Measure m={m} kind={KIND[name] ?? "num"} signed={SIGNED.has(name)} showReason />
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
        );
      })}
    </>
  );
}
