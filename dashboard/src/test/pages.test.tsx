import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { VersionProvider } from "../hooks/useVersion";
import { Analytics } from "../pages/Analytics";
import { Backtests } from "../pages/Backtests";
import { Forecasts } from "../pages/Forecasts";
import { Signals } from "../pages/Signals";
import analytics from "./fixtures/analytics.json";
import backtest1 from "./fixtures/backtest-1.json";
import backtests from "./fixtures/backtests.json";
import forecastsKcb from "./fixtures/forecasts-KCB.json";
import signals from "./fixtures/signals.json";
import status from "./fixtures/status.json";
import version from "./fixtures/version.json";
import { stubFetch } from "./setup";

function mount(node: ReactNode, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <VersionProvider intervalMs={600_000}>{node}</VersionProvider>
    </MemoryRouter>,
  );
}

describe("analytics, forecasts, signals and backtests from captured live payloads", () => {
  it("analytics lists the ranked universe, unscored last with reasons", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/analytics": analytics });
    mount(<Analytics />);
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(analytics.rows.length);
    const ranked = analytics.rows.filter((r) => r.market_rank !== null).length;
    expect(rows[0]).toHaveTextContent(analytics.rows[0].ticker_symbol);
    const unscored = analytics.rows.find((r) => r.market_rank === null)!;
    expect(rows[ranked]).toHaveTextContent(unscored.overall.reason!.slice(0, 20));
    expect(screen.getByRole("combobox", { name: "Result date" })).toHaveValue(analytics.as_of);
  });

  it("forecasts show ranges and the reason when the date is unavailable, never a target", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/forecasts": forecastsKcb });
    mount(<Forecasts />, "/forecasts?ticker=KCB");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Forecasts"));
    expect(screen.getAllByText(forecastsKcb.availability.reason!).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Show the last known forecast/ })).toBeInTheDocument();
    // accuracy rows carry n and a MAE per horizon
    const ar1 = forecastsKcb.accuracy.ar1["12m"];
    expect(screen.getAllByText(String(ar1.n)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not price targets|not investment advice/i).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/target price/i);
  });

  it("signals buckets match the payload and link to stocks", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/signals": signals });
    mount(<Signals />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Research signals"));
    for (const item of signals.buy_candidates) expect(document.querySelector(`a[href="/stocks/${item.ticker_symbol}"]`)).not.toBeNull();
    expect(screen.getAllByText(`${signals.buy_candidates.length} instruments`).length).toBeGreaterThan(0);
    const trap = signals.value_traps[0];
    expect(screen.getAllByText(trap.extra.signals![0]).length).toBeGreaterThan(0);
  });

  it("backtests show the stored run with its equity curve and benchmarks", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/status": status, "/api/v1/dashboard/backtests/1": backtest1, "/api/v1/dashboard/backtests": backtests });
    mount(<Backtests />, "/backtests?run=1");
    await waitFor(() => expect(screen.getAllByText(backtest1.run.name).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText("Headline")).toBeInTheDocument());
    expect(screen.getAllByText("^NASI").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/candidate/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not investment advice/i).length).toBeGreaterThan(0);
  });
});
