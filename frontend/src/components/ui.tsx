import type { ReactNode } from "react";

export function Panel({ title, right, children, className = "" }: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-edge bg-panel ${className}`}>
      <header className="flex items-center justify-between gap-2 border-b border-edge px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, mono = true }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-0.5 truncate text-base text-fg ${mono ? "font-mono tabular-nums" : ""}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

const TONES = {
  ok: "bg-buy/15 text-buy ring-buy/30",
  warn: "bg-wait/15 text-wait ring-wait/30",
  bad: "bg-sell/15 text-sell ring-sell/30",
  neutral: "bg-edge text-muted ring-edge",
} as const;

export type Tone = keyof typeof TONES;

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Dot({ tone }: { tone: Tone }) {
  const color = { ok: "bg-buy", warn: "bg-wait", bad: "bg-sell", neutral: "bg-muted" }[tone];
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export function ErrorNote({ message }: { message: string }) {
  return <p className="rounded border border-sell/30 bg-sell/10 px-3 py-2 text-sm text-sell">{message}</p>;
}

export function Planned({ phase, children }: { phase: string; children: ReactNode }) {
  return (
    <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded border border-dashed border-edge p-6 text-center">
      <Badge tone="neutral">{phase}</Badge>
      <p className="max-w-md text-sm text-muted">{children}</p>
    </div>
  );
}
