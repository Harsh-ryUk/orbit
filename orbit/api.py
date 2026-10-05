"""FastAPI surface. `uvicorn orbit.api:app` runs ORBIT against the in-process simulator."""
from pathlib import Path

import json
import os
from statistics import mean, median

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from simulator.sim import Sim
from .agents import detect, metrics_agent
from .graph import Orbit
from .store import Store


class NewIncident(BaseModel):
    service: str
    reason: str = "manual"


class Approval(BaseModel):
    by: str
    approved: bool = True


class Inject(BaseModel):
    name: str
    service: str = "orders"
    delay: float = 0.0


class Advance(BaseModel):
    seconds: float


ROOT = Path(__file__).resolve().parent.parent
HEALTH_METRICS = ["error_rate", "p95_latency", "cpu", "memory", "db_pool", "cache_hit", "dep_error_rate"]


_SIM_EVAL = {}


def _sim_eval():
    """Run the 12 simulator scenarios once per process (about 2s) and cache the per-scenario results."""
    if not _SIM_EVAL:
        from evaluation.run import run_one, summarize
        from evaluation.scenarios import SCENARIOS
        rs = [run_one(sc) for sc in SCENARIOS]
        _SIM_EVAL.update(summary=summarize(rs), scenarios=rs)
    return _SIM_EVAL


