"use client";

import type { ModelSummary, TradeStats } from "@/lib/api";
import { fmtUtc, pairName } from "@/lib/format";
import { useLive } from "@/lib/live";
import { Badge, Panel, Stat } from "@/components/ui";

const NAMES: Record<string, string> = {
  logistic_regression: "Logistic Regression",
  random_forest: "Random Forest",
  xgboost: "XGBoost",
};

function r(v: number | null | undefined): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(3)} R`;
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function tone(v: number | null | undefined) {
  return v == null ? "text-muted" : v > 0 ? "text-buy" : "text-sell";
}

function StatsRow({ label, s, extra }: { label: string; s: TradeStats | null; extra?: string }) {
  return (
    <tr className="border-t border-edge">
      <td className="py-1.5 pr-3 text-muted">{label}</td>
      <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{s?.trades ?? 0}</td>
      <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${tone(s?.expectancy_r)}`}>{r(s?.expectancy_r)}</td>
      <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{pct(s?.win_rate)}</td>
      <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{s?.profit_factor ?? "—"}</td>
      <td className="py-1.5 text-right text-xs text-muted">{extra ?? ""}</td>
    </tr>
  );
}

export function ModelReport({ m }: { m: ModelSummary }) {
  const practice = useLive().coachMode !== "proven";
  const p = m.periods;
  const cm = m.test.classification.confusion_matrix;
  return (
    <div className="space-y-4">
      <Panel
        title="Current model"
        right={
          <Badge tone={m.deployable ? "ok" : "warn"}>
            {m.deployable ? "Proven · signals enabled" : practice ? "Not proven · practice signals" : "Not proven · WAIT only"}
          </Badge>
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            <Stat label="Selected model" value={NAMES[m.model] ?? m.model} mono={false} />
            <Stat label="Version" value={m.version} />
            <Stat label="Trained" value={fmtUtc(m.created_at)} />
            <Stat label="Confidence threshold" value={m.threshold.toFixed(3)} />
            <Stat label="Instruments" value={m.instruments.join(" · ")} mono={false} />
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            <Stat label="Training period" value={`${p.train.start.slice(0, 10)} → ${p.train.end.slice(0, 10)}`} />
            <Stat label="Validation period" value={`${p.validation.start.slice(0, 10)} → ${p.validation.end.slice(0, 10)}`} />
            <Stat label="Test period (untouched)" value={`${p.test.start.slice(0, 10)} → ${p.test.end.slice(0, 10)}`} />
          </div>
          {!m.deployable && (
            <div className="rounded border border-wait/40 bg-wait/5 p-3 text-sm">
              <p className="font-medium text-wait">
                The AI has not proven a reliable edge.{" "}
                {practice
                  ? "In practice mode you still get its signals, labelled \"unproven - demo only\", so you can test it live."
                  : "In proven mode it therefore answers WAIT."}
              </p>
              <ul className="mt-1 list-disc pl-5 text-xs text-muted">
                {m.not_deployable_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">
                Before real money, a model should make money after costs on validation data, on most walk-forward
                periods, on the untouched test period - and in your live track record.
              </p>
            </div>
          )}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Model comparison (results per trade, after spread)">
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr>
                <th className="py-1.5 pr-3 font-normal">Model · data</th>
                <th className="py-1.5 pr-3 text-right font-normal">Trades</th>
                <th className="py-1.5 pr-3 text-right font-normal">Avg result</th>
                <th className="py-1.5 pr-3 text-right font-normal">Win rate</th>
                <th className="py-1.5 pr-3 text-right font-normal">PF</th>
                <th className="py-1.5 text-right font-normal"></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.comparison).map(([name, c]) => (
                <FragmentRows key={name} name={NAMES[name] ?? name} c={c} selected={name === m.model} />
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted">
            1 R = the amount risked on a trade ($1 with your settings). Blind trading loses about −0.08 R per trade
            (the spread), so a useful model must be clearly above 0 on every row.
          </p>
        </Panel>

        <Panel title={`Final test · ${NAMES[m.model] ?? m.model}`}>
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr>
                <th className="py-1.5 pr-3 font-normal">Instrument</th>
                <th className="py-1.5 pr-3 text-right font-normal">Trades</th>
                <th className="py-1.5 pr-3 text-right font-normal">Avg result</th>
                <th className="py-1.5 pr-3 text-right font-normal">Win rate</th>
                <th className="py-1.5 pr-3 text-right font-normal">PF</th>
                <th className="py-1.5 text-right font-normal"></th>
              </tr>
            </thead>
            <tbody>
              <StatsRow label="All" s={m.test} extra={`total ${m.test.total_r?.toFixed(1) ?? "—"} R`} />
              {Object.entries(m.test.by_instrument).map(([inst, s]) => (
                <StatsRow key={inst} label={pairName(inst)} s={s} />
              ))}
            </tbody>
          </table>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Stat label="Log-loss (lower is better)" value={m.test.classification.log_loss.toFixed(4)} hint={`no-skill baseline ${m.test.classification.log_loss_baseline.toFixed(4)}`} />
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted">Confusion (actual ↓ / decided →)</div>
              <table className="mt-1 font-mono text-xs tabular-nums">
                <thead className="text-muted">
                  <tr>
                    <th className="pr-2 font-normal"></th>
                    {cm.labels.map((l) => (
                      <th key={l} className="px-2 text-right font-normal">{l}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cm.matrix.map((row, i) => (
                    <tr key={cm.labels[i]}>
                      <td className="pr-2 text-muted">{cm.labels[i]}</td>
                      {row.map((v, j) => (
                        <td key={j} className={`px-2 text-right ${i === j && i !== 1 ? "text-buy" : ""}`}>{v.toLocaleString()}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="What the model pays attention to (top features)">
        <div className="space-y-1.5">
          {Object.entries(m.feature_importance).slice(0, 12).map(([name, v]) => {
            const max = Math.max(...Object.values(m.feature_importance));
            return (
              <div key={name} className="flex items-center gap-3 text-xs">
                <span className="w-44 shrink-0 truncate font-mono text-muted">{name}</span>
                <div className="h-2 flex-1 rounded bg-edge">
                  <div className="h-2 rounded bg-accent" style={{ width: `${(v / max) * 100}%` }} />
                </div>
                <span className="w-12 text-right font-mono tabular-nums">{(v * 100).toFixed(1)}%</span>
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-[11px] text-muted">
          Time of day and volatility dominate: the models learned <em>when</em> big moves tend to happen (London and
          New York hours) but not reliably <em>which direction</em>, which is what a trade needs.
        </p>
      </Panel>
    </div>
  );
}

function FragmentRows({ name, c, selected }: { name: string; c: ModelSummary["comparison"][string]; selected: boolean }) {
  return (
    <>
      <tr className="border-t border-edge">
        <td className="pt-2 pb-0.5 text-xs font-semibold" colSpan={6}>
          {name} {selected && <Badge tone="neutral">selected</Badge>}
          <span className="ml-2 font-normal text-muted">threshold {c.threshold.toFixed(3)}</span>
        </td>
      </tr>
      <StatsRow label="validation" s={c.validation} />
      <StatsRow
        label="walk-forward"
        s={c.walk_forward}
        extra={c.walk_forward?.positive_fold_share != null ? `${Math.round(c.walk_forward.positive_fold_share * 100)}% periods profitable` : ""}
      />
    </>
  );
}
