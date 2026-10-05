# ORBIT — Observe. Reason. Act. Verify.

AI reliability control plane: investigate a production incident, decide under a deterministic safety policy,
execute allowlisted remediation, and **prove recovery with telemetry** before calling it resolved.

Status: **milestone 1 — vertical slice against a fault simulator.** Full spec in the project brief.

## Run

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest              # behavior tests
.venv/bin/python -m evaluation.run      # 12 fault scenarios -> evaluation/reports/latest.md
.venv/bin/uvicorn orbit.api:app         # API; docs at /docs
```

Demo over the API: `POST /api/sim/inject {"name":"bad_deploy","delay":228}` → `POST /api/sim/advance {"seconds":300}`
→ `POST /api/detect` (investigates; stops at `AWAITING_APPROVAL`) → `POST /api/incidents/{id}/remediation/approve {"by":"you"}`.

## Pipeline (LangGraph, `orbit/graph.py`)

intake → triage (Laya severity) → collect (metrics + deployment agents) → timeline → generate hypotheses →
**test hypotheses against live telemetry** → RAG (runbooks + incident memory) → RCA → remediation candidates →
Laya action/risk/approval → **policy gate** → [human approval] → execute → **verify recovery** → memory | replan | escalate.

Safety properties (all covered by `tests/test_orbit.py`):
- Tools are an allowlist with exact typed params; no shell, no free-form commands (`orbit/tools.py`).
- Final approval = most restrictive of Laya, per-action policy, and RCA confidence (`orbit/policy.py`, `policies/policy.yaml`). A 99%-confident rollback still needs a human.
- Success is decided by metrics returning to healthy thresholds at T+0/30/60/120/300s, never by the command's exit status (`orbit/verify.py`).
- Max 3 attempts, then escalate. Rejected approval = nothing executes.
- Hash-chained audit log with secret redaction (`orbit/store.py`).
- Historical incidents are evidence (a small score nudge), never instructions.

## Honest status

**Laya is not integrated.** `orbit/laya.py` defines the decision contract and a transparent `HeuristicLaya`
baseline (decisions are logged as `laya-heuristic`). The real model plugs in by implementing `decide(category, payload)`.
Its label set also needs `cache`, `cpu`, `memory` added to the hypothesis categories. No Laya-vs-LLM claim can be made yet.

Evaluation numbers are measured on the **simulator** (virtual time) and measure the pipeline, not production.
Latest: RCA 11/12, recovered-or-correctly-escalated 12/12. The miss, `db_exhaustion_decoy_deploy`, is a real limit:
with metrics only, a benign deploy shortly before a DB leak is indistinguishable from a bad deploy. ORBIT rolls back the
wrong thing, verification fails, it replans and then fixes it. Log/trace evidence is what should resolve this.
"Wrong-action rate" counts actions outside the ground-truth fix set because the simulator cannot make things worse.

## Not built yet (deliberate)

| Spec item | State |
|---|---|
| Log agent, Trace agent | needs real Loki/Tempo or simulator-emitted logs/traces — next |
| Prometheus/Loki/Tempo/OTel stack, Docker Compose | simulator implements the target interface in-process; adapter is next |
| Qdrant RAG | runbooks are front-matter markdown; memory is Jaccard over symptoms (swap point marked) |
| PostgreSQL / Redis | SQLite |
| Next.js dashboard, incident page, evidence graph | not started |
| LiveKit voice | Phase 2 |
| Rollback-on-failed-remediation (undo) | no current tool has a meaningful undo; failed actions are left in place and replanned |
| `hypotheses/{id}/test`, `remediation/execute` endpoints | tests run during investigation; `approve` is the execution trigger |
| Laya vs LLM experiment, 50+ scenarios | after Laya integration |
