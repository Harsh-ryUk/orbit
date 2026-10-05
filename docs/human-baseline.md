# Human MTTR baseline: protocol

Purpose: measure how long a person takes on the same incidents ORBIT handles, so an MTTR comparison is real.

**Operator.** Ideally someone who did not write ORBIT and has not read `evaluation/` or `apps/shop` (the fault definitions live there).
A teammate on the on-call rotation is best. One operator is acceptable but state it.

**Setup.** Stack up (`docker compose -p orbit -f infra/docker/docker-compose.yml up -d`). Two terminals in the repo root.

**Terminal 1** (leave running, ~10 min per scenario): `.venv/bin/python -m evaluation.human_baseline run --operator <name>`.
It shuffles scenarios and hides their names. After ~3 minutes of healthy traffic a fault is injected; when the alert fires it prints
the alert text and starts the clock.

**You may use:** Grafana http://localhost:13000 (dashboard "Shop golden signals", plus Explore for Loki logs and Tempo traces),
Prometheus http://localhost:19090, `docs/runbooks/`, and these action commands in terminal 2 (the same allowlisted actions ORBIT has):

```
.venv/bin/python -m evaluation.human_baseline ops changes            # deploy / config history
.venv/bin/python -m evaluation.human_baseline ops restart <service>  # orders|payments|users|redis
.venv/bin/python -m evaluation.human_baseline ops rollback <service> <previous>   # <previous> from `ops changes`
.venv/bin/python -m evaluation.human_baseline ops clearcache redis
.venv/bin/python -m evaluation.human_baseline ops diagnose <deployment|configuration|database|dependency|network|cache|cpu|memory>
.venv/bin/python -m evaluation.human_baseline ops escalate           # no safe fix available: ends the session
```

**Rules.** Do not read `evaluation/`, `apps/shop/`, or `orbit/real.py` before finishing all sessions. Run `ops diagnose` when you decide
the root cause (it does not stop the clock). Recovery is detected automatically (same criterion as ORBIT: healthy, then still healthy 15s later).
Take no breaks mid-session; between sessions is fine. Fifteen minutes without resolution is recorded as a timeout.

**Then:** `.venv/bin/python -m evaluation.human_baseline report` writes `evaluation/reports/human_vs_orbit.md`.

**Known biases (state them with any number).** Operator knows the stack layout and has the dashboard pre-built (faster than a real on-call
who must find things), which makes the human baseline optimistic, so a measured reduction is conservative. ORBIT's times exclude human
approval wait for rollbacks. The faults are the same seven types ORBIT was developed against. Small n.
