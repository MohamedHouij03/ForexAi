"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Fetch now and then every `intervalMs`. `fetcher` must be a stable reference.
 * (Phase 9 replaces polling of live prices with a WebSocket stream.)
 */
export function usePolling<T>(fetcher: (() => Promise<T>) | null, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    if (!fetcher) return;
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [fetcher]);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh, intervalMs]);

  return { data, error, updatedAt, refresh };
}
