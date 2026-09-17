import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearApiCache } from "../hooks/useApi";

afterEach(() => {
  cleanup();
  clearApiCache();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Stub fetch with a map of path-prefix → JSON payload (real fixtures). */
export function stubFetch(routes: Record<string, unknown>, calls: string[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      calls.push(url);
      const hit = Object.entries(routes).find(([prefix]) => url.startsWith(prefix));
      if (!hit) return new Response(JSON.stringify({ message: `no stub for ${url}` }), { status: 404, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify(hit[1]), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}
