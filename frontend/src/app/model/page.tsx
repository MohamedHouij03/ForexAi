"use client";

import { useCallback, useState } from "react";
import { api, type ValidationReport } from "@/lib/api";
import { useInstrument } from "@/lib/instrument";
import { usePolling } from "@/lib/usePolling";
import { BacktestPanel } from "@/components/BacktestPanel";
import { LiveProbabilities } from "@/components/LiveProbabilities";
import { ModelReport } from "@/components/ModelReport";
import { ValidationReportView } from "@/components/ValidationReportView";
import { ErrorNote, Panel, Planned } from "@/components/ui";

export default function ModelPage() {
  const { current } = useInstrument();
  const name = current?.name ?? null;
  const fetcher = useCallback(() => api.validation(name!), [name]);
  const saved = usePolling(name ? fetcher : null, 60_000);
  const model = usePolling(api.model, 60_000);
  const [fresh, setFresh] = useState<ValidationReport | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Only show reports for the selected instrument (the selection can change while a request is in flight).
  const report = [fresh, saved.data].find((r) => r?.instrument === name) ?? null;

  async function rerun() {
    if (!name) return;
    setRunning(true);
    setRunError(null);
    try {
      setFresh(await api.runValidation(name));
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-4">
      {model.data ? (
        <ModelReport m={model.data} />
      ) : (
        <Panel title="Current model">
          <Planned phase="Phases 5–7">
            {model.error ?? "Loading…"} Train with scripts	rain.cmd: Logistic Regression, Random Forest and XGBoost
            are compared on data they never saw.
          </Planned>
        </Panel>
      )}
      <div className="grid gap-4">
        <Panel title="Current probabilities">
          <LiveProbabilities />
        </Panel>
      </div>
      <BacktestPanel />

      <Panel
        title={`Dataset validation · ${current?.display_name ?? ""} 15m`}
        right={
          <button
            onClick={rerun}
            disabled={running}
            className="rounded border border-edge px-3 py-1 text-xs text-fg hover:bg-edge disabled:opacity-50"
          >
            {running ? "Validating…" : "Re-run validation"}
          </button>
        }
      >
        {runError && <div className="mb-3"><ErrorNote message={runError} /></div>}
        {report ? (
          <ValidationReportView report={report} />
        ) : current && current.candles === 0 ? (
          <p className="text-sm text-muted">No data downloaded for {current.display_name} yet.</p>
        ) : saved.error ? (
          <p className="text-sm text-muted">{saved.error}</p>
        ) : (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </Panel>
    </div>
  );
}
