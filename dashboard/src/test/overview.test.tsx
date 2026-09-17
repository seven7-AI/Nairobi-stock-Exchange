import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { VersionProvider } from "../hooks/useVersion";
import { Overview } from "../pages/Overview";
import { System } from "../pages/System";
import overview from "./fixtures/overview.json";
import status from "./fixtures/status.json";
import version from "./fixtures/version.json";
import { stubFetch } from "./setup";

describe("Overview and System from captured live payloads", () => {
  it("renders the overview tiles, sources and pipelines", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/overview": overview });
    render(
      <MemoryRouter>
        <VersionProvider intervalMs={600_000}>
          <Overview />
        </VersionProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Tracked stocks")).toBeInTheDocument());
    expect(screen.getByText(String(overview.tracked_stocks))).toBeInTheDocument();
    expect(screen.getByText(`${overview.open_findings.error} error`)).toBeInTheDocument();
    for (const p of overview.pipelines) expect(screen.getAllByText(p.pipeline).length).toBeGreaterThan(0);
    expect(screen.getByText(overview.source.name)).toBeInTheDocument();
    // all-unavailable forecasts say so instead of showing 0
    expect(screen.getByText(/last known/)).toBeInTheDocument();
  });

  it("renders the system page tables and jobs", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version, "/api/v1/dashboard/status": status });
    render(
      <MemoryRouter>
        <VersionProvider intervalMs={600_000}>
          <System />
        </VersionProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Analytics store")).toBeInTheDocument());
    expect(screen.getAllByText(status.store.revision!).length).toBeGreaterThan(0);
    for (const c of status.cron) expect(screen.getAllByText(c.expression).length).toBeGreaterThan(0);
    expect(screen.getByText("market_metrics")).toBeInTheDocument();
    expect(screen.getAllByText("pipeline:daily").length).toBeGreaterThan(0);
  });

  it("shows the API error with a retry", async () => {
    stubFetch({ "/api/v1/dashboard/status/version": version });
    render(
      <MemoryRouter>
        <VersionProvider intervalMs={600_000}>
          <Overview />
        </VersionProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
