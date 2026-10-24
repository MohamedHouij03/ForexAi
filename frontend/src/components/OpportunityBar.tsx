"use client";

import { useEffect, useState } from "react";
import { useInstrument } from "@/lib/instrument";
import { useLive } from "@/lib/live";

const TONE = {
  BUY: "border-buy/70 bg-buy/10 text-buy",
  SELL: "border-sell/70 bg-sell/10 text-sell",
  WAIT: "border-edge text-muted",
} as const;

function minutesLeft(until: string | null, now: number): string | null {
  if (!until) return null;
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return null;
  return `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
}

/** Every watched pair at a glance: the coach scans all of them; click one to look at it. */
export function OpportunityBar() {
  const { instruments, current, select } = useInstrument();
  const live = useLive();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const openOn = new Set(live.openTrades.map((t) => t.instrument));
  return (
    <section className="space-y-2">
      {!live.notificationsOn && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-wait/50 bg-wait/10 px-4 py-2.5">
          <p className="text-sm text-wait">
            Turn on alerts to hear a sound and get a desktop notification the moment any pair has a BUY or SELL.
          </p>
          <button onClick={live.enableNotifications}
            className="rounded bg-wait px-3 py-1.5 text-sm font-semibold text-bg hover:bg-wait/90">
            Enable alerts
          </button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-edge bg-panel px-3 py-2">
        <span className="mr-1 text-[11px] uppercase tracking-wider text-muted">Watching</span>
        {instruments.map((i) => {
          const sig = live.signals[i.name];
          const left = sig?.status === "actionable" ? minutesLeft(sig.expires_at, now) : null;
          const decision = left ? sig!.decision : "WAIT";
          const selected = current?.name === i.name;
          return (
            <button
              key={i.name}
              onClick={() => select(i.name)}
              className={`flex items-center gap-2 rounded border px-2.5 py-1 text-xs transition-colors ${TONE[decision]} ${selected ? "ring-1 ring-fg/40" : ""}`}
              title={sig?.reason ?? "No signal yet"}
            >
              <span className="font-mono font-semibold text-fg">{i.display_name}</span>
              <span className="font-semibold">{decision}</span>
              {left && <span className="font-mono text-fg">{left}</span>}
              {openOn.has(i.name) && <span className="rounded bg-accent/20 px-1 text-[10px] text-accent">open trade</span>}
            </button>
          );
        })}
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted"
          title="When any pair gets a BUY/SELL (or a close alert), switch the screen to it automatically">
          <input type="checkbox" checked={live.autoFollow} onChange={(e) => live.setAutoFollow(e.target.checked)}
            className="accent-accent" />
          Jump to new signals automatically
        </label>
      </div>
    </section>
  );
}
