import { dur, metricValue } from "@/lib/format";

/** Small time-series chart: line, dashed baseline, markers for incident start and resolution. No chart library. */
export function Spark({ name, data, baseline, t0, t1 }: { name: string; data: [number, number][]; baseline: number | null; t0: number; t1: number | null }) {
  const W = 320, H = 96, P = 4;
  if (data.length < 2) return <div className="h-24 text-muted">no data</div>;
  const xs = data.map((d) => d[0]), ys = data.map((d) => d[1]).concat(baseline == null ? [] : [baseline]);
  const x0 = xs[0], x1 = xs[xs.length - 1];
  const lo = Math.min(...ys, 0), hi = Math.max(...ys) * 1.08 || 1;
  const X = (t: number) => P + ((t - x0) / (x1 - x0 || 1)) * (W - 2 * P);
  const Y = (v: number) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const path = data.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const last = data[data.length - 1][1];
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-mono text-[12px]">{name}</span>
        <span className="num text-[12px] text-muted">
          now <b className="text-foreground">{metricValue(name.split(".")[1], last)}</b>
          {baseline != null && <> · baseline {metricValue(name.split(".")[1], baseline)}</>}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded bg-surface-2" role="img" aria-label={`${name} over the last ${dur(x1 - x0)}`}>
        {baseline != null && <line x1={P} x2={W - P} y1={Y(baseline)} y2={Y(baseline)} stroke="var(--muted)" strokeDasharray="3 3" strokeWidth="1" />}
        {t0 >= x0 && <line x1={X(t0)} x2={X(t0)} y1={0} y2={H} stroke="var(--warn)" strokeWidth="1" />}
        {t1 && t1 >= x0 && <line x1={X(t1)} x2={X(t1)} y1={0} y2={H} stroke="var(--ok)" strokeWidth="1" />}
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.8" />
      </svg>
    </div>
  );
}
