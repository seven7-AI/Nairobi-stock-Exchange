// Polls /status/version and hands every mounted view the current store version so a
// change (a pipeline wrote, the scraper wrote) refetches what is on screen.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/api";
import { ApiError } from "../api/client";
import type { VersionOut } from "../api/types";

export interface VersionState {
  version: string | null;
  snapshot: VersionOut | null;
  lastPolledAt: Date | null;
  pollError: string | null;
  refreshing: boolean;
  refreshNow: () => void;
}

const VersionContext = createContext<VersionState>({
  version: null,
  snapshot: null,
  lastPolledAt: null,
  pollError: null,
  refreshing: false,
  refreshNow: () => {},
});

export function VersionProvider({ intervalMs = 60_000, children }: { intervalMs?: number; children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<VersionOut | null>(null);
  const [lastPolledAt, setLastPolledAt] = useState<Date | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const inflight = useRef(false);

  const poll = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    setRefreshing(true);
    try {
      const next = await api.version();
      setSnapshot((previous) => (previous?.version === next.version ? previous : next));
      setPollError(null);
    } catch (error) {
      setPollError(error instanceof ApiError ? error.message : "cannot reach the API");
    } finally {
      setLastPolledAt(new Date());
      setRefreshing(false);
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    // first poll on the next tick, so the effect itself sets no state synchronously
    const first = window.setTimeout(() => void poll(), 0);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, poll]);

  return (
    <VersionContext.Provider
      value={{ version: snapshot?.version ?? null, snapshot, lastPolledAt, pollError, refreshing, refreshNow: () => void poll() }}
    >
      {children}
    </VersionContext.Provider>
  );
}

export function useVersion(): VersionState {
  return useContext(VersionContext);
}
