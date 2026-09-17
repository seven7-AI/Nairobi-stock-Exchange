// One function per endpoint - the only place paths and query parameters are spelled.
import { fetchJson } from "./client";
import type {
  AnalyticsOut,
  BacktestDetail,
  BacktestPage,
  ForecastsOut,
  MarketOut,
  OverviewOut,
  PriceHistory,
  SignalsOut,
  Statements,
  StatusOut,
  StockDetail,
  StockListPage,
  VersionOut,
} from "./types";

export type PriceRange = "1m" | "3m" | "6m" | "1y" | "3y" | "5y" | "max";
export type Interval = "daily" | "weekly" | "monthly";

export const api = {
  version: (signal?: AbortSignal) => fetchJson<VersionOut>("/status/version", undefined, signal),
  status: (signal?: AbortSignal) => fetchJson<StatusOut>("/status", undefined, signal),
  overview: (signal?: AbortSignal) => fetchJson<OverviewOut>("/overview", undefined, signal),
  market: (asOf?: string, signal?: AbortSignal) => fetchJson<MarketOut>("/market", { as_of: asOf }, signal),
  stocks: (
    q: { q?: string; sector?: string; sort?: string; order?: string; limit?: number; cursor?: string },
    signal?: AbortSignal,
  ) => fetchJson<StockListPage>("/stocks", q, signal),
  stock: (ticker: string, asOf?: string, signal?: AbortSignal) =>
    fetchJson<StockDetail>(`/stocks/${encodeURIComponent(ticker)}`, { as_of: asOf }, signal),
  prices: (ticker: string, range: PriceRange, interval: Interval = "daily", signal?: AbortSignal) =>
    fetchJson<PriceHistory>(`/stocks/${encodeURIComponent(ticker)}/prices`, { range, interval }, signal),
  statements: (ticker: string, signal?: AbortSignal) =>
    fetchJson<Statements>(`/stocks/${encodeURIComponent(ticker)}/statements`, undefined, signal),
  analytics: (asOf?: string, sector?: string, signal?: AbortSignal) =>
    fetchJson<AnalyticsOut>("/analytics", { as_of: asOf, sector }, signal),
  forecasts: (q: { as_of?: string; ticker?: string; model?: string; horizon?: number }, signal?: AbortSignal) =>
    fetchJson<ForecastsOut>("/forecasts", q, signal),
  signals: (asOf?: string, signal?: AbortSignal) => fetchJson<SignalsOut>("/signals", { as_of: asOf }, signal),
  backtests: (signal?: AbortSignal) => fetchJson<BacktestPage>("/backtests", undefined, signal),
  backtest: (runId: number, signal?: AbortSignal) => fetchJson<BacktestDetail>(`/backtests/${runId}`, undefined, signal),
};
