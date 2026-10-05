const STEPS = ["DETECTED", "INVESTIGATING", "HYPOTHESIS_FORMED", "RCA_CONFIRMED", "REMEDIATION_PROPOSED", "AWAITING_APPROVAL", "EXECUTING", "VERIFYING", "RECOVERED", "CLOSED"];
const TERMINAL_BAD = ["ESCALATED", "FAILED", "ROLLED_BACK"];

/** Incident lifecycle. The approval step is dimmed when policy auto-executed. An escalation shows only the stages
 *  actually reached, then the terminal state. */
export function Stepper({ status, approvalUsed, executed }: { status: string; approvalUsed: boolean; executed: boolean }) {
  const bad = TERMINAL_BAD.includes(status);
  const reached = bad ? STEPS.indexOf(executed ? "VERIFYING" : approvalUsed ? "AWAITING_APPROVAL" : "REMEDIATION_PROPOSED") : STEPS.indexOf(status);
  const steps = bad ? [...STEPS.slice(0, reached + 1), status] : STEPS;
  return (
    <ol className="flex flex-wrap gap-1.5">
      {steps.map((s, i) => {
        const current = s === status;
        const skipped = s === "AWAITING_APPROVAL" && !approvalUsed && !current && reached > 5;
        const tone = bad && i === steps.length - 1 ? "border-bad text-bad bg-bad/10"
          : current ? "border-accent text-accent bg-accent/10"
          : skipped ? "border-dashed border-border text-muted/60"
          : i <= reached ? "border-border text-foreground" : "border-border text-muted/60";
        return (
          <li key={s} className={`rounded border px-2 py-0.5 text-[11px] uppercase tracking-wide ${tone}`} aria-current={current ? "step" : undefined}>
            {s.replace(/_/g, " ")}{skipped ? " (auto)" : ""}
          </li>
        );
      })}
    </ol>
  );
}
