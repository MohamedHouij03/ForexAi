"use client";

import { useCallback } from "react";
import { api } from "@/lib/api";
import { fmtCandle, fmtPrice } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { usePolling } from "@/lib/usePolling";
import { Badge, Panel, Stat, type Tone } from "@/components/ui";

const TREND_TONE: Record<string, Tone> = { Uptrend: "ok", Downtrend: "bad" };
const VOL_TONE: Record<string, Tone> = { High: "warn", Low: "neutral", Normal: "ok" };

function rsiHint(v: number | null): string {
  if (v == null) return "";
  if (v >= 70) return "overbought zone";
  if (v <= 30) return "oversold zone";
  return "neutral zone";
}

export function IndicatorsPanel() {
  const { current } = useInstrument();
  const name = current?.name ?? null;
  const fetcher = useCallback(() => api.indicators(name!), [name]);
  const res = usePolling(name && current!.candles > 0 ? fetcher : null, 60_000);
  const d = res.data?.instrument === name ? res.data : null;
  const digits = d?.display_precision ?? current?.display_precision ?? 5;
  const macdDigits = digits + 1;

  return (
    <Panel
      title="Indicators"
      right={<span className="text-[11px] text-muted">{d ? `as of ${fmtCandle(d.time)}` : ""}</span>}
    >
      {!d ? (
        <p className="text-sm text-muted">
          {current?.candles === 0 ? "No data for this instrument yet." : res.error ?? "Loading…"}
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted">Trend</span>
            <Badge tone={TREND_TONE[d.trend] ?? "neutral"}>{d.trend}</Badge>
            <span className="ml-3 text-muted">Volatility</span>
            <Badge tone={VOL_TONE[d.volatility] ?? "neutral"}>{d.volatility}</Badge>
            <span className="ml-3 text-muted">Session</span>
            <Badge tone="neutral">{d.session}</Badge>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="RSI (14)" value={d.rsi_14?.toFixed(1) ?? "—"} hint={rsiHint(d.rsi_14)} />
            <Stat
              label="MACD hist"
              value={d.macd_hist?.toFixed(macdDigits) ?? "—"}
              hint={d.macd_hist == null ? "" : d.macd_hist >= 0 ? "momentum up" : "momentum down"}
            />
            <Stat label="ATR (14)" value={d.atr_pips != null ? `${d.atr_pips.toFixed(1)} pips` : "—"} hint="typical 15m range" />
            <Stat
              label="ATR vs normal"
              value={d.atr_ratio_100 != null ? `${d.atr_ratio_100.toFixed(2)}×` : "—"}
              hint="vs 100-candle average"
            />
            <Stat label="EMA 20" value={fmtPrice(d.ema20, digits)} />
            <Stat label="EMA 50" value={fmtPrice(d.ema50, digits)} />
            <Stat label="EMA 200" value={fmtPrice(d.ema200, digits)} />
            <Stat label="Price" value={fmtPrice(d.close, digits)} hint={d.ema200 != null && d.close != null ? (d.close > d.ema200 ? "above EMA 200" : "below EMA 200") : ""} />
          </div>
          <p className="text-[11px] text-muted">
            MACD {d.macd?.toFixed(macdDigits)} / signal {d.macd_signal?.toFixed(macdDigits)} · Bollinger{" "}
            {fmtPrice(d.bb_lower, digits)} – {fmtPrice(d.bb_upper, digits)}. Computed by the same code the AI learns from,
            using closed candles only.
          </p>
        </div>
      )}
    </Panel>
  );
}
