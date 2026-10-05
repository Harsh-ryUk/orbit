"use client";
import Link from "next/link";
import { useState } from "react";
import { api, usePoll } from "@/lib/api";
import { ago, dur, label, metricValue, pct } from "@/lib/format";
import type { Action, AuditEvent, Incident, MetricSeries, Mode } from "@/lib/types";
import { Badge, Bar, Card, Empty, riskTone, sevTone, statusTone, type Tone } from "@/components/ui";
import { Spark } from "@/components/chart";
import { EvidenceGraph } from "@/components/evidence-graph";
import { AgentTrace } from "@/components/agent-trace";
import { Stepper } from "@/components/stepper";

const TABS = ["Overview", "Hypotheses", "Evidence", "Telemetry", "Remediation", "Agent trace", "Audit"] as const;
type Tab = (typeof TABS)[number];
const confTone = (c: number): Tone => (c >= 0.8 ? "ok" : c >= 0.5 ? "warn" : "bad");

export function IncidentView({ id }: { id: string }) {
  const inc = usePoll<Incident>(`/api/incidents/${id}`, 2500);
  const metrics = usePoll<MetricSeries>(`/api/incidents/${id}/metrics`, 5000);
  const audit = usePoll<AuditEvent[]>(`/api/incidents/${id}/audit`, 4000);
  const mode = usePoll<Mode>("/api/mode", 5000);
  const [tab, setTab] = useState<Tab>("Overview");
  const i = inc.data;

  if (!i) return <Card>{inc.error ? <p className="text-bad">Could not load {id}: {inc.error}</p> : <p className="text-muted">Loading {id}…</p>}</Card>;
  const now = mode.data?.now ?? i.started_at;
  const pending = i.actions.find((a) => a.approval_status === "pending");

  return (
    <div className="space-y-4">
      <div>
        <Link href="/" className="text-[12px] text-muted hover:text-foreground">← Dashboard</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-xl font-semibold">{i.id}</h1>
          <span className="text-lg">{i.service}</span>
          <Badge tone={sevTone(i.severity)}>{i.severity ?? "unrated"}</Badge>
          <Badge tone={statusTone(i.status)}>{label(i.status)}</Badge>
          <span className="text-[13px] text-muted">started {ago(now, i.started_at)} · alert: <span className="font-mono">{i.trigger.reason}</span></span>
        </div>
      </div>

      <Stepper status={i.status} approvalUsed={i.actions.some((a) => a.policy.decision === "HUMAN_APPROVAL")} executed={i.actions.some((a) => a.execution_status !== "not_started")} />

      {pending && <ApprovalBanner id={i.id} action={pending} onDone={inc.reload} />}
      {i.status === "CLOSED" && <Outcome tone="ok">Recovered and verified from telemetry in {dur(i.mttr_s)}. Incident stored in memory for future retrieval.</Outcome>}
      {i.status === "ESCALATED" && <Outcome tone="bad">Escalated to a human: {i.escalation_reason ?? "no safe automated action"}. ORBIT did not change the system.</Outcome>}

      <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[13px] ${tab === t ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground"}`}>{t}</button>
        ))}
      </div>

      {tab === "Overview" && <Overview i={i} />}
      {tab === "Hypotheses" && <Hypotheses i={i} />}
      {tab === "Evidence" && <EvidenceList i={i} />}
      {tab === "Telemetry" && <Telemetry i={i} m={metrics.data} />}
      {tab === "Remediation" && <Remediation i={i} />}
      {tab === "Agent trace" && <Card title="What each agent did"><AgentTrace inc={i} audit={audit.data ?? []} /></Card>}
      {tab === "Audit" && <Audit events={audit.data ?? []} />}
    </div>
  );
}

