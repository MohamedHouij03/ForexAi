"use client";

import { pairName } from "@/lib/format";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { API_URL, api, type CoachStats, type CoachTrade, type LiveStatus, type SignalRow } from "@/lib/api";
import { useInstrument } from "@/lib/instrument";

const ALERTS_KEY = "forex-ai.alerts";
const FOLLOW_KEY = "forex-ai.autofollow";

function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {}
}

type Price = { instrument: string; price: number; time: string; source: "stream" | "candle" | "poll" };
export type Toast = { id: number; tone: "buy" | "sell" | "wait" | "info"; title: string; body: string; instrument?: string };

type LiveContextValue = {
  connected: boolean;
  status: LiveStatus | null;
  coachMode: string | null;
  prices: Record<string, Price>;
  signals: Record<string, SignalRow>; // latest signal per instrument
  openTrades: CoachTrade[];
  stats: CoachStats | null;
  toasts: Toast[];
  dismissToast: (id: number) => void;
  openToast: (toast: Toast) => void;
  autoFollow: boolean;
  setAutoFollow: (on: boolean) => void;
  notificationsOn: boolean;
  enableNotifications: () => Promise<void>;
  testAlert: () => void;
  refresh: () => void;
  version: number; // bumps on every trade/stats change (lets panels refetch)
};

const LiveContext = createContext<LiveContextValue | null>(null);

function wsUrl(): string {
  return `${API_URL.replace(/^http/, "ws")}/api/ws`;
}

