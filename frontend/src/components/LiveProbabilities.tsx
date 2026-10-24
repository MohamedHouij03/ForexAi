"use client";

import { fmtCandle } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { useLive } from "@/lib/live";
import { Badge } from "@/components/ui";

function pct(v: number | null | undefined) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

/** The AI's latest P(BUY) / P(WAIT) / P(SELL) for every watched pair (updates at each candle close). */
export function LiveProbabilities() {
  const { instruments, select } = useInstrument();
  const { signals } = useLive();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
          <tr>
            {["Pair", "Candle (UTC)", "P(BUY)", "P(WAIT)", "P(SELL)", "Decision", "Why"].map((h) => (
              <th key={h} className="py-1.5 pr-3 font-normal">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {instruments.map((i) => {
            const s = signals[i.name];
            return (
              <tr key={i.name} className="cursor-pointer border-t border-edge hover:bg-edge/40" onClick={() => select(i.name)}>
                <td className="py-1.5 pr-3 font-mono font-semibold">{i.display_name}</td>
                <td className="py-1.5 pr-3 font-mono text-xs text-muted">{s ? fmtCandle(s.candle_time).slice(11, 16) : "—"}</td>
                <td className="py-1.5 pr-3 font-mono tabular-nums">{pct(s?.p_buy)}</td>
                <td className="py-1.5 pr-3 font-mono tabular-nums">{pct(s?.p_wait)}</td>
                <td className="py-1.5 pr-3 font-mono tabular-nums">{pct(s?.p_sell)}</td>
                <td className="py-1.5 pr-3">
                  {s ? <Badge tone={s.decision === "BUY" ? "ok" : s.decision === "SELL" ? "bad" : "neutral"}>{s.decision}</Badge> : "—"}
                </td>
                <td className="py-1.5 text-xs text-muted">{s?.reason ?? "no decision yet"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-muted">
        Chance that a trade opened now reaches its target before its stop, within the maximum holding time. P(WAIT) is
        the chance that neither happens. A signal needs one side above the threshold and ahead of the other side.
      </p>
    </div>
  );
}
