"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type SignalRow } from "@/lib/api";
import { fmtCandle, fmtLots, fmtPrice, fmtUsd, fmtUtc, maxEntry, pairName } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { useLive } from "@/lib/live";
import { usePolling } from "@/lib/usePolling";
import { Dialog, Field, buttonClass, inputClass } from "@/components/Dialog";
import { Badge } from "@/components/ui";

const STYLE = {
  BUY: { box: "border-buy/60 bg-buy/5", text: "text-buy" },
  SELL: { box: "border-sell/60 bg-sell/5", text: "text-sell" },
  WAIT: { box: "border-wait/50 bg-wait/5", text: "text-wait" },
} as const;

function useCountdown(until: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [until]);
  if (!until) return null;
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return "expired";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function pct(v: number | null | undefined) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-edge py-1.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className={`font-mono tabular-nums ${strong ? "text-base font-semibold" : ""}`}>{value}</span>
    </div>
  );
}

/** The coach's current call for the selected instrument, with "I took this trade" / "Skip". */
export function SignalCard() {
  const { current } = useInstrument();
  const live = useLive();
  const name = current?.name ?? null;
  const fetcher = useCallback(() => api.latestSignal(name!), [name]);
  const polled = usePolling(name ? fetcher : null, 60_000);
  const model = usePolling(api.model, 300_000).data;

  // newest of: pushed over the WebSocket, or fetched
  const pushed = name ? live.signals[name] : undefined;
  const fetched = polled.data?.instrument === name ? polled.data : null;
  const sig: SignalRow | null = pushed && (!fetched || pushed.id >= fetched.id) ? pushed : fetched;

  // the signal being confirmed is frozen when the dialog opens, so a new alert that switches the screen
  // to another pair can never change which trade gets recorded
  const [takingSig, setTakingSig] = useState<SignalRow | null>(null);
  const taking = takingSig != null;
  const [fill, setFill] = useState("");
  const [units, setUnits] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const countdown = useCountdown(sig?.status === "actionable" ? sig.expires_at : null);

  const digits = current?.display_precision ?? 5;
  const called = sig?.decision ?? "WAIT";
  const limit = sig ? maxEntry(called, sig.entry, sig.stop_loss) : null;
  const nowPrice = name ? live.prices[name]?.price : undefined;
  const tooLate = limit != null && nowPrice != null && (called === "BUY" ? nowPrice > limit : nowPrice < limit);
  // a BUY/SELL that expired, was skipped, taken or is too late disappears: the card goes back to WAIT
  const live_ = sig?.status === "actionable" && countdown !== "expired" && !tooLate;
  const gone = called !== "WAIT" && !live_;
  const decision = gone ? "WAIT" : called;
  const style = STYLE[decision];
  const actionable = !gone && decision !== "WAIT";
  const confidence = sig ? (decision === "BUY" ? sig.p_buy : decision === "SELL" ? sig.p_sell : null) : null;
  const metal = current?.asset_class === "metal";
  const lots = fmtLots(sig?.units, metal);
  const goneText = !sig || !gone ? null
    : sig.status === "taken" ? `You took this ${called} - follow it in Open trades.`
    : tooLate || sig.reason?.startsWith("Too late")
      ? `The ${called} signal was removed: too late, price already moved past ${fmtPrice(limit, digits)}.`
    : sig.status === "skipped" ? `You skipped the ${called} signal.`
    : `The ${called} signal expired. Waiting for the next opportunity.`;
  const takingLimit = takingSig ? maxEntry(takingSig.decision, takingSig.entry, takingSig.stop_loss) : null;
  const fillTooLate = takingLimit != null && fill !== "" &&
    (takingSig?.decision === "BUY" ? Number(fill) > takingLimit : Number(fill) < takingLimit);

  function openTake() {
    if (!sig) return;
    setFill(sig.entry?.toFixed(digits) ?? "");
    setUnits(String(sig.units ?? ""));
    setError(null);
    setTakingSig(sig);
  }

  async function submitTake() {
    if (!takingSig) return;
    setBusy(true);
    setError(null);
    try {
      await api.takeSignal(takingSig.id, Number(fill), units ? Number(units) : undefined);
      setTakingSig(null);
      live.refresh();
      polled.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function skip() {
    if (!sig) return;
    await api.skipSignal(sig.id).catch(() => {});
    polled.refresh();
  }

  return (
    <section className={`rounded-lg border-2 p-5 ${style.box}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm text-muted">{current?.display_name ?? "—"}</span>
        <div className="flex gap-1.5">
          {sig?.mode === "practice" && decision !== "WAIT" && <Badge tone="warn">Practice · unproven</Badge>}
          <Badge tone="neutral">15m signal</Badge>
        </div>
      </div>
      <div className={`mt-3 text-5xl font-bold tracking-tight ${style.text}`}>{decision}</div>

      {!sig ? (
        <p className="mt-2 text-sm text-muted">
          No signal yet. The coach decides at every 15-minute candle close while the live engine runs.
        </p>
      ) : gone ? (
        <>
          <p className="mt-2 text-sm text-fg">{goneText}</p>
          <p className="mt-1 text-xs text-muted">Last signal: candle closed {fmtCandle(sig.candle_time)}</p>
        </>
      ) : decision === "WAIT" ? (
        <>
          <p className="mt-2 text-sm text-fg">{sig.reason ?? "No high-confidence trading opportunity detected."}</p>
          <p className="mt-1 text-xs text-muted">
            Candle closed {fmtCandle(sig.candle_time)} · P(BUY) {pct(sig.p_buy)} · P(WAIT) {pct(sig.p_wait)} · P(SELL) {pct(sig.p_sell)}
          </p>
        </>
      ) : (
        <>
          <div className="mt-3">
            <Row label="Entry" value={fmtPrice(sig.entry, digits)} strong />
            <Row label="Stop loss" value={fmtPrice(sig.stop_loss, digits)} />
            <Row label="Take profit" value={fmtPrice(sig.take_profit, digits)} />
            <Row label="Volume in your broker" value={`${lots} lot`} strong />
            <Row label="Position size" value={`${sig.units?.toLocaleString() ?? "—"} ${current?.unit_label ?? "units"}`} />
            <Row label={decision === "BUY" ? "Too late if price is above" : "Too late if price is below"}
              value={fmtPrice(limit, digits)} />
            <Row label="Trade allocation (margin)" value={fmtUsd(sig.margin_required)} />
            <Row label="Maximum estimated loss" value={fmtUsd(sig.risk_amount)} />
            <Row label="Potential estimated profit" value={fmtUsd(sig.potential_profit)} />
            <Row label="Risk / reward" value={`1:${sig.risk_reward}`} />
            <Row label="AI confidence" value={pct(confidence)} />
            <Row label="Signal generated" value={`${fmtUtc(sig.created_at)} · 15m`} />
          </div>
          {sig.mode === "practice" && (
            <p className="mt-3 rounded border border-wait/40 bg-wait/10 p-2 text-xs text-wait">
              PRACTICE signal: this model has NOT shown an edge in testing
              {model?.test.expectancy_r != null ? ` (test: ${model.test.expectancy_r.toFixed(2)} R per trade)` : ""}.
              Use your demo account only. Nothing here is a guarantee.
            </p>
          )}
          {sig.status === "actionable" ? (
            <div className="mt-3 space-y-2">
              <p className="text-xs text-muted">
                In your broker: <span className="text-fg">{decision} {lots} lot</span>, stop loss{" "}
                <span className="font-mono text-fg">{fmtPrice(sig.stop_loss, digits)}</span>, take profit{" "}
                <span className="font-mono text-fg">{fmtPrice(sig.take_profit, digits)}</span>. Check the price first:
                if it is already {decision === "BUY" ? "above" : "below"}{" "}
                <span className="font-mono text-fg">{fmtPrice(limit, digits)}</span>, skip it. Valid for{" "}
                <span className="font-mono text-fg">{countdown}</span>.
              </p>
              {tooLate && (
                <p className="rounded border border-sell/50 bg-sell/10 p-2 text-xs text-sell">
                  Too late: price is now {fmtPrice(nowPrice, digits)} - the move already happened. Skip this one.
                </p>
              )}
              <div className="flex gap-2">
                <button className={buttonClass.primary} disabled={!actionable} onClick={openTake}>
                  I took this trade
                </button>
                <button className={buttonClass.secondary} onClick={skip}>Skip</button>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted">Signal {sig.status}.</p>
          )}
        </>
      )}

      <Dialog open={taking} title={`I took ${takingSig?.decision ?? ""} ${pairName(takingSig?.instrument)}`}
        onClose={() => setTakingSig(null)}>
        <div className="space-y-3">
          <Field label="Price you got" hint="The open price your broker shows. Stop loss and take profit stay exactly as on the signal.">
            <input className={inputClass} value={fill} onChange={(e) => setFill(e.target.value)} inputMode="decimal" autoFocus />
          </Field>
          <Field label="Units you traded" hint={`Suggested ${takingSig?.units?.toLocaleString() ?? "—"} units (${fmtUsd(takingSig?.risk_amount)} at risk).`}>
            <input className={inputClass} value={units} onChange={(e) => setUnits(e.target.value)} inputMode="numeric" />
          </Field>
          {fillTooLate && (
            <p className="text-sm text-wait">
              That price is past {fmtPrice(takingLimit, digits)} - the trade started late, so it has less room to
              reach the target.
            </p>
          )}
          {error && <p className="text-sm text-sell">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button className={buttonClass.secondary} onClick={() => setTakingSig(null)}>Cancel</button>
            <button className={buttonClass.primary} disabled={busy || !fill} onClick={submitTake}>
              {busy ? "Saving…" : "Confirm"}
            </button>
          </div>
        </div>
      </Dialog>
    </section>
  );
}
