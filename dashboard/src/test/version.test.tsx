import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useApi } from "../hooks/useApi";
import { VersionProvider } from "../hooks/useVersion";
import { fetchJson } from "../api/client";

function Probe() {
  const { data } = useApi("probe", (signal) => fetchJson<{ n: number }>("/probe", undefined, signal));
  return <div>n={data?.n ?? "?"}</div>;
}

describe("version polling invalidates views", () => {
  it("refetches mounted views when the store version changes, not otherwise", async () => {
    let version = "a";
    let n = 0;
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        if (url.includes("/status/version")) return Response.json({ version, latest_market_date: null, latest_analytics_date: null, analytics_updated_at: null, scraper_updated_at: null, generated_at: "" });
        n += 1;
        return Response.json({ n });
      }),
    );
    render(
      <VersionProvider intervalMs={1000}>
        <Probe />
      </VersionProvider>,
    );
    await waitFor(() => expect(screen.getByText("n=1")).toBeInTheDocument());
    const probes = () => calls.filter((c) => c.includes("/probe")).length;
    expect(probes()).toBe(1);
    // a poll with the same version: no refetch
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1100));
    });
    expect(probes()).toBe(1);
    // the store changed: the view refetches
    version = "b";
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1100));
    });
    await waitFor(() => expect(screen.getByText("n=2")).toBeInTheDocument());
    expect(probes()).toBe(2);
  });
});
