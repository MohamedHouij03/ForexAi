"use client";

import { useCallback } from "react";
import { api, type AppConfig } from "@/lib/api";
import { fmtInt, fmtPrice, fmtUsd } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { usePolling } from "@/lib/usePolling";
import { Badge, Panel, Stat } from "@/components/ui";

export function RiskPanel({ config }: { config: AppConfig | null }) {
  const { current } = useInstrument();
  const name = current?.name ?? null;
  const fetcher = useCallback(() => api.riskPreview(name!), [name]);
  const preview = usePolling(name && current!.candles > 0 ? fetcher : null, 60_000);
  const p = preview.data?.instrument === name ? preview.data : null;

  const r = config?.risk;
  const leverage = current?.asset_class === "metal" ? r?.leverage_metal : r?.leverage_forex;
  const digits = current?.display_precision ?? 5;

  return (
    <Panel title="Risk configuration">
      {!r ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="space-y-4">
          <Stat label="Account balance (paper)" value={fmtUsd(r.account_balance)} />
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded border border-accent/30 bg-accent/5 p-3">
              <Stat
                label="Trade allocation"
                value={fmtUsd(r.max_trade_allocation)}
                hint={`${r.max_trade_allocation_percent}% of balance · margin safety cap`}
              />
            </div>
            <div className="rounded border border-sell/30 bg-sell/5 p-3">
              <Stat
                label="Max loss (risk)"
                value={fmtUsd(r.max_risk_amount)}
                hint={`${r.max_risk_percent}% of balance · lost only if stop loss is hit`}
              />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <Stat label="SL" value={`${r.stop_loss_atr_multiplier}×ATR`} />
            <Stat label="TP" value={`${r.take_profit_atr_multiplier}×ATR`} />
            <Stat label="R:R" value={`1:${r.target_risk_reward}`} />
            <Stat label="Leverage" value={leverage ? `${leverage}:1` : "—"} />
          </div>
          <p className="text-[11px] text-muted">
            Account protection: at most {r.max_open_trades} open trade{r.max_open_trades === 1 ? "" : "s"} at a time;
            new trades stop for the day after losing{" "}
            {`${r.max_daily_loss_percent}% (${fmtUsd((r.account_balance * r.max_daily_loss_percent) / 100)})`}.
          </p>

          <div className="rounded border border-edge p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-wider text-muted">
                Sizing example · {current?.display_name ?? "—"}
              </span>
              <Badge tone="neutral">illustration, not a signal</Badge>
            </div>
            {!p ? (
              <p className="text-xs text-muted">{current?.candles === 0 ? "No data for this instrument yet." : "Loading…"}</p>
            ) : !p.tradable ? (
              <p className="text-xs text-wait">
                Not tradable with these limits: {p.reason}. The assistant would answer WAIT.
              </p>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-3 gap-3">
                  <Stat label="Position" value={`${fmtInt(p.units)} ${current?.unit_label ?? ""}`} hint={`value ${fmtUsd(p.position_value)}`} />
                  <Stat label="Margin used" value={fmtUsd(p.margin_required)} hint={`of ${fmtUsd(p.max_allocation)}`} />
                  <Stat label="Loss at SL" value={fmtUsd(p.risk_amount)} hint={`of ${fmtUsd(p.max_risk_amount)} allowed`} />
                </div>
                <p className="text-[11px] text-muted">
                  BUY at {fmtPrice(p.entry, digits)}, SL {fmtPrice(p.stop_loss, digits)} ({p.stop_distance_pips.toFixed(1)} pips = 1.5×ATR),
                  TP {fmtPrice(p.take_profit, digits)} → potential {fmtUsd(p.potential_profit)}.{" "}
                  {p.limited_by === "allocation"
                    ? `Size is capped by the ${fmtUsd(p.max_allocation)} margin allocation, so the loss at SL stays below the ${fmtUsd(p.max_risk_amount)} limit.`
                    : `Size is set by the ${fmtUsd(p.max_risk_amount)} loss limit.`}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
