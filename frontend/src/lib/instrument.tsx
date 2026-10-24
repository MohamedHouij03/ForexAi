"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type InstrumentInfo } from "@/lib/api";

const STORAGE_KEY = "forex-ai.instrument";

type InstrumentContextValue = {
  instruments: InstrumentInfo[];
  current: InstrumentInfo | null;
  select: (name: string) => void;
  error: string | null;
};

const InstrumentContext = createContext<InstrumentContextValue>({
  instruments: [],
  current: null,
  select: () => {},
  error: null,
});

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Loads the watchlist (INSTRUMENTS on the backend) and remembers the selected instrument in this browser. */
export function InstrumentProvider({ children }: { children: ReactNode }) {
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await api.instruments();
        if (cancelled) return;
        setInstruments(list);
        setError(null);
        setSelected((prev) => {
          const wanted = prev ?? readStored();
          return list.some((i) => i.name === wanted) ? wanted : (list[0]?.name ?? null);
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    const first = setTimeout(load, 0);
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const select = useCallback((name: string) => {
    setSelected(name);
    try {
      window.localStorage.setItem(STORAGE_KEY, name);
    } catch {}
  }, []);

  const current = instruments.find((i) => i.name === selected) ?? null;
  return (
    <InstrumentContext.Provider value={{ instruments, current, select, error }}>{children}</InstrumentContext.Provider>
  );
}

export function useInstrument() {
  return useContext(InstrumentContext);
}

export function InstrumentSelect() {
  const { instruments, current, select } = useInstrument();
  if (instruments.length === 0) return null;
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      <span className="sr-only sm:not-sr-only">Viewing</span>
      <select
        value={current?.name ?? ""}
        onChange={(e) => select(e.target.value)}
        className="rounded border border-edge bg-panel px-2 py-1.5 font-mono text-sm text-fg outline-none focus:border-accent"
      >
        {instruments.map((i) => (
          <option key={i.name} value={i.name}>
            {i.display_name}
            {i.candles === 0 ? " (no data)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
