"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, usePoll } from "@/lib/api";
import { ago, dur, label, metricValue, pct } from "@/lib/format";
import type { Change, Health, Incident, Mode, Stats } from "@/lib/types";
import { Badge, Card, Empty, Stat, sevTone, statusTone } from "@/components/ui";

const FAULTS = ["bad_deploy", "db_exhaustion", "config_regression", "memory_leak", "cpu_saturation", "redis_down", "dependency_down", "network_latency"];
const SHOWN = ["error_rate", "p95_latency", "db_pool", "cache_hit", "cpu", "memory"];

export default function Dashboard() {
  const mode = usePoll<Mode>("/api/mode");
  const stats = usePoll<Stats>("/api/stats");
  const health = usePoll<Health[]>("/api/health");
  const incidents = usePoll<Incident[]>("/api/incidents");
  const changes = usePoll<Change[]>("/api/changes", 5000);
  const now = mode.data?.now ?? 0;
  const down = mode.error && !mode.data;

  if (down) return <ApiDown error={mode.error!} />;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Active incidents" value={stats.data?.open ?? "–"} sub={`${stats.data?.total ?? 0} total`} />
        <Stat label="Awaiting approval" value={stats.data?.awaiting_approval ?? "–"} tone={stats.data?.awaiting_approval ? "warn" : undefined} sub="needs a human" />
        <Stat label="Recovery rate" value={pct(stats.data?.recovery_rate)} sub={`${stats.data?.recovered ?? 0} recovered, ${stats.data?.escalated ?? 0} escalated`} />
        <Stat label="Automation rate" value={pct(stats.data?.automation_rate)} sub="recovered with no approval" />
        <Stat label="MTTR (median)" value={dur(stats.data?.mttr_median_s)} sub="detection to verified recovery" />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Service health">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(health.data ?? []).map((h) => (
                <div key={h.service} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{h.service}</span>
                    <Badge tone={h.status === "healthy" ? "ok" : "bad"}>{h.status}</Badge>
                  </div>
                  <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-1 text-[12px]">
                    {Object.entries(h.metrics).filter(([k]) => SHOWN.includes(k) || k === "redis_up").map(([k, v]) => (
                      <div key={k}>
                        <dt className="text-muted">{label(k)}</dt>
                        <dd className={`num font-medium ${h.anomalous.includes(k) ? "text-bad" : ""}`}>{metricValue(k, v)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Incidents">
            {incidents.data?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead className="text-[12px] text-muted">
                    <tr><th className="pb-2 font-medium">ID</th><th className="font-medium">Service</th><th className="font-medium">Sev</th><th className="font-medium">Status</th><th className="font-medium">Root cause</th><th className="font-medium">Started</th><th className="text-right font-medium">MTTR</th></tr>
                  </thead>
                  <tbody>
                    {incidents.data.map((i) => (
                      <tr key={i.id} className="border-t border-border hover:bg-surface-2">
                        <td className="py-2"><Link href={`/incidents/${i.id}`} className="font-mono text-accent hover:underline">{i.id}</Link></td>
                        <td>{i.service}</td>
                        <td><Badge tone={sevTone(i.severity)}>{i.severity ?? "–"}</Badge></td>
                        <td><Badge tone={statusTone(i.status)}>{label(i.status)}</Badge></td>
                        <td className="max-w-[18rem] truncate">{i.root_cause ?? "–"} {i.root_cause_confidence != null && <span className="num text-muted">{pct(i.root_cause_confidence)}</span>}</td>
                        <td className="text-muted">{ago(now, i.started_at)}</td>
                        <td className="num text-right">{dur(i.mttr_s)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>No incidents yet. {mode.data?.target === "sim" ? "Inject a fault to see ORBIT investigate." : "ORBIT opens one when the detector fires."}</Empty>}
          </Card>
        </div>

        <div className="space-y-5">
          {mode.data?.target === "sim" && <SimPanel onChange={() => { health.reload(); incidents.reload(); stats.reload(); changes.reload(); mode.reload(); }} />}
          <Card title="Recent deployments and config changes">
            {changes.data?.length ? (
              <ul className="space-y-2 text-[13px]">
                {changes.data.map((c, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-3">
                    <span><b>{c.service}</b> <span className="text-muted">{c.kind}</span> <span className="font-mono text-[12px]">{c.previous} → {c.ref}</span>{c.rolled_back && <> <Badge tone="warn">rolled back</Badge></>}</span>
                    <span className="num shrink-0 text-muted">{ago(now, c.t)}</span>
                  </li>
                ))}
              </ul>
            ) : <Empty>No changes recorded.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}

function SimPanel({ onChange }: { onChange: () => void }) {
  const router = useRouter();
  const [fault, setFault] = useState("bad_deploy");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const svc = fault === "redis_down" ? "redis" : "orders";

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setMsg(null);
    try { await fn(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); onChange(); }
  }
  async function detect() {
    const r = await api<{ detected: boolean; incident?: Incident }>("/api/detect", {});
    if (r.detected && r.incident) router.push(`/incidents/${r.incident.id}`);
    else setMsg("No alert yet: the detector needs a breach sustained for 60s. Advance time.");
  }
  const btn = "rounded-md border border-border bg-surface-2 px-3 py-1.5 text-[13px] hover:border-accent disabled:opacity-50";
  return (
    <Card title="Simulator" right={<Badge tone="info">demo</Badge>}>
      <p className="mb-3 text-[12px] text-muted">In-process fault simulator with virtual time. The real stack runs with ORBIT_TARGET=real.</p>
      <label className="mb-1 block text-[12px] text-muted" htmlFor="fault">Fault</label>
      <select id="fault" value={fault} onChange={(e) => setFault(e.target.value)} className="mb-3 w-full rounded-md border border-border bg-surface px-2 py-1.5">
        {FAULTS.map((f) => <option key={f} value={f}>{label(f)} ({f === "redis_down" ? "redis" : "orders"})</option>)}
      </select>
      <button disabled={busy} className="mb-3 w-full rounded-md bg-accent px-3 py-2 text-[13px] font-semibold text-background hover:opacity-90 disabled:opacity-50"
        onClick={() => run(async () => { await api("/api/sim/inject", { name: fault, service: svc }); await api("/api/sim/advance", { seconds: 90 }); await detect(); })}>
        Inject fault and run to alert
      </button>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} className={btn} onClick={() => run(async () => { await api("/api/sim/inject", { name: fault, service: svc }); })}>Inject only</button>
        <button disabled={busy} className={btn} onClick={() => run(async () => { await api("/api/sim/advance", { seconds: 60 }); })}>+60s</button>
        <button disabled={busy} className={btn} onClick={() => run(detect)}>Run detector</button>
      </div>
      {msg && <p role="status" className="mt-3 text-[12px] text-warn">{msg}</p>}
    </Card>
  );
}

function ApiDown({ error }: { error: string }) {
  return (
    <Card title="Cannot reach the ORBIT API">
      <p className="text-muted">The dashboard expects the API at <code className="font-mono">{process.env.NEXT_PUBLIC_API ?? "http://localhost:8000"}</code>. Start it from the repo root:</p>
      <pre className="mt-3 rounded bg-surface-2 p-3 font-mono text-[12px]">.venv/bin/uvicorn orbit.api:app --port 8000</pre>
      <p className="mt-3 text-[12px] text-muted">{error}</p>
    </Card>
  );
}
