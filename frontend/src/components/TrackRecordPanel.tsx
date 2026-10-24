"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type CoachTrade, type SignalRow } from "@/lib/api";
import { fmtCandle, fmtUsd, fmtUtc, pairName } from "@/lib/format";
import { useLive } from "@/lib/live";
import { Badge, Panel, Stat } from "@/components/ui";

function signed(v: number | null | undefined, digits = 2, suffix = "") {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
}

export function TrackRecordPanel() {
  const live = useLive();
  const [closed, setClosed] = useState<CoachTrade[]>([]);
  const [calls, setCalls] = useState<SignalRow[]>([]);

  const load = useCallback(() => {
    api.closedTrades().then(setClosed).catch(() => {});
    api.signals(true, 50).then(setCalls).catch(() => {});
  }, []);
  useEffect(() => {
    const first = setTimeout(load, 0);
    const id = setInterval(load, 60_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load, live.version]);

  const s = live.stats;
  return (
    <Panel title="Track record (live, since you started)">
      {!s ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Paper balance" value={fmtUsd(s.balance)} hint={`started ${fmtUsd(s.starting_balance)}`} />
            <Stat label="Your trades" value={`${s.your_trades.closed} closed`}
              hint={s.your_trades.win_rate != null ? `${Math.round(s.your_trades.win_rate * 100)}% won · ${signed(s.your_trades.total_pnl, 2, " $")}` : "none yet"} />
            <Stat label="AI calls scored" value={`${s.ai_track_record.scored} / ${s.ai_track_record.calls}`}
              hint={s.ai_track_record.average_r != null ? `avg ${signed(s.ai_track_record.average_r, 2, " R")} · ${Math.round((s.ai_track_record.win_rate ?? 0) * 100)}% won` : "waiting for outcomes"} />
            <Stat label="Signals" value={`${s.signals_followed} taken`} hint={`${s.signals_skipped} skipped · ${s.signals_expired} expired`} />
          </div>
          <p className="text-[11px] text-muted">
            &quot;AI calls&quot; scores every BUY/SELL the model made as if it had been followed exactly (spread included),
            whether or not you took it - the honest live test of the AI. Real money should only be considered after many
            scored calls with a clearly positive average.
          </p>

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="mb-1 text-[11px] uppercase tracking-wider text-muted">Your closed trades</h3>
              {closed.length === 0 ? (
                <p className="text-sm text-muted">None yet.</p>
              ) : (
                <div className="max-h-72 overflow-auto">
                  <table className="w-full font-mono text-xs tabular-nums">
                    <thead className="sticky top-0 bg-panel text-left text-muted">
                      <tr>{["Closed (UTC)", "Pair", "Side", "Pips", "P/L", "R", "Balance"].map((h) => <th key={h} className="px-2 py-1 font-normal">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {closed.map((t) => (
                        <tr key={t.id} className="border-t border-edge">
                          <td className="px-2 py-1 text-muted">{fmtUtc(t.closed_at).replace(" UTC", "")}</td>
                          <td className="px-2 py-1">{pairName(t.instrument)}</td>
                          <td className="px-2 py-1"><Badge tone={t.side === "BUY" ? "ok" : "bad"}>{t.side}</Badge></td>
                          <td className="px-2 py-1">{signed(t.pips, 1)}</td>
                          <td className={`px-2 py-1 ${(t.pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}`}>{signed(t.pnl)}</td>
                          <td className="px-2 py-1">{signed(t.r_multiple, 2)}</td>
                          <td className="px-2 py-1">{fmtUsd(t.balance_after)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div>
              <h3 className="mb-1 text-[11px] uppercase tracking-wider text-muted">Recent AI calls and what happened</h3>
              {calls.length === 0 ? (
                <p className="text-sm text-muted">No BUY/SELL calls yet.</p>
              ) : (
                <div className="max-h-72 overflow-auto">
                  <table className="w-full font-mono text-xs tabular-nums">
                    <thead className="sticky top-0 bg-panel text-left text-muted">
                      <tr>{["Candle close (UTC)", "Pair", "Call", "You", "Outcome"].map((h) => <th key={h} className="px-2 py-1 font-normal">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {calls.map((c) => (
                        <tr key={c.id} className="border-t border-edge">
                          <td className="px-2 py-1 text-muted">{fmtCandle(c.candle_time).replace(" UTC", "")}</td>
                          <td className="px-2 py-1">{pairName(c.instrument)}</td>
                          <td className="px-2 py-1"><Badge tone={c.decision === "BUY" ? "ok" : "bad"}>{c.decision}</Badge></td>
                          <td className="px-2 py-1 text-muted">{c.status}</td>
                          <td className={`px-2 py-1 ${c.outcome_r == null ? "text-muted" : c.outcome_r >= 0 ? "text-buy" : "text-sell"}`}>
                            {c.outcome_r == null ? "pending" : `${signed(c.outcome_r, 2, " R")} (${c.outcome_reason})`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
