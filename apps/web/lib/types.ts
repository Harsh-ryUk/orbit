export type Evidence = { id: string; source: string; type: string; timestamp: number; content: string; relevance: string };
export type Test = { prediction: string; observed: string; weight: number };
export type Hypothesis = { id: string; category: string; description: string; confidence: number; status: string; tests: Test[] };
export type Decision = { category: string; label: string; confidence: number; rationale: string; latency_ms: number; engine: string };
export type Action = {
  id: string; action_type: string; parameters: Record<string, string>; risk: string; approval_status: string;
  execution_status: string; executed_at: number | null; result?: string; laya: Decision; policy: { decision: string; reasons: string[] };
};
export type RecoveryRow = { metric: string; baseline: number; before_value: number; after_value: number | null; threshold: string; status: string };
export type Rca = {
  root_cause: string; category: string; confidence: number; supporting_evidence: string[]; contradicting_evidence: string[];
  affected_services: string[]; timeline: { t: number; event: string }[];
};
export type Anomaly = { service: string; metric: string; baseline: number; current: number; onset: number };
export type LogSig = { service: string; level: string; template: string; count: number; first_seen: number; sample: string; is_new: boolean };
export type TraceSummary = {
  service: string; n_traces: number; new_ops: string[]; path: string[];
  error_spans: { name: string; kind: string; rate: number; sample: string | null }[];
  bottleneck: { name: string; kind: string; delta: number; share: number } | null;
};
export type Incident = {
  id: string; service: string; environment: string; severity: string | null; status: string; final_status: string | null;
  trigger: { reason: string }; started_at: number; resolved_at: number | null; mttr_s?: number; root_cause: string | null;
  root_cause_confidence: number | null; rca: Rca | null; evidence: Evidence[]; hypotheses: Hypothesis[]; actions: Action[];
  recovery: RecoveryRow[]; timeline: { t: number; event: string }[]; approvals: { approved: boolean; by: string }[];
  escalation_reason?: string; anomalies?: Anomaly[]; log_signatures?: LogSig[]; trace_summary?: TraceSummary | null;
};
export type Stats = {
  total: number; open: number; awaiting_approval: number; recovered: number; escalated: number;
  recovery_rate: number | null; automation_rate: number | null; mttr_mean_s: number | null; mttr_median_s: number | null;
};
export type Health = { service: string; status: "healthy" | "degraded"; anomalous: string[]; metrics: Record<string, number> };
export type Change = { t: number; service: string; kind: string; ref: string; previous: string; rolled_back: boolean };
export type Mode = { target: "sim" | "real"; now: number };
export type MetricSeries = { series: Record<string, [number, number][]>; baselines: Record<string, number | null>; started_at: number; resolved_at: number | null };
export type AuditEvent = { ts: number; incident_id: string; agent: string; decision?: string; [k: string]: unknown };
