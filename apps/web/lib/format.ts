export const pct = (x: number | null | undefined, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);

export function dur(s: number | null | undefined) {
  if (s == null) return "–";
  const t = Math.round(Math.abs(s));
  return t < 60 ? `${t}s` : `${Math.floor(t / 60)}m ${String(t % 60).padStart(2, "0")}s`;
}

export const ago = (now: number, t: number) => `${dur(now - t)} ago`;

/** Metric values by name: ratios as %, latencies as seconds. */
export function metricValue(name: string, v: number | null | undefined) {
  if (v == null) return "–";
  if (name.includes("latency")) return v < 1 ? `${Math.round(v * 1000)}ms` : `${v.toFixed(2)}s`;
  if (name === "redis_up") return v > 0.5 ? "up" : "down";
  return `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;
}

export const label = (s: string) => s.replace(/_/g, " ");