/** Two short tones - audible cue for a new BUY/SELL or close advice. */
function beep(ctx: AudioContext | null, high: boolean) {
  if (!ctx) return;
  const now = ctx.currentTime;
  [0, 0.18].forEach((offset, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = high ? (i ? 988 : 784) : i ? 523 : 659;
    gain.gain.setValueAtTime(0.0001, now + offset);
    gain.gain.exponentialRampToValueAtTime(0.25, now + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.16);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.18);
  });
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [coachMode, setCoachMode] = useState<string | null>(null);
  const [prices, setPrices] = useState<Record<string, Price>>({});
  const [signals, setSignals] = useState<Record<string, SignalRow>>({});
  const [openTrades, setOpenTrades] = useState<CoachTrade[]>([]);
  const [stats, setStats] = useState<CoachStats | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [notificationsOn, setNotificationsOn] = useState(false);
  const [version, setVersion] = useState(0);
  const [autoFollow, setAutoFollowState] = useState(true);
  const { select } = useInstrument();
  const selectRef = useRef(select);
  const followRef = useRef(true);
  const audio = useRef<AudioContext | null>(null);
  const notifyRef = useRef(false);
  const seenSignals = useRef<Set<number>>(new Set());
  const seenAdvice = useRef<Set<string>>(new Set()); // "<trade id>:<advice>"

  useEffect(() => {
    selectRef.current = select;
  }, [select]);

  // Restore preferences: alerts stay on across visits (the browser remembers the permission);
  // sound needs one user gesture per page load, so the first click / key press anywhere unlocks it.
  useEffect(() => {
    const unlock = () => {
      if (!audio.current) {
        try {
          audio.current = new AudioContext();
        } catch {}
      }
      audio.current?.resume().catch(() => {});
    };
    const t = setTimeout(() => {
      const follow = stored(FOLLOW_KEY) !== "off";
      followRef.current = follow;
      setAutoFollowState(follow);
      const granted = typeof Notification === "undefined" || Notification.permission === "granted";
      if (stored(ALERTS_KEY) === "on" && granted) {
        notifyRef.current = true;
        setNotificationsOn(true);
      }
    }, 0);
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  const setAutoFollow = useCallback((on: boolean) => {
    followRef.current = on;
    setAutoFollowState(on);
    store(FOLLOW_KEY, on ? "on" : "off");
  }, []);

  const desktopNotes = useRef<Record<string, Notification>>({}); // open BUY/SELL notifications per pair
  const alert = useCallback((toast: Omit<Toast, "id">, loud: boolean) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { ...toast, id }]);
    if (loud) {
      beep(audio.current, toast.tone !== "info");
      if (notifyRef.current && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          const n = new Notification(toast.title, { body: toast.body, tag: toast.title, requireInteraction: true });
          if (toast.instrument && (toast.tone === "buy" || toast.tone === "sell")) desktopNotes.current[toast.instrument] = n;
          n.onclick = () => {
            window.focus();
            if (toast.instrument) selectRef.current(toast.instrument);
            n.close();
          };
        } catch {}
      }
    }
  }, []);

  // Latest call for every watchlist pair (the scanner), refreshed every minute; pushes arrive in between.
  useEffect(() => {
    const load = () =>
      api
        .currentSignals()
        .then((rows) =>
          setSignals((prev) => {
            const next = { ...prev };
            for (const r of rows) {
              if (!r.decision) continue;
              const row = r as SignalRow;
              seenSignals.current.add(row.id);
              if (!next[row.instrument] || next[row.instrument].id <= row.id) next[row.instrument] = row;
            }
            return next;
          }),
        )
        .catch(() => {});
    const first = setTimeout(load, 0);
    const id = setInterval(load, 60_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const refresh = useCallback(() => {
    api.openTrades().then(setOpenTrades).catch(() => {});
    api.coachStats().then(setStats).catch(() => {});
    setVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 1000;
    let stopped = false;

    const onMessage = (msg: { event: string; data: unknown }) => {
      const d = msg.data as Record<string, unknown>;
      switch (msg.event) {
        case "snapshot": {
          const snap = d as { status: LiveStatus | null; open_trades: CoachTrade[]; stats: CoachStats; coach_mode: string };
          setStatus(snap.status);
          setOpenTrades(snap.open_trades);
          snap.open_trades.forEach((t) => t.advice && seenAdvice.current.add(`${t.id}:${t.advice}`));
          setStats(snap.stats);
          setCoachMode(snap.coach_mode);
          if (snap.status?.prices) setPrices(snap.status.prices as Record<string, Price>);
          break;
        }
        case "status":
          setStatus(d as unknown as LiveStatus);
          break;
        case "price": {
          const p = d as unknown as Price;
          setPrices((prev) => ({ ...prev, [p.instrument]: p }));
          break;
        }
        case "signal": {
          const s = d as unknown as SignalRow;
          setSignals((prev) => ({ ...prev, [s.instrument]: s }));
          const fresh = !seenSignals.current.has(s.id);
          seenSignals.current.add(s.id);
          if (!fresh && s.status === "expired" && s.reason?.startsWith("Too late")) {
            // the opportunity is gone: remove its alert and say so quietly
            const pair = pairName(s.instrument);
            setToasts((t) => t.filter((x) => !(x.instrument === s.instrument && (x.tone === "buy" || x.tone === "sell"))));
            desktopNotes.current[s.instrument]?.close();
            delete desktopNotes.current[s.instrument];
            alert({ instrument: s.instrument, tone: "info", title: `${s.decision} ${pair} removed`,
              body: "Too late - the price already moved. Don't enter this one." }, false);
          }
          if (fresh && s.status === "actionable" && (s.decision === "BUY" || s.decision === "SELL")) {
            const pair = pairName(s.instrument);
            if (followRef.current) selectRef.current(s.instrument); // show the opportunity, whatever pair was on screen
            alert({
              instrument: s.instrument,
              tone: s.decision === "BUY" ? "buy" : "sell",
              title: `${s.decision} ${pair}${s.mode === "practice" ? " (practice)" : ""}`,
              body: `Entry ${s.entry} · SL ${s.stop_loss} · TP ${s.take_profit} · ${s.units} units, risk $${s.risk_amount?.toFixed(2)}`,
            }, true);
          }
          break;
        }
        case "trade": {
          const t = d as unknown as CoachTrade;
          setOpenTrades((prev) => {
            const rest = prev.filter((x) => x.id !== t.id);
            return t.status === "open" ? [...rest, t] : rest;
          });
          const key = `${t.id}:${t.advice}`;
          if (t.status === "open" && t.advice && !seenAdvice.current.has(key)) {
            seenAdvice.current.add(key);
            if (followRef.current) selectRef.current(t.instrument);
            const pair = pairName(t.instrument);
            alert({ instrument: t.instrument, tone: "wait",
              title: t.advice === "close" ? `CLOSE ${pair} ${t.side}` : `WATCH ${pair} ${t.side} - near the stop`,
              body: t.advice_reason ?? "" }, true);
          }
          setVersion((v) => v + 1);
          break;
        }
        case "stats":
          setStats(d as unknown as CoachStats);
          setVersion((v) => v + 1);
          break;
      }
    };

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        setConnected(true);
        delay = 1000;
      };
      ws.onmessage = (e) => {
        try {
          onMessage(JSON.parse(e.data));
        } catch {}
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) {
          retry = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 30_000);
        }
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    const ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25_000);
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, [alert]);

  const enableNotifications = useCallback(async () => {
    // A click is needed before browsers allow sound; this is that click.
    if (!audio.current) {
      try {
        audio.current = new AudioContext();
      } catch {}
    }
    await audio.current?.resume().catch(() => {});
    if (typeof Notification !== "undefined" && Notification.permission !== "granted") {
      await Notification.requestPermission().catch(() => "denied");
    }
    notifyRef.current = true;
    setNotificationsOn(true);
    store(ALERTS_KEY, "on");
    beep(audio.current, true);
  }, []);

  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const testAlert = useCallback(() => {
    alert({ tone: "buy", title: "Test alert", body: "This is how a BUY or SELL will look and sound. No trade was created." }, true);
  }, [alert]);
  const openToast = useCallback((toast: Toast) => {
    if (toast.instrument) selectRef.current(toast.instrument);
    setToasts((t) => t.filter((x) => x.id !== toast.id));
  }, []);

  return (
    <LiveContext.Provider value={{ connected, status, coachMode, prices, signals, openTrades, stats, toasts, dismissToast,
      openToast, autoFollow, setAutoFollow, notificationsOn, enableNotifications, testAlert, refresh, version }}>
      {children}
    </LiveContext.Provider>
  );
}

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used inside LiveProvider");
  return ctx;
}

/** USD value of one unit of the quote currency (USD-quoted pairs and USD-based pairs; crosses need a rate). */
export function quoteToUsd(instrument: string, price: number): number | null {
  const [base, quote] = instrument.split("_");
  if (quote === "USD") return 1;
  if (base === "USD") return 1 / price;
  return null;
}
