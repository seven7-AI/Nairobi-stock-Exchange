// Fetch a dashboard payload, keep the last good value while a refetch runs, and
// refetch when the store version changes. Results are memoised per (key, version)
// so navigating back is instant and a version bump invalidates everything.
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

interface Outcome<T> {
  key: string; // the base key, without the version
  data?: T;
  error?: string;
  status?: number;
}

export function useApi<T>(key: string | null, loader: (signal: AbortSignal) => Promise<T>): ApiState<T> {
  const { version } = useVersion();
  const cacheKey = key === null ? null : `${key}#${version ?? "?"}`;
  // The first poll only names the version we already fetched under "?": adopt it.
  if (key !== null && cacheKey !== null && !cache.has(cacheKey) && cache.has(`${key}#?`)) {
    cache.set(cacheKey, cache.get(`${key}#?`));
    cache.delete(`${key}#?`);
  }
  const cached = cacheKey !== null ? (cache.get(cacheKey) as T | undefined) : undefined;
  const [last, setLast] = useState<Outcome<T> | null>(null);
  const [tick, setTick] = useState(0);
  // `loader` is recreated every render; the key identifies the request, so the
  // effect reads the latest loader through a ref instead of depending on it.
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    if (cacheKey === null || cache.has(cacheKey)) return;
    const controller = new AbortController();
    loaderRef
      .current(controller.signal)
      .then((next) => {
        cache.set(cacheKey, next);
        setLast({ key: key ?? "", data: next, status: 200 });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setLast({ key: key ?? "", error: err instanceof Error ? err.message : String(err), status: err instanceof ApiError ? err.status : undefined });
      });
    return () => controller.abort();
  }, [cacheKey, key, tick]);

  const refetch = useCallback(() => {
    if (cacheKey) cache.delete(cacheKey);
    setTick((t) => t + 1);
  }, [cacheKey]);

  const same = last !== null && last.key === key;
  const data = cached ?? (same ? last.data : undefined);
  const error = cached === undefined && same ? last.error : undefined;
  return {
    data,
    error,
    status: same ? last.status : undefined,
    loading: cacheKey !== null && cached === undefined && data === undefined && error === undefined,
    stale: cacheKey !== null && cached === undefined && data !== undefined,
    refetch,
  };
}

export function clearApiCache(): void {
  cache.clear();
}
