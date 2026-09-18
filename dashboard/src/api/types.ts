// Every response shape of /api/v1/dashboard, in one place. Numbers that can be
// absent arrive as a Measure - never as a bare 0.

export type MeasureStatus =
  | "known"
  | "zero"
  | "missing"
  | "unavailable"
  | "not_applicable"
  | "not_meaningful"
  | "partial";

export interface Measure {
  value: number | null;
  status: MeasureStatus | string;
  reason: string | null;
}

export interface Availability extends Measure {
  latest_known_as_of?: IsoDate | null;
}

export type IsoDate = string; // "2026-09-16"
export type IsoDateTime = string; // "2026-09-16T07:40:59+00:00"

export interface VersionOut {
  version: string;
  analytics_updated_at: IsoDateTime | null;
  scraper_updated_at: IsoDateTime | null;
  latest_market_date: IsoDate | null;
  latest_analytics_date: IsoDate | null;
  generated_at: IsoDateTime;
}

export interface JobRow {
  job_name: string;
  status: string;
  started_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  as_of: string | null;
  rows_written: number;
  seconds: number | null;
  error: string | null;
  details: Record<string, unknown>;
}

export interface StepRow {
  name: string;
  status: string;
  rows: number;
  seconds: number;
  reason: string | null;
}

export interface Pipeline {
  pipeline: string;
  schedule: string;
  timezone: string;
  description: string;
  last_run: JobRow | null;
  last_success: JobRow | null;
  steps: StepRow[];
}

export interface CronEntry {
  pipeline: string;
  expression: string;
  timezone: string;
  description: string;
}

export interface SourceHealth {
  name: string;
  status: "ok" | "stale" | "degraded" | "unreachable" | string;
  reachable: boolean;
  detail: string;
  newest_scraped_at: IsoDateTime | null;
  age_hours: number | null;
  is_stale: boolean;
  quality_ok: boolean | null;
  tables: { name: string; row_count: number; newest_scraped_at: IsoDateTime | null }[];
}

export interface StatusOut {
  version: VersionOut;
  store: {
    revision: string | null;
    head: string | null;
    migrated: boolean;
    tables: Record<string, number>;
    last_update: Record<string, string | null>;
  };
  pipelines: Pipeline[];
  jobs: JobRow[];
  models: { name: string; version: string; kind: string; status: string; performance?: unknown }[];
  open_findings: number;
  source: SourceHealth;
  watermarks: Record<string, string>;
  cron: CronEntry[];
}

export interface TableCoverage {
  as_of: IsoDate | null;
  counts: Record<string, number>;
  latest_known_as_of: IsoDate | null;
}

export interface OverviewOut {
  version: VersionOut;
  tracked_stocks: number;
  scraped_stocks: number;
  classified_universe: number;
  latest_market_date: IsoDate | null;
  stocks_with_data_on_latest: number;
  source: SourceHealth;
  pipelines: Pipeline[];
  analytics: Record<string, TableCoverage>;
  forecasts: TableCoverage;
  open_findings: { error: number; warning: number; info: number } & Record<string, number>;
  store_revision: string | null;
  store_migrated: boolean;
  last_update: Record<string, string | null>;
}

export interface Quote {
  ticker_symbol: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  price: Measure;
  change_pct: Measure;
  volume: Measure;
  low_52w: Measure;
  high_52w: Measure;
  market_cap: Measure;
  close: Measure;
  close_date: IsoDate | null;
  scraped_at: IsoDateTime | null;
  facts: { industry?: string | null; founded?: number | null; employees?: number | null; revenue?: number | null };
  source: string;
}

export interface SectorPerf {
  sector: string;
  members: number;
  known_members: number;
  median: Measure;
}

export interface IndexAvailability {
  status: string;
  reason: string | null;
  latest_known_as_of: IsoDate | null;
  last: number | null;
}

export interface MarketOut {
  as_of: IsoDate;
  latest_market_date: IsoDate | null;
  stocks_with_data: number;
  universe: number;
  quotes: Quote[];
  performance: Record<"1d" | "1w" | "1m", SectorPerf[]>;
  top_movers: Quote[];
  bottom_movers: Quote[];
  index: Record<string, IndexAvailability>;
  coverage: Record<string, Record<string, number>>;
}

export interface StockRow {
  ticker_symbol: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  price: Measure;
  change_pct: Measure;
  volume: Measure;
  market_cap: Measure;
  pe: Measure;
  pb: Measure;
  dividend_yield: Measure;
  factor_percentiles: Record<string, number | null>;
  overall_score: Measure;
  classification: string | null;
  market_rank: number | null;
  confidence: number | null;
  value_trap_risk: number | null;
  compounder_score: number | null;
  as_of: IsoDate | null;
}

