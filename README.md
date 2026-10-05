# ORBIT — Observe. Reason. Act. Verify.

AI reliability control plane: investigate a production incident, decide under a deterministic safety policy,
execute allowlisted remediation, and **prove recovery with telemetry** before calling it resolved.

Status: **milestone 3 — the same pipeline now runs against a real OpenTelemetry → Prometheus/Loki/Tempo stack.** Full spec in the project brief.

## Run

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest              # behavior tests
.venv/bin/python -m evaluation.run      # 12 fault scenarios -> evaluation/reports/latest.md
.venv/bin/uvicorn orbit.api:app         # API; docs at /docs
```

Demo over the API: `POST /api/sim/inject {"name":"bad_deploy","delay":228}` → `POST /api/sim/advance {"seconds":300}`
→ `POST /api/detect` (investigates; stops at `AWAITING_APPROVAL`) → `POST /api/incidents/{id}/remediation/approve {"by":"you"}`.

## Real stack (docker compose)

```bash
docker compose -p orbit -f infra/docker/docker-compose.yml up -d --build   # ~1 min first time
.venv/bin/python -m evaluation.real bad_deploy redis_down                  # real-time scenarios, writes evaluation/reports/real.md
```

```
loadgen -> orders -> payments -> external (mock provider)      all emit OTLP (traces, metrics, logs)
              \-> redis, postgres                                       |
                                                                  OTel Collector
                                              Tempo (traces) <--------- + --------> Loki (logs)
                                                                      Prometheus (scrapes collector)
```
`orbit/real.py` (`RealTarget`) implements the same target interface as the simulator, so agents, graph and policy are unchanged:
PromQL for metrics/history, LogQL for logs, TraceQL for traces. Remediation runs only the four allowlisted actions through
`docker compose` on the host (no generic exec). Faults are injected by `RealTarget.inject()` (chaos tooling ORBIT's tools cannot reach):
bad deploy (v2.8.1 holds DB connections), config regression (tight timeout), connection leak, memory leak, Redis stop, provider outage.
Host ports: Prometheus 19090, Loki 13100, Tempo 13200, apps 18001-18004. Tear down: `docker compose -p orbit -f infra/docker/docker-compose.yml down -v`.

**Real-stack results (`evaluation/reports/real.md`): 7 scenarios, one run each.** RCA correct 7/7, six recovered with telemetry-verified
recovery in 65-130s (mean 77s), the provider outage correctly escalated, no wrong actions, 2 human approvals (rollbacks) and 1 escalation.
That includes the decoy case (benign deploy right before a connection leak): diagnosed `database` at 85% and fixed with a restart, no wrong rollback.
Caveats: n=1 per scenario, so no variance; the faults and the signals the app emits were authored by me alongside the hypothesis tests, and
all seven scenarios are single-fault, single-service. This shows the pipeline works on real telemetry; it does not show it generalizes to
production. CPU saturation is not available on the compose target (`scale_service` raises: no load balancer in front of replicas).
The adapter's parsing and rollback logic are covered by offline tests (`tests/test_real.py`).

## Pipeline (LangGraph, `orbit/graph.py`)

intake → triage (Laya severity) → collect (metrics, deployment, **log**, **trace** agents) → timeline → generate hypotheses →
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
Latest: RCA 12/12, recovered-or-correctly-escalated 12/12. **Read that with care:** the simulator's log messages and
span names are authored by me alongside the faults, and the hypothesis tests were tuned against these 12 scenarios.
The agent logic is generic (signature grouping with variable parts stripped, span-set diff vs baseline, latency-bottleneck
attribution, failing-path extraction), but 100% here is not evidence it will hold on real telemetry.
The ablation in `evaluation/reports/latest.md` is the meaningful result: without logs/traces RCA drops to 11/12 and the
decoy case (`db_exhaustion_decoy_deploy`: benign deploy shortly before a DB leak) rolls back the wrong thing before replanning.
Traces fix it because the benign deploy introduces no new span operations. If the logs/traces backend is down, ORBIT
degrades to metrics-only instead of failing (tested).
"Wrong-action rate" counts actions outside the ground-truth fix set because the simulator cannot make things worse.

## Not built yet (deliberate)

| Spec item | State |
|---|---|
| Prometheus/Loki/Tempo/OTel stack, Docker Compose | **done** (`infra/docker`, `orbit/real.py`); 7 real scenarios run once each |
| Qdrant RAG | runbooks are front-matter markdown; memory is Jaccard over symptoms (swap point marked) |
| PostgreSQL / Redis | SQLite |
| Next.js dashboard, incident page, evidence graph | not started |
| LiveKit voice | Phase 2 |
| Rollback-on-failed-remediation (undo) | no current tool has a meaningful undo; failed actions are left in place and replanned |
| `hypotheses/{id}/test`, `remediation/execute` endpoints | tests run during investigation; `approve` is the execution trigger |
| Laya vs LLM experiment, 50+ scenarios | after Laya integration |
