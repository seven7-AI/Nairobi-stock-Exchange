// Fetch a dashboard payload, keep the last good value while a refetch runs, and
// refetch when the store version changes. Results are memoised per (key, version)
// so navigating back is instant.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useVersion } from "./useVersion";

const cache = new Map<string, unknown>();

export interface ApiState<T> {
  data: T | undefined;
  error: string | undefined;
  status: number | undefined;
  loading: boolean;
  stale: boolean;
  refetch: () => void;
}

export function useApi<T>(key: string | null, loader: (signal: AbortSignal) => Promise<T>): ApiState<T> {
  const { version } = useVersion();
  const cacheKey = key === null ? null : `${key}#${version ?? "?"}`;
  const [data, setData] = useState<T | undefined>(() =>
    cacheKey ? (cache.get(cacheKey) as T | undefined) : undefined,
  );
  const [error, setError] = useState<string | undefined>();
  const [status, setStatus] = useState<number | undefined>();
  const [loading, setLoading] = useState(cacheKey !== null && !cache.has(cacheKey));
  const [stale, setStale] = useState(false);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (cacheKey === null) {
      setLoading(false);
      return;
    }
    // the first poll only names the version we already fetched under "?": adopt it
    if (key !== null && !cache.has(cacheKey) && cache.has(`${key}#?`)) {
      cache.set(cacheKey, cache.get(`${key}#?`));
      cache.delete(`${key}#?`);
    }
    const cached = cache.get(cacheKey) as T | undefined;
    if (cached !== undefined && tick === 0) {
      setData(cached);
      setLoading(false);
      setStale(false);
      return;
    }
    const controller = new AbortController();
    setStale(data !== undefined);
    setLoading(data === undefined);
    setError(undefined);
    loaderRef
      .current(controller.signal)
      .then((next) => {
        cache.set(cacheKey, next);
        setData(next);
        setStatus(200);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus(err instanceof ApiError ? err.status : undefined);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setStale(false);
        }
      });
    return () => controller.abort();
  }, [cacheKey, key, tick]);

  const refetch = useCallback(() => {
    if (cacheKey) cache.delete(cacheKey);
    setTick((t) => t + 1);
  }, [cacheKey]);

  return { data, error, status, loading, stale, refetch };
}

export function clearApiCache(): void {
  cache.clear();
}
