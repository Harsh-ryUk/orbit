"use client";
import { usePoll } from "@/lib/api";
import { dur, pct } from "@/lib/format";
import { Badge, Card, Empty, Stat } from "@/components/ui";

type Run = {
  name: string; detected: boolean; detector?: number; rca_ok?: boolean; final?: string | null; expected?: string; actions?: string[];
  time_to_action_s?: number | null; time_to_resolution_s?: number | null; fault_to_resolution_s?: number | null; mttr_s?: number | null; detect_latency_s?: number;
};
type Human = { operator: string; scenario: string; outcome: string; expected: string; time_to_resolution_s: number | null; diagnosis_ok: boolean; n_wrong: number };
type Evaluation = { real: Run[]; human: Human[]; sim: { summary: Record<string, number | null>; scenarios: Run[] } };

const med = (xs: (number | null | undefined)[]) => {
  const v = xs.filter((x): x is number => x != null).sort((a, b) => a - b);
  return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
};
const range = (xs: (number | null | undefined)[]) => {
  const v = xs.filter((x): x is number => x != null);
  return v.length > 1 ? `${dur(Math.min(...v))}–${dur(Math.max(...v))}` : "";
};
const group = <T,>(xs: T[], key: (x: T) => string) => {
  const m = new Map<string, T[]>();
  xs.forEach((x) => m.set(key(x), [...(m.get(key(x)) ?? []), x]));
  return [...m.entries()];
};

