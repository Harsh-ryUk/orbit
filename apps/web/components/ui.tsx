import type { ReactNode } from "react";

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-lg border border-border bg-surface ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES = {
  ok: "text-ok border-ok/40 bg-ok/10", warn: "text-warn border-warn/40 bg-warn/10", bad: "text-bad border-bad/40 bg-bad/10",
  info: "text-info border-info/40 bg-info/10", muted: "text-muted border-border bg-surface-2",
};
export type Tone = keyof typeof TONES;

export function Badge({ tone = "muted", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide ${TONES[tone]}`}>{children}</span>;
}

export const statusTone = (s: string): Tone =>
  ({ CLOSED: "ok", RECOVERED: "ok", ESCALATED: "bad", FAILED: "bad", AWAITING_APPROVAL: "warn", ROLLED_BACK: "warn" } as Record<string, Tone>)[s] ?? "info";
export const sevTone = (s: string | null): Tone => (s === "P0" ? "bad" : s === "P1" ? "warn" : s ? "info" : "muted");
export const riskTone = (r: string): Tone => (r === "LOW" ? "ok" : r === "MEDIUM" ? "warn" : "bad");

const TEXT: Record<Tone, string> = { ok: "text-ok", warn: "text-warn", bad: "text-bad", info: "text-info", muted: "text-muted" };

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`num mt-1 text-2xl font-semibold ${tone ? TEXT[tone] : ""}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-muted">{children}</p>;
}

export function Bar({ value, tone = "info" }: { value: number; tone?: Tone }) {
  const c = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", info: "bg-info", muted: "bg-muted" }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-2">
      <div className={`h-full ${c}`} style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
    </div>
  );
}
