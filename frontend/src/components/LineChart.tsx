"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type Point = { t: string; v: number };

type Props = {
  points: Point[];
  label: string; // series name for the tooltip
  format: (v: number) => string;
  height?: number;
  reference?: { value: number; label: string }; // e.g. the starting balance
  area?: boolean; // wash between the line and the reference/zero
};

const PAD = { top: 12, right: 64, bottom: 24, left: 56 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/** Single-series line chart: 2px line, hairline grid, crosshair + tooltip that snaps to the nearest point. */
export function LineChart({ points, label, format, height = 200, reference, area = false }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => {
    const times = points.map((p) => new Date(p.t).getTime());
    const values = points.map((p) => p.v);
    const refVal = reference?.value ?? (area ? 0 : undefined);
    const lo = Math.min(...values, refVal ?? Infinity);
    const hi = Math.max(...values, refVal ?? -Infinity);
    const padY = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
    const y0 = lo - padY;
    const y1 = hi + padY;
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const iw = width - PAD.left - PAD.right;
    const ih = height - PAD.top - PAD.bottom;
    const x = (t: number) => PAD.left + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
    const y = (v: number) => PAD.top + (1 - (v - y0) / (y1 - y0)) * ih;
    const xs = times.map(x);
    const ys = values.map(y);
    const line = xs.map((px, i) => `${i ? "L" : "M"}${px.toFixed(1)},${ys[i].toFixed(1)}`).join("");
    const base = y(refVal ?? y0);
    const fill = area && xs.length ? `${line}L${xs[xs.length - 1].toFixed(1)},${base}L${xs[0].toFixed(1)},${base}Z` : "";
    const yTicks = niceTicks(y0, y1).filter((v) => v >= y0 && v <= y1);
    const xTicks = [0, 0.33, 0.66, 1].map((f) => t0 + (t1 - t0) * f);
    return { xs, ys, line, fill, yTicks, xTicks, x, y, refY: refVal != null ? y(refVal) : null };
  }, [points, width, height, reference, area]);

  if (points.length === 0) return <p className="text-sm text-muted">No data.</p>;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - box.left;
    let best = 0;
    for (let i = 1; i < geo.xs.length; i++) if (Math.abs(geo.xs[i] - px) < Math.abs(geo.xs[best] - px)) best = i;
    setHover(best);
  }

  const last = points.length - 1;
  const h = hover != null ? points[hover] : null;
  return (
    <div ref={wrap} className="relative w-full">
      <svg
        width={width}
        height={height}
        className="block touch-none select-none"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        role="img"
        aria-label={`${label} chart`}
      >
        {geo.yTicks.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={width - PAD.right} y1={geo.y(v)} y2={geo.y(v)} stroke="var(--color-edge)" strokeWidth={1} />
            <text x={PAD.left - 8} y={geo.y(v)} dy="0.32em" textAnchor="end" className="fill-muted text-[10px]">
              {format(v)}
            </text>
          </g>
        ))}
        {geo.xTicks.map((t, i) => (
          <text key={i} x={geo.x(t)} y={height - 6} textAnchor={i === 0 ? "start" : i === 3 ? "end" : "middle"}
            className="fill-muted text-[10px]">
            {new Date(t).toISOString().slice(0, 10)}
          </text>
        ))}
        {reference && geo.refY != null && (
          <g>
            <line x1={PAD.left} x2={width - PAD.right} y1={geo.refY} y2={geo.refY} stroke="var(--color-muted)" strokeWidth={1} opacity={0.6} />
            <text x={width - PAD.right + 6} y={geo.refY} dy="0.32em" className="fill-muted text-[10px]">
              {reference.label}
            </text>
          </g>
        )}
        {geo.fill && <path d={geo.fill} fill="var(--color-accent)" opacity={0.1} />}
        <path d={geo.line} fill="none" stroke="var(--color-accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {/* end value, directly labelled */}
        <circle cx={geo.xs[last]} cy={geo.ys[last]} r={4} fill="var(--color-accent)" stroke="var(--color-panel)" strokeWidth={2} />
        <text x={geo.xs[last] + 8} y={geo.ys[last]} dy="0.32em" className="fill-fg text-[11px] font-medium">
          {format(points[last].v)}
        </text>
        {hover != null && (
          <g>
            <line x1={geo.xs[hover]} x2={geo.xs[hover]} y1={PAD.top} y2={height - PAD.bottom} stroke="var(--color-muted)" strokeWidth={1} />
            <circle cx={geo.xs[hover]} cy={geo.ys[hover]} r={4} fill="var(--color-accent)" stroke="var(--color-panel)" strokeWidth={2} />
          </g>
        )}
      </svg>
      {h && hover != null && (
        <div
          className="pointer-events-none absolute top-1 rounded border border-edge bg-bg/95 px-2 py-1 text-xs shadow"
          style={{ left: Math.min(Math.max(geo.xs[hover] + 10, 0), width - 170) }}
        >
          <div className="font-mono text-sm font-semibold text-fg">{format(h.v)}</div>
          <div className="flex items-center gap-1.5 text-muted">
            <span className="inline-block h-0.5 w-3 bg-accent" />
            {label} · {new Date(h.t).toISOString().slice(0, 16).replace("T", " ")} UTC
          </div>
        </div>
      )}
    </div>
  );
}
