"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtCandle, fmtInt, fmtPrice, fmtUtc, isMarketOpen } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { usePolling } from "@/lib/usePolling";
import { IndicatorsPanel } from "@/components/IndicatorsPanel";
import { LiveChart } from "@/components/LiveChart";
import { OpenTradesPanel } from "@/components/OpenTradesPanel";
import { OpportunityBar } from "@/components/OpportunityBar";
import { TrackRecordPanel } from "@/components/TrackRecordPanel";
import { useLive } from "@/lib/live";
import { RiskPanel } from "@/components/RiskPanel";
import { SignalCard } from "@/components/SignalCard";
import { SystemStatus } from "@/components/SystemStatus";
import { Badge, Panel, Stat } from "@/components/ui";

export default function LiveAssistantPage() {
  const { current, error: instrumentsError } = useInstrument();
  const live = useLive();
  const name = current?.name ?? null;
  const digits = current?.display_precision ?? 5;
  const assetClass = current?.asset_class ?? "forex";

  const health = usePolling(api.health, 15_000);
  const config = usePolling(api.config, 60_000);
  const summaryFetcher = useCallback(() => api.dataSummary(name!), [name]);
  const candlesFetcher = useCallback(() => api.candles(name!, 20), [name]);
  const summary = usePolling(name ? summaryFetcher : null, 15_000);
  const candles = usePolling(name ? candlesFetcher : null, 15_000);

  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  useEffect(() => {
    const tick = () => setMarketOpen(isMarketOpen(assetClass));
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [assetClass]);

  // Ignore responses that belong to a previously selected instrument.
  const rows = candles.data?.instrument === name ? candles.data.candles : [];
  const summaryData = summary.data?.instrument === name ? summary.data : null;
  const last = rows.at(-1);
  const livePrice = name ? live.prices[name] : undefined;
  const streaming = livePrice?.source === "stream";
  const noBidAsk = last != null && last.bid_close == null;
  const naHint = noBidAsk ? "not provided by data source" : undefined;

  return (
    <div className="space-y-4">
      <OpportunityBar />
      {/* Market header */}
      <section className="rounded-lg border border-edge bg-panel px-4 py-3">
        <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <div className="text-2xl font-semibold tracking-tight">{current?.display_name ?? "—"}</div>
            <div className="text-[11px] text-muted">{current?.description ?? ""}</div>
          </div>
          <Stat label="Bid" value={fmtPrice(last?.bid_close, digits)} hint={naHint} />
          <Stat label="Ask" value={fmtPrice(last?.ask_close, digits)} hint={naHint} />
          <Stat label="Spread" value={last?.spread_pips != null ? `${last.spread_pips.toFixed(1)} pips` : "—"} hint={naHint} />
          <Stat
            label={streaming ? "Price (live)" : "Price (mid)"}
            value={fmtPrice(livePrice?.price ?? last?.close, digits)}
            hint={streaming ? `tick ${fmtUtc(livePrice?.time).slice(11, 16)} UTC` : "last candle close"}
          />
          <Stat
            label="Market"
            mono={false}
            value={marketOpen == null ? "—" : <Badge tone={marketOpen ? "ok" : "neutral"}>{marketOpen ? "Open" : "Closed"}</Badge>}
          />
          <Stat label="Last candle" value={fmtCandle(last?.time)} hint="close time of the latest finished 15m candle" />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Panel title={`Chart · ${current?.display_name ?? ""} 15m`}>
            <LiveChart />
          </Panel>

          <Panel title="Recent candles (UTC)" right={<span className="text-[11px] text-muted">{candles.updatedAt ? `updated ${candles.updatedAt.toLocaleTimeString()}` : ""}</span>}>
            {rows.length === 0 ? (
              <p className="text-sm text-muted">
                {instrumentsError ?? candles.error ?? "No candles stored yet for this instrument. Run the downloader (see README)."}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full font-mono text-xs tabular-nums">
                  <thead className="text-left text-muted">
                    <tr>
                      {["Closed", "Open", "High", "Low", "Close", "Bid", "Ask", "Spread", "Ticks"].map((h) => (
                        <th key={h} className="px-2 py-1.5 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...rows].reverse().slice(0, 12).map((c) => (
                      <tr key={c.time} className="border-t border-edge">
                        <td className="px-2 py-1.5 text-muted">{fmtCandle(c.time).replace(" UTC", "")}</td>
                        <td className="px-2 py-1.5">{fmtPrice(c.open, digits)}</td>
                        <td className="px-2 py-1.5">{fmtPrice(c.high, digits)}</td>
                        <td className="px-2 py-1.5">{fmtPrice(c.low, digits)}</td>
                        <td className={`px-2 py-1.5 ${c.close >= c.open ? "text-buy" : "text-sell"}`}>{fmtPrice(c.close, digits)}</td>
                        <td className="px-2 py-1.5">{fmtPrice(c.bid_close, digits)}</td>
                        <td className="px-2 py-1.5">{fmtPrice(c.ask_close, digits)}</td>
                        <td className="px-2 py-1.5">{c.spread_pips?.toFixed(1) ?? "—"}</td>
                        <td className="px-2 py-1.5 text-muted">{fmtInt(c.volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <IndicatorsPanel />
        </div>

        <div className="space-y-4">
          <SignalCard />
          <OpenTradesPanel />
          <RiskPanel config={config.data} />
          <SystemStatus health={health.data} summary={summaryData} error={health.error} />
        </div>
      </div>
      <TrackRecordPanel />
    </div>
  );
}
