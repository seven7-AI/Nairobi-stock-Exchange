import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { VersionProvider } from "../hooks/useVersion";
import { StockDetail } from "../pages/StockDetail";
import { Stocks } from "../pages/Stocks";
import prices from "./fixtures/prices-KCB-max.json";
import stock from "./fixtures/stock-KCB.json";
import stocks from "./fixtures/stocks.json";
import version from "./fixtures/version.json";
import { stubFetch } from "./setup";

function mount(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <VersionProvider intervalMs={600_000}>
        <Routes>
          <Route path="/stocks" element={<Stocks />} />
          <Route path="/stocks/:ticker" element={<StockDetail />} />
        </Routes>
      </VersionProvider>
    </MemoryRouter>,
  );
}

describe("stock pages from captured live payloads", () => {
  it("renders KCB with reasons where the store has none", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/stocks/KCB/prices": prices, "/api/v1/dashboard/stocks/KCB": stock });
    mount("/stocks/KCB?range=max");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("KCB"));
    // metrics the gap makes unavailable carry the gap in their reason
    const ret12 = stock.profile.metrics.returns.return_12m;
    expect(ret12.status).toBe("unavailable");
    await waitFor(() => expect(screen.getAllByText(ret12.reason!).length).toBeGreaterThan(0));
    // a bank's interest coverage is not applicable, shown as n/a with the reason
    const ic = stock.profile.metrics.quality.interest_coverage;
    expect(ic.status).toBe("not_applicable");
    await screen.findByText("Fundamentals");
    screen.getByRole("button", { name: "Fundamentals" }).click();
    await waitFor(() => expect(screen.getAllByText(ic.reason!).length).toBeGreaterThan(0));
    // geographic exposure is honestly unavailable
    expect(screen.getAllByText(stock.geographic.reason).length).toBeGreaterThan(0);
    // the forecast card names the reason and the last known date
    expect(screen.getAllByText(stock.forecast_availability.reason!).length).toBeGreaterThan(0);
    // no non-known measure ever renders as a bare 0
    for (const chip of document.querySelectorAll(".measure--na")) expect(chip.textContent).not.toBe("0");
    // the gap is spelled out under the chart
    await waitFor(() => expect(screen.getAllByText(/572 d/).length).toBeGreaterThan(0));
  });

  it("lists every equity with sortable columns", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/stocks": stocks });
    mount("/stocks");
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    expect(screen.getAllByRole("row")).toHaveLength(stocks.items.length + 1);
    expect(screen.getByRole("link", { name: "KCB" })).toHaveAttribute("href", "/stocks/KCB");
  });
});