export interface StockListPage {
  items: StockRow[];
  next_cursor: string | null;
  total: number;
  as_of: IsoDate | null;
  sort: string;
  order: string;
}

export interface PricePoint {
  date: IsoDate;
  close: number;
  volume: number | null;
  change_pct: number | null;
  source: string;
  flagged: boolean;
}

export interface Gap {
  after: IsoDate;
  before: IsoDate;
  days: number;
}

export interface PriceHistory {
  ticker_symbol: string;
  range: string;
  interval: string;
  start: IsoDate | null;
  end: IsoDate | null;
  points: PricePoint[];
  gaps: Gap[];
  gap_threshold_days: number;
  n_observations: number;
  availability: Availability;
  source_tickers: string[];
  missing_start: { from: IsoDate; to: IsoDate; days: number } | null;
}

export interface FiscalYear {
  period_end: IsoDate;
  label: string;
  currency: string | null;
  values: Record<string, Measure>;
}

export interface Statements {
  ticker_symbol: string;
  as_of: IsoDate;
  period_type: string;
  concepts: string[];
  years: FiscalYear[];
  availability: Availability;
}

export interface SectorComparisonRow {
  metric: string;
  stock: Measure;
  sector_median: Measure;
  sector_members: number;
  known_peers: number;
  percentile_in_sector: number | null;
}

export interface FactorScore {
  score: Measure;
  coverage: number | null;
  percentile_market: number | null;
  percentile_sector: number | null;
  percentile_industry: number | null;
  inputs?: unknown;
}

export interface Profile {
  ticker_symbol: string;
  as_of: Record<string, IsoDate | null>;
  identity: Record<string, unknown>;
  score: Record<string, unknown> & {
    overall?: Measure;
    confidence?: number;
    classification?: string | null;
    ranks?: { market: number | null; sector: number | null; industry: number | null };
    value_trap_risk?: number | null;
    compounder_score?: number | null;
    explanation?: Record<string, unknown> & { positive_factors?: string[]; negative_factors?: string[] };
    status?: string;
    reason?: string;
  };
  factors: Record<string, FactorScore>;
  metrics: Record<string, Record<string, Measure>>;
  valuation: Record<string, unknown> & {
    intrinsic?: Measure;
    fair_low?: number | null;
    fair_high?: number | null;
    price?: number | null;
    upside?: number | null;
    margin_of_safety?: number | null;
    uncertainty?: number | null;
    actionable?: boolean | null;
    methods?: Record<string, { status: string; reason: string | null; bear: number | null; base: number | null; bull: number | null; assumptions: Record<string, unknown> }>;
    status?: string;
    reason?: string;
  };
  forecast: Record<string, unknown> & { models?: Record<string, Record<string, ForecastCell>>; status?: string; reason?: string };
  scenarios: Record<string, unknown> & { outcomes?: Record<string, { implied_return: Measure; implied_price: number | null; assumptions: Record<string, unknown> }>; status?: string; reason?: string };
  simulation: Record<string, unknown>;
  regime: Record<string, unknown> & { status: string; reason?: string | null; label?: string | null; trend?: string | null; volatility?: string | null; risk?: string | null; index?: string };
  models: { name: string; version: string; kind: string; status: string }[];
  disclaimer: string;
  notes: string[];
}

export interface StockDetail {
  ticker_symbol: string;
  quote: Quote;
  profile: Profile;
  prices: PriceHistory;
  sector_comparison: SectorComparisonRow[];
  statements: Statements;
  facts: Record<string, unknown> & {
    company_name?: string | null;
    sector?: string | null;
    industry?: string | null;
    founded?: number | null;
    employees?: number | null;
    revenue?: number | null;
    listed_since?: IsoDate | null;
    country?: string | null;
    ceo?: string | null;
    website?: string | null;
    address?: string | null;
    exchange?: string | null;
    fiscal_year?: string | null;
    currency?: string | null;
    sic?: string | null;
    executives?: { name: string; title: string | null }[] | null;
  };
  geographic: {
    status: string;
    reason: string | null;
    home_country?: string | null;
    operating_countries?: string[];
    description?: string | null;
    note?: string | null;
    segments: unknown[];
    coverage?: Measure | null;
  };
  forecast_availability: Availability;
  links: Record<string, string>;
}

export interface FactorCell {
  score: Measure;
  coverage: number;
  percentile_market: number | null;
  percentile_sector: number | null;
  percentile_industry: number | null;
}

export interface AnalyticsRow {
  ticker_symbol: string;
  sector: string | null;
  industry: string | null;
  overall: Measure;
  classification: string | null;
  confidence: number;
  market_rank: number | null;
  sector_rank: number | null;
  industry_rank: number | null;
  value_trap_risk: number | null;
  compounder_score: number | null;
  positive_factors: string[];
  negative_factors: string[];
  factors: Record<string, FactorCell>;
  relative: Record<string, Measure>;
}

