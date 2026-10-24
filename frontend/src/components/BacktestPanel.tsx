"use client";

import { useCallback, useState } from "react";
import { api, type BacktestResult, type GroupStats } from "@/lib/api";
import { fmtUsd, pairName } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { usePolling } from "@/lib/usePolling";
import { LineChart } from "@/components/LineChart";
import { Badge, Panel, Stat } from "@/components/ui";

const PERIOD_LABEL: Record<string, string> = { walk_forward: "Walk-forward period", test: "Untouched test period" };

function signed(v: number | null | undefined, digits = 2, suffix = "") {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
}

function Breakdown({ title, rows }: { title: string; rows: Record<string, GroupStats> }) {
  return (
    <div>
      <h3 className="mb-1 text-[11px] uppercase tracking-wider text-muted">{title}</h3>
      <table className="w-full font-mono text-xs tabular-nums">
        <tbody>
          {Object.entries(rows).map(([k, g]) => (
            <tr key={k} className="border-t border-edge">
              <td className="py-1 pr-2 font-sans text-muted">{pairName(k)}</td>
              <td className="py-1 pr-2 text-right">{g.trades}</td>
              <td className={`py-1 pr-2 text-right ${g.pnl >= 0 ? "text-buy" : "text-sell"}`}>{signed(g.pnl)}</td>
              <td className="py-1 text-right text-muted">{(g.win_rate * 100).toFixed(0)}% won</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BacktestPanel() {
  const [period, setPeriod] = useState<"test" | "walk_forward">("test");
  const fetcher = useCallback(() => api.backtest(period), [period]);
  const res = usePolling(fetcher, 120_000);
  const b: BacktestResult | null = res.data?.period === period ? res.data : null;
  const m = b?.metrics;
  const { instruments } = useInstrument();
  const digits = (name: unknown) => instruments.find((i) => i.name === name)?.display_precision ?? 5;

  return (
    <Panel
      title="Backtest · your rules, $100 start, out-of-sample signals only"
      right={
        <div className="flex gap-1">
          {(["walk_forward", "test"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded px-2.5 py-1 text-xs ${period === p ? "bg-edge text-fg" : "text-muted hover:text-fg"}`}
            >
              {PERIOD_LABEL[p]}
            </button>
          ))}
        </div>
      }
    >
      {!b || !m ? (
        <p className="text-sm text-muted">{res.error ?? "Loading…"}</p>
      ) : (
        <div className="space-y-5">
          <p className="text-xs text-muted">
            {b.model.replace("_", " ")} ({b.granularity}) · {b.start.slice(0, 10)} → {b.end.slice(0, 10)} · risk{" "}
            {b.config.risk_percent}% per trade, max {b.config.max_open_trades} open trade, daily stop{" "}
            {b.config.max_daily_loss_percent}%, spread included, gaps filled at the real price.
          </p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
            <Stat label="Balance" value={`${fmtUsd(m.starting_balance)} → ${fmtUsd(m.final_balance)}`} />
            <Stat label="Total return" value={signed(m.total_return_pct, 1, "%")} />
            <Stat label="Trades" value={m.trades} hint={`${b.signals} signals`} />
            <Stat label="Win rate" value={m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : "—"} hint={`1:${+(b.config.tp_atr / b.config.sl_atr).toFixed(2)} needs >${Math.round((100 * b.config.sl_atr) / (b.config.sl_atr + b.config.tp_atr))}% + costs`} />
            <Stat label="Profit factor" value={m.profit_factor?.toFixed(2) ?? "—"} hint="above 1 = profitable" />
            <Stat label="Max drawdown" value={m.max_drawdown_pct != null ? `${m.max_drawdown_pct.toFixed(1)}%` : "—"} />
            <Stat label="Sharpe ratio" value={m.sharpe_ratio?.toFixed(2) ?? "—"} />
            <Stat label="Average trade" value={signed(m.average_trade, 2, " $")} hint={`${signed(m.average_r, 3, " R")}`} />
            <Stat label="Average winner" value={signed(m.average_winner, 2, " $")} hint={`${m.average_pips_gained ?? "—"} pips`} />
            <Stat label="Average loser" value={signed(m.average_loser, 2, " $")} hint={`${m.average_pips_lost ?? "—"} pips`} />
            <Stat label="Longest streaks" value={`${m.longest_winning_streak ?? 0} W / ${m.longest_losing_streak ?? 0} L`} />
            <Stat
              label="Risk of ruin"
              value={m.risk_of_ruin?.prob_drawdown_50pct != null ? `${(m.risk_of_ruin.prob_drawdown_50pct * 100).toFixed(0)}%` : "—"}
              hint="chance of losing half (Monte Carlo)"
            />
          </div>

          {b.equity.length > 1 && (
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <h3 className="mb-1 text-[11px] uppercase tracking-wider text-muted">Account balance after each trade</h3>
                <LineChart
                  points={b.equity.map((p) => ({ t: p.time, v: p.balance }))}
                  label="Balance"
                  format={(v) => `$${v.toFixed(2)}`}
                  reference={{ value: m.starting_balance, label: "start" }}
                />
              </div>
              <div>
                <h3 className="mb-1 text-[11px] uppercase tracking-wider text-muted">Drawdown (% below the previous peak)</h3>
                <LineChart
                  points={b.equity.map((p) => ({ t: p.time, v: p.drawdown_pct }))}
                  label="Drawdown"
                  format={(v) => `${v.toFixed(1)}%`}
                  area
                />
              </div>
            </div>
          )}

          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            <Breakdown title="By year" rows={m.by_year ?? {}} />
            <Breakdown title="By instrument" rows={m.by_instrument ?? {}} />
            <Breakdown title="BUY vs SELL" rows={m.by_side ?? {}} />
            <Breakdown title="By session (entry)" rows={m.by_session ?? {}} />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-[11px] uppercase tracking-wider text-muted">
                Trades (newest first · {Math.min(b.trades.length, 100)} of {b.trades_total})
              </h3>
              {Object.entries(b.skipped).some(([, v]) => v > 0) && (
                <span className="text-[11px] text-muted">
                  signals not taken:{" "}
                  {Object.entries(b.skipped).filter(([, v]) => v > 0).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}
                </span>
              )}
            </div>
            <div className="max-h-96 overflow-auto">
              <table className="w-full font-mono text-xs tabular-nums">
                <thead className="sticky top-0 bg-panel text-left text-muted">
                  <tr>
                    {["Entry (UTC)", "Pair", "Side", "Entry", "SL", "TP", "Units", "Risk", "Exit", "Result", "Pips", "P/L", "Balance"].map((h) => (
                      <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.trades.slice(0, 100).map((t, i) => (
                    <tr key={i} className="border-t border-edge">
                      <td className="px-2 py-1 text-muted">{String(t.entry_time).slice(0, 16).replace("T", " ")}</td>
                      <td className="px-2 py-1">{pairName(String(t.instrument))}</td>
                      <td className="px-2 py-1"><Badge tone={t.side === "BUY" ? "ok" : "bad"}>{t.side}</Badge></td>
                      <td className="px-2 py-1">{Number(t.entry).toFixed(digits(t.instrument))}</td>
                      <td className="px-2 py-1">{Number(t.stop_loss).toFixed(digits(t.instrument))}</td>
                      <td className="px-2 py-1">{Number(t.take_profit).toFixed(digits(t.instrument))}</td>
                      <td className="px-2 py-1">{t.units}</td>
                      <td className="px-2 py-1">{fmtUsd(Number(t.risk_amount))}</td>
                      <td className="px-2 py-1">{Number(t.exit).toFixed(digits(t.instrument))}</td>
                      <td className="px-2 py-1 text-muted">{String(t.reason).replace("_", " ")}</td>
                      <td className="px-2 py-1">{Number(t.pips).toFixed(1)}</td>
                      <td className={`px-2 py-1 ${Number(t.pnl) >= 0 ? "text-buy" : "text-sell"}`}>{signed(Number(t.pnl))}</td>
                      <td className="px-2 py-1">{fmtUsd(Number(t.balance_after))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
