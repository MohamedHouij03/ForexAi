import type { DataSummary, Health } from "@/lib/api";
import { fmtInt, fmtUtc } from "@/lib/format";
import { Badge, Dot, ErrorNote, Panel, type Tone } from "@/components/ui";

export const VALIDATION_TONE: Record<string, Tone> = { PASS: "ok", WARN: "warn", FAIL: "bad" };

function Row({ tone, label, value }: { tone: Tone; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <span className="flex items-center gap-2 text-muted">
        <Dot tone={tone} /> {label}
      </span>
      <span className="truncate text-right">{value}</span>
    </div>
  );
}

export function SystemStatus({ health, summary, error }: {
  health: Health | null;
  summary: DataSummary | null;
  error: string | null;
}) {
  return (
    <Panel title="System & data pipeline">
      {error && !health ? (
        <ErrorNote message={`${error}. Start the backend (see README).`} />
      ) : (
        <div className="divide-y divide-edge">
          <Row tone={health ? "ok" : "neutral"} label="Backend API" value={health ? health.status : "…"} />
          <Row
            tone={health ? (health.database.ok ? "ok" : "bad") : "neutral"}
            label="Database"
            value={health ? (health.database.ok ? "connected" : "unreachable") : "…"}
          />
          <Row
            tone={health ? (health.data_provider.configured ? "ok" : "warn") : "neutral"}
            label="Data provider"
            value={health ? `${health.data_provider.name} · ${health.data_provider.configured ? "API key set" : "no API key"}` : "…"}
          />
          <Row
            tone={summary ? (summary.candles > 0 ? "ok" : "warn") : "neutral"}
            label={`Stored candles${summary ? ` (${summary.instrument} ${summary.granularity})` : ""}`}
            value={summary ? fmtInt(summary.candles) : "…"}
          />
          <Row tone="neutral" label="History range" value={summary?.first_time ? `${fmtUtc(summary.first_time)} → ${fmtUtc(summary.last_time)}` : "—"} />
          <div className="flex items-center justify-between py-1.5 text-sm">
            <span className="text-muted">Dataset validation</span>
            {summary?.last_validation_status ? (
              <Badge tone={VALIDATION_TONE[summary.last_validation_status]}>{summary.last_validation_status}</Badge>
            ) : (
              <span>not run yet</span>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