def create_app(orbit=None):
    """ORBIT_TARGET=sim (default, in-process simulator, in-memory store) or real (docker stack; needs it up)."""
    if orbit is None:
        data = ROOT / "data"
        data.mkdir(exist_ok=True)
        if os.environ.get("ORBIT_TARGET") == "real":
            from .real import RealTarget
            target = RealTarget()
            store = Store(str(data / "orbit_real.db"), data / "audit_real.jsonl")
        else:
            target = Sim()
            target.wait(1200)  # healthy history so baselines exist
            store = Store()    # ponytail: incidents on the simulator are demo state; in-memory so a restart is a clean slate
        orbit = Orbit(target, store)
    app = FastAPI(title="ORBIT", description="Observe. Reason. Act. Verify.")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
    store, sim = orbit.store, orbit.target
    is_sim = isinstance(sim, Sim)

    def inc(id):
        i = store.get(id)
        if not i:
            raise HTTPException(404, "incident not found")
        return i

    # ponytail: investigations run inline (ms against the simulator); move to a worker/queue for real telemetry latency
    @app.post("/api/incidents")
    def create(b: NewIncident):
        return orbit.open_incident(b.service, dict(reason=b.reason))

    @app.get("/api/incidents")
    def list_():
        return store.list()

    @app.get("/api/incidents/{id}")
    def get(id: str):
        return inc(id)

    @app.post("/api/incidents/{id}/investigate")
    def investigate(id: str):
        inc(id)
        return orbit.investigate(id)

    @app.get("/api/incidents/{id}/investigation")
    def investigation(id: str):
        i = inc(id)
        return dict(timeline=i["timeline"], evidence=i["evidence"], rca=i["rca"])

    @app.get("/api/incidents/{id}/hypotheses")
    def hypotheses(id: str):
        return inc(id)["hypotheses"]

    @app.get("/api/incidents/{id}/remediation")
    def remediation(id: str):
        return inc(id)["actions"]

    @app.post("/api/incidents/{id}/remediation/approve")
    def approve(id: str, b: Approval):
        inc(id)
        try:
            return orbit.approve(id, b.by, b.approved)
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/incidents/{id}/recovery")
    def recovery(id: str):
        return inc(id)["recovery"]

    @app.post("/api/detect")
    def detect_():
        hit = detect(sim)
        if not hit:
            return dict(detected=False)
        open_ = [i for i in store.list() if i["service"] == hit[0] and i["status"] not in ("CLOSED", "ESCALATED")]
        i = open_[0] if open_ else orbit.investigate(orbit.open_incident(hit[0], dict(reason=hit[1]))["id"])
        return dict(detected=True, incident=i)

    @app.get("/api/audit/verify")
    def audit():
        return dict(chain_ok=store.audit_ok(), events=len(store.audit_log))

    @app.get("/api/mode")
    def mode():
        return dict(target="sim" if is_sim else "real", now=sim.now())

    @app.get("/api/stats")
    def stats():
        inc = store.list()
        done = [i for i in inc if i["status"] == "CLOSED"]
        mttr = [i["mttr_s"] for i in done if i.get("mttr_s")]
        return dict(total=len(inc), open=sum(i["status"] not in ("CLOSED", "ESCALATED") for i in inc),
                    awaiting_approval=sum(i["status"] == "AWAITING_APPROVAL" for i in inc),
                    recovered=len(done), escalated=sum(i["status"] == "ESCALATED" for i in inc),
                    recovery_rate=len(done) / len(inc) if inc else None,
                    automation_rate=sum(not i["approvals"] for i in done) / len(done) if done else None,   # recovered with no human approval
                    mttr_mean_s=mean(mttr) if mttr else None, mttr_median_s=median(mttr) if mttr else None)

    @app.get("/api/health")
    def health():
        m = sim.metrics()
        anoms = {(a["service"], a["metric"]): a for a in metrics_agent(sim)}
        out = []
        for svc in sim.services:
            vals = {k[1]: v for k, v in m.items() if k[0] == svc and (k[1] in HEALTH_METRICS or k[1] == "redis_up")}
            bad = [k[1] for k in anoms if k[0] == svc]
            out.append(dict(service=svc, status="degraded" if bad else "healthy", anomalous=bad, metrics=vals))
        return out

    @app.get("/api/changes")
    def changes():
        return sorted(sim.changes(), key=lambda c: -c["t"])[:10]

    @app.get("/api/incidents/{id}/metrics")
    def inc_metrics(id: str):
        """Time series (last 20 min, <=120 points) for the incident's anomalous metrics, with their baselines."""
        i = inc(id)
        keys = {(a["service"], a["metric"]): a["baseline"] for a in i.get("anomalies") or []}
        keys.update({(i["service"], k): None for k in ("error_rate", "p95_latency")} if not keys else {})
        hist = [(t, m) for t, m in sim.history() if t >= sim.now() - 1200]
        step = max(1, len(hist) // 120)
        series = {f"{s}.{m}": [[t, mm[(s, m)]] for t, mm in hist[::step] if (s, m) in mm] for s, m in keys}
        return dict(series=series, baselines={f"{s}.{m}": b for (s, m), b in keys.items()}, started_at=i["started_at"], resolved_at=i.get("resolved_at"))

    @app.get("/api/incidents/{id}/audit")
    def inc_audit(id: str):
        inc(id)
        rows = [json.loads(l)["event"] for l in store.audit_log]
        return [r for r in rows if r.get("incident_id") == id]

    @app.get("/api/evaluation")
    def evaluation():
        reports = ROOT / "evaluation" / "reports"
        load = lambda f: [json.loads(l) for l in (reports / f).read_text().splitlines() if l.strip()] if (reports / f).exists() else []
        return dict(real=load("orbit_real_runs.jsonl"), human=load("human_baseline.jsonl"), sim=_sim_eval())

    # simulator controls (dev only; real targets don't expose these)
    def need_sim():
        if not is_sim:
            raise HTTPException(400, "simulator controls are only available with ORBIT_TARGET=sim")

    @app.post("/api/sim/inject")
    def sim_inject(b: Inject):
        need_sim()
        sim.inject(b.name, b.service, b.delay)
        return dict(ok=True)

    @app.post("/api/sim/advance")
    def sim_advance(b: Advance):
        need_sim()
        sim.wait(b.seconds)
        return dict(now=sim.now())

    @app.get("/api/sim/metrics")
    def sim_metrics():
        return {f"{s}.{m}": round(v, 3) for (s, m), v in sim.metrics().items()}

    return app


app = create_app()
