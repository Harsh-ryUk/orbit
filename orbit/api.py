"""FastAPI surface. `uvicorn orbit.api:app` runs ORBIT against the in-process simulator."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from simulator.sim import Sim
from .agents import detect
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


def create_app(orbit=None):
    if orbit is None:
        sim = Sim()
        sim.wait(1200)  # healthy history so baselines exist
        data = Path(__file__).resolve().parent.parent / "data"
        data.mkdir(exist_ok=True)
        orbit = Orbit(sim, Store(str(data / "orbit.db"), data / "audit.jsonl"))
    app = FastAPI(title="ORBIT", description="Observe. Reason. Act. Verify.")
    store, sim = orbit.store, orbit.target

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

    # simulator controls (dev only; real targets don't expose these)
    @app.post("/api/sim/inject")
    def sim_inject(b: Inject):
        sim.inject(b.name, b.service, b.delay)
        return dict(ok=True)

    @app.post("/api/sim/advance")
    def sim_advance(b: Advance):
        sim.wait(b.seconds)
        return dict(now=sim.now())

    @app.get("/api/sim/metrics")
    def sim_metrics():
        return {f"{s}.{m}": round(v, 3) for (s, m), v in sim.metrics().items()}

    return app


app = create_app()
