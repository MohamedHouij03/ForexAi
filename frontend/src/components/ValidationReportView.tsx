import type { ValidationCheck, ValidationReport } from "@/lib/api";
import { fmtInt, fmtUtc } from "@/lib/format";
import { Badge, Stat, type Tone } from "@/components/ui";
import { VALIDATION_TONE } from "@/components/SystemStatus";

function checkTone(c: ValidationCheck): Tone {
  if (c.passed) return "ok";
  return c.severity === "error" ? "bad" : c.severity === "warning" ? "warn" : "neutral";
}

function checkLabel(c: ValidationCheck): string {
  if (c.passed) return "OK";
  return { error: "FAIL", warning: "WARN", info: "INFO" }[c.severity];
}

export function ValidationReportView({ report }: { report: ValidationReport }) {
  const cov = report.coverage;
  const s = report.spread_pips;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <Stat label="Status" mono={false} value={<Badge tone={VALIDATION_TONE[report.status]}>{report.status}</Badge>} />
        <Stat label="Candles" value={fmtInt(report.rows)} />
        <Stat label="Range" value={`${fmtUtc(report.first_time)} → ${fmtUtc(report.last_time)}`} />
        {cov && <Stat label="Coverage" value={`${cov.coverage_pct.toFixed(3)}%`} hint={`${fmtInt(cov.missing_excluding_holidays)} missing · ${fmtInt(cov.holiday_missing)} holiday`} />}
        {s?.median != null ? (
          <Stat label="Spread (pips)" value={`${s.median.toFixed(2)} median`} hint={`p95 ${s.p95?.toFixed(2)} · max ${s.max?.toFixed(1)}`} />
        ) : (
          <Stat label="Fields" mono={false} value="Mid OHLC only" hint="no bid/ask or volume from source" />
        )}
        {report.cleaning && (
          <Stat
            label="Cleaning"
            value={`${fmtInt(report.cleaning.rows_removed)} removed`}
            hint={Object.entries(report.cleaning.removed_by_reason).map(([k, v]) => `${k.replace(/_/g, " ")}: ${fmtInt(v)}`).join(" · ") || "nothing removed"}
          />
        )}
        <Stat label="Checked" value={fmtUtc(report.generated_at)} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
            <tr>
              <th className="py-1.5 pr-3 font-normal">Result</th>
              <th className="py-1.5 pr-3 font-normal">Check</th>
              <th className="py-1.5 pr-3 text-right font-normal">Count</th>
              <th className="py-1.5 font-normal">Details</th>
            </tr>
          </thead>
          <tbody>
            {report.checks.map((c) => (
              <tr key={c.name} className="border-t border-edge align-top">
                <td className="py-1.5 pr-3"><Badge tone={checkTone(c)}>{checkLabel(c)}</Badge></td>
                <td className="py-1.5 pr-3 font-mono text-xs">{c.name}</td>
                <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{fmtInt(c.count)}</td>
                <td className="py-1.5 text-xs text-muted">
                  {c.message}
                  {!c.passed && c.examples.length > 0 && (
                    <div className="mt-0.5 font-mono text-[11px]">e.g. {c.examples.slice(0, 2).join(" · ")}</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-[11px] uppercase tracking-wider text-muted">Largest gaps during market hours</h3>
          {report.gaps.largest?.length ? (
            <table className="w-full font-mono text-xs tabular-nums">
              <tbody>
                {report.gaps.largest.slice(0, 10).map((g) => (
                  <tr key={g.start} className="border-t border-edge">
                    <td className="py-1 pr-2">{fmtUtc(g.start)}</td>
                    <td className="py-1 pr-2 text-right">{g.missing_candles}</td>
                    <td className="py-1 text-muted">{g.category}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-muted">No gaps.</p>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-[11px] uppercase tracking-wider text-muted">Coverage by year</h3>
          <table className="w-full font-mono text-xs tabular-nums">
            <tbody>
              {report.coverage_by_year.map((y) => (
                <tr key={y.year} className="border-t border-edge">
                  <td className="py-1 pr-2">{y.year}</td>
                  <td className="py-1 pr-2 text-right">{fmtInt(y.present)}</td>
                  <td className="py-1 pr-2 text-right text-muted">{fmtInt(y.missing)} missing</td>
                  <td className="py-1 text-right">{y.coverage_pct.toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