function Outcome({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const c = tone === "ok" ? "border-ok/40 bg-ok/10 text-ok" : "border-bad/40 bg-bad/10 text-bad";
  return <p role="status" className={`rounded-md border px-4 py-2.5 text-[13px] ${c}`}>{children}</p>;
}

function ApprovalBanner({ id, action, onDone }: { id: string; action: Action; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function decide(approved: boolean) {
    setBusy(true);
    setErr(null);
    try { await api(`/api/incidents/${id}/remediation/approve`, { by: "dashboard", approved }); onDone(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const params = Object.entries(action.parameters).map(([k, v]) => `${k}=${v}`).join(", ");
  return (
    <section aria-label="Approval required" className="rounded-lg border border-warn/50 bg-warn/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-2"><Badge tone="warn">Approval required</Badge><Badge tone={riskTone(action.risk)}>{action.risk} risk</Badge></div>
          <p className="font-mono text-[15px] font-semibold">{action.action_type}({params})</p>
          <p className="mt-1 text-[12px] text-muted">Laya proposed <b>{action.laya.label}</b> at {pct(action.laya.confidence)} confidence. {action.policy.reasons.join("; ")}</p>
        </div>
        <div className="flex gap-2">
          <button disabled={busy} onClick={() => decide(false)} className="rounded-md border border-border bg-surface px-4 py-2 text-[13px] hover:border-bad disabled:opacity-50">Reject</button>
          <button disabled={busy} onClick={() => decide(true)} className="rounded-md bg-accent px-4 py-2 text-[13px] font-semibold text-background hover:opacity-90 disabled:opacity-50">Approve and execute</button>
        </div>
      </div>
      {err && <p role="alert" className="mt-2 text-[12px] text-bad">{err}</p>}
    </section>
  );
}

function Overview({ i }: { i: Incident }) {
  const r = i.rca;
  const rel = (t: number) => `${t < i.started_at ? "T−" : "T+"}${dur(t - i.started_at)}`;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
      <Card title="Root cause analysis" className="lg:col-span-3">
        {r ? (
          <div className="space-y-4">
            <div>
              <p className="text-lg font-semibold">{r.root_cause}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3"><div className="w-40 sm:w-48"><Bar value={r.confidence} tone={confTone(r.confidence)} /></div><span className="num font-semibold">{pct(r.confidence)}</span><Badge>{label(r.category)}</Badge></div>
              <p className="mt-2 text-[12px] text-muted">Affected: {r.affected_services.join(", ")}</p>
            </div>
            <Bullets title="Supporting evidence" items={r.supporting_evidence} tone="ok" />
            <Bullets title="Contradicting evidence" items={r.contradicting_evidence} tone="bad" />
          </div>
        ) : <Empty>Investigation has not produced an RCA yet.</Empty>}
      </Card>
      <Card title="Timeline" className="lg:col-span-2">
        <ol className="space-y-2">
          {i.timeline.map((e, k) => (
            <li key={k} className="flex gap-3 text-[13px]"><span className="num w-20 shrink-0 text-muted">{rel(e.t)}</span><span>{e.event}</span></li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function Bullets({ title, items, tone }: { title: string; items: string[]; tone: Tone }) {
  return (
    <div>
      <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {items.length ? <ul className="space-y-1">{items.map((t, k) => <li key={k} className="flex gap-2 text-[13px]"><span className={tone === "ok" ? "text-ok" : "text-bad"} aria-hidden>{tone === "ok" ? "+" : "−"}</span>{t}</li>)}</ul> : <p className="text-[13px] text-muted">None.</p>}
    </div>
  );
}

function Hypotheses({ i }: { i: Incident }) {
  if (!i.hypotheses.length) return <Card><Empty>No hypotheses yet.</Empty></Card>;
  return (
    <div className="space-y-4">
      <Card title="Evidence graph" right={<span className="text-[12px] text-muted">green raised a hypothesis, red lowered it</span>}>
        <EvidenceGraph hypotheses={i.hypotheses} />
      </Card>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {i.hypotheses.map((h, k) => (
          <Card key={h.id} title={<span className="flex items-center gap-2"><span className="font-mono text-muted">{h.id}</span>{h.description}</span>} right={<Badge tone={k === 0 && h.confidence > 0.5 ? "ok" : "muted"}>{h.status}</Badge>}>
            <div className="mb-3 flex items-center gap-3"><div className="flex-1"><Bar value={h.confidence} tone={k === 0 ? confTone(h.confidence) : "muted"} /></div><span className="num font-semibold">{pct(h.confidence, 1)}</span></div>
            <ul className="space-y-1.5">
              {h.tests.map((t, n) => (
                <li key={n} className="text-[12px]"><span className={`num font-semibold ${t.weight > 0 ? "text-ok" : t.weight < 0 ? "text-bad" : "text-muted"}`}>{t.weight > 0 ? "+" : ""}{t.weight.toFixed(1)}</span> <span className="text-muted">predicts {t.prediction}:</span> {t.observed}</li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}

function EvidenceList({ i }: { i: Incident }) {
  const sources = Array.from(new Set(i.evidence.map((e) => e.source)));
  const [sel, setSel] = useState<string | null>(null);
  const rows = i.evidence.filter((e) => !sel || e.source === sel);
  return (
    <Card title={`Evidence (${rows.length})`} right={
      <div className="flex flex-wrap gap-1">
        <button onClick={() => setSel(null)} aria-pressed={!sel} className={`rounded border px-2 py-0.5 text-[11px] ${!sel ? "border-accent text-accent" : "border-border text-muted"}`}>all</button>
        {sources.map((s) => <button key={s} onClick={() => setSel(s)} aria-pressed={sel === s} className={`rounded border px-2 py-0.5 text-[11px] ${sel === s ? "border-accent text-accent" : "border-border text-muted"}`}>{s}</button>)}
      </div>}>
      <ul className="divide-y divide-border">
        {rows.map((e) => (
          <li key={e.id} className="flex gap-3 py-2 text-[13px]">
            <span className="font-mono text-[12px] text-muted">{e.id}</span>
            <Badge tone={e.source === "hypothesis_test" ? "info" : "muted"}>{e.source}</Badge>
            <span className="min-w-0 flex-1 break-words">{e.content}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Telemetry({ i, m }: { i: Incident; m: MetricSeries | null }) {
  const sigs = i.log_signatures ?? [];
  const tr = i.trace_summary;
  return (
    <div className="space-y-4">
      <Card title="Metrics" right={<span className="text-[12px] text-muted"><span className="text-warn">│</span> incident start <span className="text-ok">│</span> recovered · dashed = baseline</span>}>
        {m && Object.keys(m.series).length ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Object.entries(m.series).map(([k, d]) => <Spark key={k} name={k} data={d} baseline={m.baselines[k]} t0={m.started_at} t1={m.resolved_at} />)}
          </div>
        ) : <Empty>No anomalous metrics recorded.</Empty>}
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Log signatures" right={<span className="text-[12px] text-muted">variable parts stripped, grouped</span>}>
          {sigs.length ? (
            <ul className="space-y-2">
              {sigs.map((s, k) => (
                <li key={k} className="text-[12px]">
                  <div className="flex items-center gap-2"><Badge tone={s.level === "ERROR" ? "bad" : "warn"}>{s.level}</Badge><span className="font-semibold">{s.service}</span><span className="num text-muted">×{s.count}</span>{s.is_new && <Badge tone="info">new</Badge>}</div>
                  <p className="mt-1 break-words font-mono text-muted">{s.template}</p>
                </li>
              ))}
            </ul>
          ) : <Empty>No error signatures in the incident window.</Empty>}
        </Card>
        <Card title="Trace analysis">
          {tr ? (
            <div className="space-y-3 text-[13px]">
              <p className="text-muted">{tr.n_traces} traces compared with the pre-incident baseline for <b className="text-foreground">{tr.service}</b>.</p>
              <div><h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">Failing request path</h3>
                <p className="font-mono text-[12px]">{tr.path.length ? tr.path.join("  →  ") : "no failing requests"}</p></div>
              <div><h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">Latency bottleneck</h3>
                <p>{tr.bottleneck ? <><span className="font-mono text-[12px]">{tr.bottleneck.name}</span> <span className="text-muted">(+{tr.bottleneck.delta.toFixed(2)}s, {pct(tr.bottleneck.share)} of added latency)</span></> : "none"}</p></div>
              <div><h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">New operations since baseline</h3>
                <p className="font-mono text-[12px]">{tr.new_ops.length ? tr.new_ops.join(", ") : "none"}</p></div>
              {tr.error_spans.length > 0 && <div><h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">Failing spans</h3>
                <ul>{tr.error_spans.map((e) => <li key={e.name} className="text-[12px]"><span className="font-mono">{e.name}</span> <span className="num text-muted">{pct(e.rate)}</span> {e.sample}</li>)}</ul></div>}
            </div>
          ) : <Empty>No traces available for this incident (backend down or not sampled).</Empty>}
        </Card>
      </div>
    </div>
  );
}

function Remediation({ i }: { i: Incident }) {
  return (
    <div className="space-y-4">
      {i.actions.length ? i.actions.map((a) => {
        const params = Object.entries(a.parameters).map(([k, v]) => `${k}=${v}`).join(", ");
        return (
          <Card key={a.id} title={<span className="font-mono">{a.action_type}({params})</span>} right={<div className="flex gap-2"><Badge tone={riskTone(a.risk)}>{a.risk}</Badge><Badge tone={a.execution_status === "success" ? "ok" : a.execution_status === "failed" ? "bad" : "muted"}>{label(a.execution_status)}</Badge></div>}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 text-[13px]">
              <div>
                <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">Laya decision</h3>
                <p><b>{a.laya.label}</b> <span className="num text-muted">{pct(a.laya.confidence)} · {a.laya.latency_ms.toFixed(2)}ms · {a.laya.engine}</span></p>
                <p className="mt-1 text-muted">{a.laya.rationale}</p>
              </div>
              <div>
                <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted">Policy gate</h3>
                <p><Badge tone={a.policy.decision === "AUTO_EXECUTE" ? "ok" : a.policy.decision === "BLOCK" ? "bad" : "warn"}>{label(a.policy.decision)}</Badge> <span className="text-muted">approval: {a.approval_status}</span></p>
                <ul className="mt-1 text-muted">{a.policy.reasons.map((r, k) => <li key={k}>{r}</li>)}</ul>
              </div>
            </div>
          </Card>
        );
      }) : <Card><Empty>{i.status === "ESCALATED" ? "No action was taken: no safe automated remediation exists for this cause." : "No remediation proposed yet."}</Empty></Card>}
      <Card title="Recovery verification" right={i.recovery.length ? <Badge tone={i.recovery.every((r) => r.status === "RECOVERED") ? "ok" : "bad"}>{i.recovery.filter((r) => r.status === "RECOVERED").length}/{i.recovery.length} healthy</Badge> : undefined}>
        {i.recovery.length ? (
          <table className="w-full text-left text-[13px] [&_th]:pr-4 [&_td]:pr-4 [&_th:last-child]:pr-0 [&_td:last-child]:pr-0">
            <thead className="text-[12px] text-muted"><tr><th className="pb-2 font-medium">Metric</th><th className="font-medium">Baseline</th><th className="font-medium">At incident</th><th className="font-medium">After remediation</th><th className="text-right font-medium">Status</th></tr></thead>
            <tbody>{i.recovery.map((r) => {
              const name = r.metric.split(".")[1];
              return <tr key={r.metric} className="border-t border-border"><td className="py-2 font-mono text-[12px]">{r.metric}</td><td className="num">{metricValue(name, r.baseline)}</td><td className="num text-bad">{metricValue(name, r.before_value)}</td><td className="num">{metricValue(name, r.after_value)}</td><td className="text-right"><Badge tone={r.status === "RECOVERED" ? "ok" : "bad"}>{r.status === "RECOVERED" ? "healthy" : "breached"}</Badge></td></tr>;
            })}</tbody>
          </table>
        ) : <Empty>Nothing to verify yet. ORBIT only calls an incident resolved after telemetry confirms recovery.</Empty>}
      </Card>
    </div>
  );
}

function Audit({ events }: { events: AuditEvent[] }) {
  const t0 = events[0]?.ts ?? 0; // audit timestamps are wall-clock, not simulator time: show offsets from the first event
  return (
    <Card title={`Audit log (${events.length})`} right={<span className="text-[12px] text-muted">hash-chained; secrets redacted</span>}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12px] [&_th]:pr-4 [&_td]:pr-4 [&_th:last-child]:pr-0 [&_td:last-child]:pr-0">
          <thead className="text-muted"><tr><th className="pb-2 font-medium">Time</th><th className="font-medium">Agent</th><th className="font-medium">Decision</th><th className="font-medium">Detail</th></tr></thead>
          <tbody>{events.map((e, k) => {
            const { ts, incident_id: _i, agent, decision, ...rest } = e; void _i;
            return <tr key={k} className="border-t border-border align-top"><td className="num py-1.5 text-muted">{(ts - t0 >= 0 ? "+" : "") + (ts - t0).toFixed(0)}s</td><td className="font-medium">{agent}</td><td>{String(decision ?? "")}</td><td className="break-all font-mono text-muted">{JSON.stringify(rest)}</td></tr>;
          })}</tbody>
        </table>
      </div>
    </Card>
  );
}
