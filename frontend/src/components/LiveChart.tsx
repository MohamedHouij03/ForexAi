"use client";

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ChartData } from "@/lib/api";
import { useInstrument } from "@/lib/instrument";
import { useLive } from "@/lib/live";

// Theme tokens (globals.css). EMA hues: validated categorical slots 1/4/5 (blue, yellow, magenta) on the
// dark panel surface - they stay clear of the green/red candles and pass the colour-blind checks.
const C = {
  surface: "#111620",
  grid: "#1e2533",
  text: "#8a93a6",
  up: "#22c55e",
  down: "#ef4444",
  entry: "#8a93a6",
  ema20: "#3987e5",
  ema50: "#c98500",
  ema200: "#d55181",
};
const EMAS = [
  { key: "ema20", label: "EMA 20", color: C.ema20 },
  { key: "ema50", label: "EMA 50", color: C.ema50 },
  { key: "ema200", label: "EMA 200", color: C.ema200 },
] as const;
type EmaKey = (typeof EMAS)[number]["key"];
const STEP = 15 * 60;

export function LiveChart() {
  const { current } = useInstrument();
  const live = useLive();
  const name = current?.name ?? null;
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeries = useRef<Partial<Record<EmaKey, ISeriesApi<"Line">>>>({});
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const lastBar = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null);
  const lastClosed = useRef<number>(0);
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Record<EmaKey, boolean>>({ ema20: true, ema50: true, ema200: true });

  // --- create the chart once
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: C.surface }, textColor: C.text, fontSize: 11 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.grid },
      timeScale: { borderColor: C.grid, timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" },
    });
    candles.current = c.addSeries(CandlestickSeries, {
      upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down,
    });
    for (const e of EMAS) {
      emaSeries.current[e.key] = c.addSeries(LineSeries, {
        color: e.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: e.label,
        crosshairMarkerVisible: false,
      });
    }
    markers.current = createSeriesMarkers(candles.current, []);
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      candles.current = null;
      emaSeries.current = {};
      markers.current = null;
      lines.current = [];
    };
  }, []);

  // --- load data (instrument change, every new candle, and every minute as a fallback)
  const signalId = name ? live.signals[name]?.id : undefined;
  const load = useCallback(async () => {
    if (!name) return;
    try {
      setData(await api.chart(name));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [name]);
  useEffect(() => {
    const first = setTimeout(load, 0);
    const id = setInterval(load, 60_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load, signalId, live.version]);

  // --- push data into the series
  useEffect(() => {
    if (!data || data.instrument !== name || !candles.current) return;
    const digits = data.display_precision;
    candles.current.applyOptions({ priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits } });
    candles.current.setData(data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    const last = data.candles[data.candles.length - 1];
    lastBar.current = last ? { ...last } : null;
    lastClosed.current = last?.time ?? 0;
    for (const e of EMAS) {
      emaSeries.current[e.key]?.setData(data[e.key].map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    }

    const ms: SeriesMarker<Time>[] = data.signals.map((s) => ({
      time: s.time as UTCTimestamp,
      position: s.decision === "BUY" ? "belowBar" : "aboveBar",
      shape: s.decision === "BUY" ? "arrowUp" : "arrowDown",
      color: s.decision === "BUY" ? C.up : C.down,
      text: s.decision + (s.outcome_r != null ? ` ${s.outcome_r >= 0 ? "+" : ""}${s.outcome_r.toFixed(1)}R` : ""),
    }));
    for (const t of data.trades) {
      if (t.closed_at && t.pnl != null && t.closed_at >= (data.candles[0]?.time ?? 0)) {
        ms.push({
          time: (Math.floor(t.closed_at / STEP) * STEP) as UTCTimestamp,
          position: "inBar", shape: "circle", color: t.pnl >= 0 ? C.up : C.down,
          text: `closed ${t.pnl >= 0 ? "+" : "-"}$${Math.abs(t.pnl).toFixed(2)}`,
        });
      }
    }
    ms.sort((a, b) => Number(a.time) - Number(b.time));
    markers.current?.setMarkers(ms);

    // price lines: your open trade, or the proposed levels of a signal that can still be taken
    for (const l of lines.current) candles.current.removePriceLine(l);
    lines.current = [];
    const add = (price: number | null, color: string, title: string, style: LineStyle) => {
      if (price == null || !candles.current) return;
      lines.current.push(candles.current.createPriceLine({ price, color, title, lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
    };
    const open = data.trades.find((t) => t.status === "open");
    const pending = [...data.signals].reverse().find((s) => s.status === "actionable");
    if (open) {
      add(open.entry_price, C.entry, `${open.side} entry`, LineStyle.Solid);
      add(open.stop_loss, C.down, "SL", LineStyle.Dashed);
      add(open.take_profit, C.up, "TP", LineStyle.Dashed);
    } else if (pending) {
      add(pending.entry, C.entry, `${pending.decision} signal`, LineStyle.Dotted);
      add(pending.stop_loss, C.down, "signal SL", LineStyle.Dotted);
      add(pending.take_profit, C.up, "signal TP", LineStyle.Dotted);
    }
  }, [data, name]);

  // --- EMA toggles
  useEffect(() => {
    for (const e of EMAS) emaSeries.current[e.key]?.applyOptions({ visible: show[e.key] });
  }, [show]);

  // --- real-time ticks build the candle that is still forming (EUR/USD and gold)
  const tick = name ? live.prices[name] : undefined;
  useEffect(() => {
    if (!tick || tick.source !== "stream" || !candles.current || !lastBar.current) return;
    const t = Math.floor(new Date(tick.time).getTime() / 1000);
    const barTime = Math.floor(t / STEP) * STEP;
    if (barTime <= lastClosed.current) return; // belongs to a candle that is already closed
    const bar = lastBar.current;
    const next = bar.time === barTime
      ? { ...bar, high: Math.max(bar.high, tick.price), low: Math.min(bar.low, tick.price), close: tick.price }
      : { time: barTime, open: bar.close, high: Math.max(bar.close, tick.price), low: Math.min(bar.close, tick.price), close: tick.price };
    lastBar.current = next;
    candles.current.update({ ...next, time: next.time as UTCTimestamp });
  }, [tick]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        {EMAS.map((e) => (
          <button
            key={e.key}
            onClick={() => setShow((s) => ({ ...s, [e.key]: !s[e.key] }))}
            aria-pressed={show[e.key]}
            className={`flex items-center gap-1.5 rounded border px-2 py-1 ${show[e.key] ? "border-edge text-fg" : "border-edge/50 text-muted line-through"}`}
          >
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: e.color }} />
            {e.label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-3 text-muted">
          <span className="flex items-center gap-1"><span style={{ color: C.up }}>▲</span> BUY signal</span>
          <span className="flex items-center gap-1"><span style={{ color: C.down }}>▼</span> SELL signal</span>
          <span className="flex items-center gap-1"><span className="inline-block w-4 border-t border-dashed" style={{ borderColor: C.down }} /> SL</span>
          <span className="flex items-center gap-1"><span className="inline-block w-4 border-t border-dashed" style={{ borderColor: C.up }} /> TP</span>
        </span>
      </div>
      <div ref={box} className="h-[420px] w-full" />
      {error && <p className="mt-2 text-sm text-muted">{error}</p>}
      <p className="mt-2 text-[11px] text-muted">
        15-minute candles, UTC. Markers show every BUY/SELL the coach gave, with its result in R once known.
        {tick?.source === "stream" ? " The last candle updates with live ticks." : " Updates at each candle close."}
      </p>
    </div>
  );
}
