import type { Hypothesis } from "@/lib/types";
import { label, pct } from "@/lib/format";

const ROW = 40, HYP_W = 210, TEST_W = 420, GAP = 70, RCA_W = 150;

/** How the evidence supports or contradicts each hypothesis: RCA <- hypotheses <- the tests that moved their score.
 *  Green edges raised a hypothesis's score, red lowered it; edge width is the test weight. */
export function EvidenceGraph({ hypotheses, max = 4 }: { hypotheses: Hypothesis[]; max?: number }) {
  const hs = hypotheses.slice(0, max);
  const rows: { h: number; t: Hypothesis["tests"][number]; y: number }[] = [];
  hs.forEach((h, hi) => h.tests.filter((t) => t.weight !== 0).forEach((t) => rows.push({ h: hi, t, y: rows.length * ROW })));
  const hy = hs.map((_, hi) => {
    const mine = rows.filter((r) => r.h === hi);
    return mine.length ? (mine[0].y + mine[mine.length - 1].y) / 2 : hi * ROW;
  });
  const H = Math.max(rows.length * ROW, hs.length * ROW) + 8;
  const xH = RCA_W + GAP, xT = xH + HYP_W + GAP, W = xT + TEST_W;
  const edge = (x1: number, y1: number, x2: number, y2: number) => `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;
  const color = (w: number) => (w > 0 ? "var(--ok)" : "var(--bad)");
  return (
    <div className="overflow-x-auto">
      <div className="relative" style={{ width: W, height: H }}>
        <svg width={W} height={H} className="absolute inset-0" aria-hidden>
          {hs.map((_, hi) => (
            <path key={hi} d={edge(xH, hy[hi] + 17, RCA_W, hy[0] + 17)} fill="none" stroke="var(--border)" strokeWidth={hi === 0 ? 3 : 1.5} />
          ))}
          {rows.map((r, i) => (
            <path key={i} d={edge(xT, r.y + 17, xH + HYP_W, hy[r.h] + 17)} fill="none" stroke={color(r.t.weight)} strokeOpacity="0.75" strokeWidth={Math.max(1, Math.abs(r.t.weight) * 1.4)} />
          ))}
        </svg>
        <div className="absolute rounded-md border border-accent bg-surface-2 px-3 py-1.5" style={{ left: 0, top: hy[0], width: RCA_W, height: 34 }}>
          <div className="text-[11px] uppercase tracking-wide text-accent">Root cause</div>
        </div>
        {hs.map((h, hi) => (
          <div key={h.id} className={`absolute rounded-md border bg-surface px-3 py-1 ${hi === 0 ? "border-accent" : "border-border"}`} style={{ left: xH, top: hy[hi], width: HYP_W, height: 34 }}>
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[12px] font-medium">{label(h.category)}</span>
              <span className="num text-[12px] font-semibold">{pct(h.confidence)}</span>
            </div>
          </div>
        ))}
        {rows.map((r, i) => (
          <div key={i} title={`${r.t.prediction}: ${r.t.observed}`} className="absolute flex items-center gap-2 rounded border border-border bg-surface px-2" style={{ left: xT, top: r.y, width: TEST_W, height: 34 }}>
            <span className={`num w-9 shrink-0 text-[12px] font-semibold ${r.t.weight > 0 ? "text-ok" : "text-bad"}`}>{r.t.weight > 0 ? "+" : ""}{r.t.weight.toFixed(1)}</span>
            <span className="truncate text-[12px] text-muted">{r.t.observed}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