export default function EvaluationPage() {
  const { data, error } = usePoll<Evaluation>("/api/evaluation", 60000);
  if (!data) return <Card>{error ? <p className="text-bad">{error}</p> : <p className="text-muted">Running the simulator suite…</p>}</Card>;
  const { real, human, sim } = data;
  const det = real.filter((r) => r.detected);
  const handled = (r: Run) => r.final === r.expected;
  const groups = group(real, (r) => r.name);
  const humanGroups = group(human.filter((h) => h.outcome === h.expected), (h) => h.scenario);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Evaluation</h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Measured results from reproducible fault injection. Every scenario is a single fault in a single service, written alongside the system it tests, and the
          hypothesis tests were tuned against them, so accuracy here is in-sample. Treat these as a regression suite, not a generalization claim.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Simulator: RCA accuracy" value={pct(sim.summary["RCA accuracy"])} sub={`${sim.summary.scenarios} scenarios, virtual time`} />
        <Stat label="Simulator: handled correctly" value={pct(sim.summary["handled correctly (recovered or correctly escalated)"])} sub="recovered, or escalated when no safe fix" />
        <Stat label="Real stack: runs" value={real.length} sub={`${det.length} detected · ${groups.length} scenarios`} />
        <Stat label="Real stack: RCA correct" value={det.length ? `${det.filter((r) => r.rca_ok).length}/${det.length}` : "–"} sub="of detected runs" />
      </div>

      <Card title="Real docker stack (OpenTelemetry → Prometheus / Loki / Tempo)" right={<span className="text-[12px] text-muted">times from the alert; approvals granted instantly</span>}>
        {groups.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px] [&_th]:pr-4 [&_td]:pr-4 [&_th:last-child]:pr-0 [&_td:last-child]:pr-0">
              <thead className="text-[12px] text-muted"><tr><th className="pb-2 font-medium">Scenario</th><th className="font-medium">Runs</th><th className="font-medium">Detected</th><th className="font-medium">RCA</th><th className="font-medium">Outcome</th><th className="font-medium">Action</th><th className="font-medium">Alert → action</th><th className="font-medium">Alert → resolved</th></tr></thead>
              <tbody>{groups.map(([name, rs]) => {
                const d = rs.filter((r) => r.detected);
                const acts = Array.from(new Set(d.flatMap((r) => r.actions ?? [])));
                return (
                  <tr key={name} className="border-t border-border">
                    <td className="py-2 font-mono text-[12px]">{name}</td>
                    <td className="num">{rs.length}</td>
                    <td className="num"><span className={d.length < rs.length ? "text-bad" : ""}>{d.length}/{rs.length}</span></td>
                    <td className="num">{d.filter((r) => r.rca_ok).length}/{d.length}</td>
                    <td><Badge tone={d.length && d.every(handled) ? "ok" : "warn"}>{d[0]?.final ?? "not detected"}</Badge></td>
                    <td className="font-mono text-[12px] text-muted">{acts.join(", ") || "–"}</td>
                    <td className="num">{dur(med(d.map((r) => r.time_to_action_s)))}</td>
                    <td className="num">{dur(med(d.map((r) => r.time_to_resolution_s)))} <span className="text-muted">{range(d.map((r) => r.time_to_resolution_s))}</span></td>
                  </tr>
                );
              })}</tbody>
            </table>
            <p className="mt-3 text-[12px] text-muted">Runs without a detector version used the first detector, which missed a Redis outage that was masked by a cache fallback (see redis_down). The fixed detector pages on a component being down.</p>
          </div>
        ) : <Empty>No real-stack runs recorded. Run <code className="font-mono">python -m evaluation.real</code> against the docker stack.</Empty>}
      </Card>

      <Card title="Human baseline vs ORBIT" right={<span className="text-[12px] text-muted">alert → verified recovery</span>}>
        {humanGroups.length ? (
          <table className="w-full text-left text-[13px] [&_th]:pr-4 [&_td]:pr-4 [&_th:last-child]:pr-0 [&_td:last-child]:pr-0">
            <thead className="text-[12px] text-muted"><tr><th className="pb-2 font-medium">Scenario</th><th className="font-medium">Human median (n)</th><th className="font-medium">ORBIT median (n)</th><th className="text-right font-medium">Reduction</th></tr></thead>
            <tbody>{humanGroups.map(([name, hs]) => {
              const o = real.filter((r) => r.name === name && handled(r));
              const hm = med(hs.map((h) => h.time_to_resolution_s)), om = med(o.map((r) => r.time_to_resolution_s));
              return <tr key={name} className="border-t border-border"><td className="py-2 font-mono text-[12px]">{name}</td><td className="num">{dur(hm)} ({hs.length})</td><td className="num">{dur(om)} ({o.length})</td><td className="num text-right">{hm && om != null ? pct(1 - om / hm) : "–"}</td></tr>;
            })}</tbody>
          </table>
        ) : <Empty>No human sessions recorded yet. Without a measured human baseline there is no MTTR-reduction figure to report. Protocol: docs/human-baseline.md.</Empty>}
      </Card>

      <Card title="Simulator suite" right={<span className="text-[12px] text-muted">{sim.summary.scenarios} scenarios, virtual time</span>}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px] [&_th]:pr-4 [&_td]:pr-4 [&_th:last-child]:pr-0 [&_td:last-child]:pr-0">
            <thead className="text-[12px] text-muted"><tr><th className="pb-2 font-medium">Scenario</th><th className="font-medium">RCA</th><th className="font-medium">Confidence</th><th className="font-medium">Outcome</th><th className="font-medium">Actions</th><th className="text-right font-medium">MTTR</th></tr></thead>
            <tbody>{sim.scenarios.map((r) => (
              <tr key={r.name} className="border-t border-border">
                <td className="py-2 font-mono text-[12px]">{r.name}</td>
                <td><Badge tone={r.rca_ok ? "ok" : "bad"}>{r.rca_ok ? "correct" : "wrong"}</Badge></td>
                <td className="num">{pct((r as unknown as { rca_conf: number }).rca_conf)}</td>
                <td><Badge tone={handled(r) ? "ok" : "bad"}>{r.final}</Badge></td>
                <td className="font-mono text-[12px] text-muted">{(r.actions ?? []).join(", ") || "–"}</td>
                <td className="num text-right">{dur(r.mttr_s)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
