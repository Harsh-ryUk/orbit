import type { AuditEvent, Incident } from "@/lib/types";
import { label, pct } from "@/lib/format";

/** The investigation as the agents performed it, derived from the incident record and its audit log. */
export function AgentTrace({ inc, audit }: { inc: Incident; audit: AuditEvent[] }) {
  const n = (src: string) => inc.evidence.filter((e) => e.source === src).length;
  const dec = (...agents: string[]) => audit.filter((a) => agents.includes(a.agent)).map((a) => `${a.agent}: ${a.decision}`).join(" · ");
  const top = inc.hypotheses[0];
  const act = inc.actions[inc.actions.length - 1];
  const steps: { agent: string; out: string; done: boolean }[] = [
    { agent: "Supervisor / triage", out: `severity ${inc.severity ?? "unrated"}`, done: !!inc.severity },
    { agent: "Metrics agent", out: `${n("metrics")} anomalies vs baseline`, done: n("metrics") > 0 },
    { agent: "Deployment agent", out: `${n("deployment")} recent change(s) before onset`, done: n("deployment") > 0 },
    { agent: "Log agent", out: `${n("logs")} error signature(s), ${inc.log_signatures?.filter((s) => s.is_new).length ?? 0} new`, done: n("logs") > 0 },
    { agent: "Trace agent", out: inc.trace_summary ? `${inc.trace_summary.n_traces} traces; new ops: ${inc.trace_summary.new_ops.join(", ") || "none"}` : "no traces available", done: !!inc.trace_summary },
    { agent: "Hypothesis engine", out: top ? `${inc.hypotheses.length} tested; leader ${label(top.category)} ${pct(top.confidence)}` : "–", done: !!top },
    { agent: "RAG (runbooks, memory)", out: `${n("rag")} runbook(s), ${n("memory")} similar past incident(s)`, done: n("rag") + n("memory") > 0 },
    { agent: "RCA", out: inc.rca ? `${label(inc.rca.category)} at ${pct(inc.rca.confidence)}` : "–", done: !!inc.rca },
    { agent: "Laya (decisions)", out: dec("action", "risk", "approval", "recovery", "escalation") || "–", done: audit.some((a) => a.agent === "action") },
    { agent: "Policy gate", out: audit.filter((a) => a.agent === "policy").map((a) => `${a.decision}`).join(" → ") || "–", done: audit.some((a) => a.agent === "policy") },
    { agent: "Executor", out: act ? `${act.action_type}(${Object.values(act.parameters).join(", ")}) ${act.execution_status}` : "no action executed", done: inc.actions.some((a) => a.execution_status !== "not_started") },
    { agent: "Recovery verification", out: inc.recovery.length ? `${inc.recovery.filter((r) => r.status === "RECOVERED").length}/${inc.recovery.length} metrics healthy` : "–", done: inc.recovery.length > 0 },
  ];
  return (
    <ol className="relative ml-2 border-l border-border">
      {steps.map((s) => (
        <li key={s.agent} className="relative pb-3 pl-5 last:pb-0">
          <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border ${s.done ? "border-accent bg-accent" : "border-border bg-surface"}`} />
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className={`text-[13px] font-medium ${s.done ? "" : "text-muted"}`}>{s.agent}</span>
            <span className="text-[12px] text-muted">{s.out}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
