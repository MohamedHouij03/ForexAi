"use client";

import { useState } from "react";
import { api, type CoachTrade } from "@/lib/api";
import { fmtLots, fmtPrice, fmtUsd, fmtUtc, pairName } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { quoteToUsd, useLive } from "@/lib/live";
import { Dialog, Field, buttonClass, inputClass } from "@/components/Dialog";
import { Badge, Panel } from "@/components/ui";

export function OpenTradesPanel() {
  const live = useLive();
  const { instruments } = useInstrument();
  const [closing, setClosing] = useState<CoachTrade | null>(null);
  const [exitPrice, setExitPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const meta = (name: string) => instruments.find((i) => i.name === name);

  function openClose(t: CoachTrade, price: number) {
    setClosing(t);
    setExitPrice(price.toFixed(meta(t.instrument)?.display_precision ?? 5));
    setError(null);
  }

  async function submitClose() {
    if (!closing) return;
    setBusy(true);
    setError(null);
    try {
      await api.closeTrade(closing.id, Number(exitPrice));
      setClosing(null);
      live.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`Open trades (${live.openTrades.length})`}>
      {live.openTrades.length === 0 ? (
        <p className="text-sm text-muted">No open trades. When you take a signal, the coach follows it here.</p>
      ) : (
        <div className="space-y-3">
          {live.openTrades.map((t) => {
            const m = meta(t.instrument);
            const digits = m?.display_precision ?? 5;
            const pip = m?.pip_size ?? 0.0001;
            const livePrice = live.prices[t.instrument];
            const price = livePrice?.price ?? t.last_price ?? t.entry_price;
            const diff = t.side === "BUY" ? price - t.entry_price : t.entry_price - price;
            const conv = quoteToUsd(t.instrument, price);
            const pnl = conv == null ? null : diff * t.units * conv;
            const pips = diff / pip;
            return (
              <div key={t.id} className={`rounded border p-3 ${t.advice ? "border-wait bg-wait/10" : "border-edge"}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{pairName(t.instrument)}</span>
                    <Badge tone={t.side === "BUY" ? "ok" : "bad"}>{t.side}</Badge>
                    <span className="whitespace-nowrap text-xs text-muted">{t.units.toLocaleString()} {m?.unit_label ?? "units"} · {fmtLots(t.units, m?.asset_class === "metal")} lot</span>
                  </div>
                  <span className={`whitespace-nowrap font-mono text-base font-semibold tabular-nums ${pips >= 0 ? "text-buy" : "text-sell"}`}>
                    {pips >= 0 ? "+" : ""}{pips.toFixed(1)} pips · {pnl == null ? "—" : `${pnl >= 0 ? "+" : "-"}${fmtUsd(Math.abs(pnl))}`}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-4 gap-2 font-mono text-xs tabular-nums">
                  <div><div className="font-sans text-[10px] uppercase text-muted">Entry</div>{fmtPrice(t.entry_price, digits)}</div>
                  <div>
                    <div className="font-sans text-[10px] uppercase text-muted">Current {livePrice?.source === "stream" ? "· live" : livePrice?.source === "poll" ? "· every 90 s" : ""}</div>
                    {fmtPrice(price, digits)}
                  </div>
                  <div><div className="font-sans text-[10px] uppercase text-muted">Stop loss</div>{fmtPrice(t.stop_loss, digits)}</div>
                  <div><div className="font-sans text-[10px] uppercase text-muted">Take profit</div>{fmtPrice(t.take_profit, digits)}</div>
                </div>
                <div className="mt-2 flex items-center justify-between gap-2 text-xs">
                  <span className="text-muted">
                    Opened {fmtUtc(t.opened_at)} · close by {fmtUtc(t.close_by)} · risk {fmtUsd(t.risk_amount)}
                  </span>
                  <div className="flex gap-2">
                    <button
                      className="rounded px-2 py-2 text-xs text-muted hover:text-sell"
                      title="Remove this trade if you did not actually place it at your broker"
                      onClick={async () => {
                        if (window.confirm(`Remove this ${pairName(t.instrument)} ${t.side}? Only do this if you did NOT place it at your broker.`)) {
                          await api.cancelTrade(t.id).catch(() => {});
                          live.refresh();
                        }
                      }}
                    >
                      I didn&apos;t take it
                    </button>
                    <button className={buttonClass.secondary} onClick={() => openClose(t, price)}>I closed it</button>
                  </div>
                </div>
                {t.advice && (
                  <p className="mt-2 rounded bg-wait/20 px-2 py-1.5 text-sm font-medium text-wait">{t.advice === "close" ? "CLOSE NOW" : "HEADS UP"}: {t.advice_reason}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={closing != null} title={`I closed ${pairName(closing?.instrument)} ${closing?.side}`} onClose={() => setClosing(null)}>
        <div className="space-y-3">
          <Field label="Price you closed at" hint="The exit price your broker shows (for a stop or target hit: that level).">
            <input className={inputClass} value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} inputMode="decimal" autoFocus />
          </Field>
          {error && <p className="text-sm text-sell">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button className={buttonClass.secondary} onClick={() => setClosing(null)}>Cancel</button>
            <button className={buttonClass.primary} disabled={busy || !exitPrice} onClick={submitClose}>
              {busy ? "Saving…" : "Confirm"}
            </button>
          </div>
        </div>
      </Dialog>
    </Panel>
  );
}
