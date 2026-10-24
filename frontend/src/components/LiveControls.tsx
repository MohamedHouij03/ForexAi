"use client";

import { pairName } from "@/lib/format";
import { useLive } from "@/lib/live";
import { Dot } from "@/components/ui";

/** Header: live-engine status and the button that enables sound + desktop notifications. */
export function LiveControls() {
  const live = useLive();
  const running = live.status?.running;
  const tone = !live.connected ? "bad" : running ? "ok" : "warn";
  const label = !live.connected ? "Offline" : running ? "Live" : "Engine off";
  const title = !live.connected
    ? "Not connected to the backend"
    : live.status?.message ?? "";
  return (
    <div className="flex items-center gap-3">
      <span className="flex items-center gap-1.5 text-xs text-muted" title={title}>
        <Dot tone={tone} /> {label}
        {live.status?.stream_connected && live.status.stream_symbols.length > 0 && (
          <span className="hidden sm:inline">· ticks: {live.status.stream_symbols.map((s) => pairName(s)).join(", ")}</span>
        )}
      </span>
      <button
        onClick={live.enableNotifications}
        className={`rounded border px-2.5 py-1 text-xs ${live.notificationsOn ? "border-buy/40 text-buy" : "border-wait/50 text-wait hover:bg-wait/10"}`}
        title="Sound and desktop notification for every BUY/SELL and every close advice"
      >
        {live.notificationsOn ? "🔔 Alerts on" : "🔕 Enable alerts"}
      </button>
      {live.notificationsOn && (
        <button onClick={live.testAlert} className="rounded border border-edge px-2.5 py-1 text-xs text-muted hover:text-fg"
          title="Play the alert sound and show a notification to check that everything works">
          Test alert
        </button>
      )}
    </div>
  );
}

export function Toaster() {
  const { toasts, dismissToast, openToast } = useLive();
  const tone = { buy: "border-buy bg-buy/15", sell: "border-sell bg-sell/15", wait: "border-wait bg-wait/15", info: "border-edge bg-panel" };
  return (
    <div className="fixed right-4 bottom-4 z-40 flex w-80 flex-col gap-2" aria-live="assertive">
      {toasts.map((t) => (
        <div key={t.id} className={`rounded-lg border-2 p-3 shadow-lg backdrop-blur ${tone[t.tone]}`}>
          <div className="flex items-start justify-between gap-2">
            <div role="button" tabIndex={0} className="cursor-pointer" title="Show this pair"
              onClick={() => openToast(t)} onKeyDown={(e) => e.key === "Enter" && openToast(t)}>
              <div className="font-semibold">{t.title}</div>
              <div className="mt-0.5 text-xs text-muted">{t.body}</div>
            </div>
            <button className="text-muted hover:text-fg" onClick={() => dismissToast(t.id)} aria-label="Dismiss">✕</button>
          </div>
        </div>
      ))}
    </div>
  );
}