export interface AnalyticsOut {
  as_of: IsoDate;
  model: string;
  available_dates: IsoDate[];
  factor_names: string[];
  rows: AnalyticsRow[];
  coverage: Record<string, Record<string, number>>;
  latest_known_as_of: IsoDate | null;
}

export interface ForecastCell {
  expected_return: Measure;
  q05: number | null;
  q25: number | null;
  q50: number | null;
  q75: number | null;
  q95: number | null;
  p_positive: number | null;
  p_outperform: number | null;
  expected_vol: number | null;
  p_drawdown: number | null;
  drawdown_threshold?: number | null;
  benchmark?: string | null;
}

export interface TickerForecasts {
  ticker_symbol: string;
  sector: string | null;
  as_of: IsoDate;
  price: number | null;
  models: Record<string, Record<string, ForecastCell>>;
  scenarios: { as_of: IsoDate; price: number | null; outcomes: Record<string, { implied_return: Measure; implied_price: number | null; assumptions: Record<string, unknown> }> } | null;
  simulation: { as_of: IsoDate; price: number | null; paths: Record<string, Record<string, Record<string, unknown>>> } | null;
}

export interface HorizonAccuracy {
  n: number;
  mae: Measure;
  rmse: Measure;
  directional_accuracy: Measure;
  benchmark_hit_rate: Measure;
  interval_coverage: Measure;
}

export interface ForecastsOut {
  as_of: IsoDate;
  availability: Availability;
  latest_known_as_of: IsoDate | null;
  available_dates: IsoDate[];
  tickers: string[];
  items: TickerForecasts[];
  accuracy: Record<string, Record<string, HorizonAccuracy>>;
  regime: Record<string, unknown> & { status: string; reason?: string | null; label?: string | null; trend?: string | null; volatility?: string | null; risk?: string | null; index?: string; as_of?: IsoDate };
  models: { name: string; version: string; kind: string; status: string }[];
  disclaimer: string;
}

export interface SignalItem {
  ticker_symbol: string;
  sector: string | null;
  classification: string | null;
  overall_score: Measure;
  confidence: number;
  market_rank: number | null;
  positive_factors: string[];
  negative_factors: string[];
  link: string;
  extra: Record<string, unknown> & { risk?: number; risk_label?: string; signals?: string[]; compounder_score?: number; criteria_met?: string[]; reason?: string | null };
}

export interface ValuationItem {
  ticker_symbol: string;
  sector: string | null;
  price: number | null;
  intrinsic: Measure;
  fair_low: number | null;
  fair_high: number | null;
  upside: number;
  margin_of_safety: number | null;
  uncertainty: number | null;
  actionable: boolean;
  methods_used: string[];
  link: string;
}

export interface RiskFlag {
  kind: string;
  ticker_symbol: string | null;
  severity: string;
  check_name: string | null;
  detail: string;
  trade_date: IsoDate | null;
  link: string | null;
}

export interface SignalsOut {
  as_of: IsoDate;
  model: string;
  universe: number;
  scored: number;
  unscored: number;
  unscored_reasons: Record<string, number>;
  buy_candidates: SignalItem[];
  watch: SignalItem[];
  neutral: SignalItem[];
  weak: SignalItem[];
  avoid: SignalItem[];
  value_traps: SignalItem[];
  compounders: SignalItem[];
  compounder_threshold: number;
  valuation_upside: ValuationItem[];
  valuation_downside: ValuationItem[];
  risk_flags: RiskFlag[];
  factor_combinations: { positive: SignalItem[]; negative: SignalItem[] };
  disclaimer: string;
}

export interface BacktestSummary {
  run_id: number;
  name: string;
  purpose: string;
  model: string;
  start_date: IsoDate;
  end_date: IsoDate;
  top_n: number;
  cost_rate: number;
  segments: number;
  status: string;
  reason: string | null;
  linked_total_return: Measure;
  first_segment: Record<string, Measure>;
  benchmarks: string[];
}

export interface BacktestPage {
  items: BacktestSummary[];
  next_cursor: string | null;
  total: number;
}

export interface EquityPoint {
  day: IsoDate;
  segment: string;
  equity: number;
  drawdown: number;
  benchmarks: Record<string, number | null>;
}

export interface BacktestDetail {
  run: BacktestSummary;
  weights: Record<string, number>;
  costs: Record<string, number>;
  results: Record<string, Record<string, Record<string, Measure>>>;
  equity: EquityPoint[];
  max_drawdown: Measure;
  turnover: { day: IsoDate; segment: string; buys: number; sells: number; exits: number; traded_value: number; cost: number }[];
  disclaimer: string;
}
