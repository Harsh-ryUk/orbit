import pytest
from fastapi.testclient import TestClient

from evaluation.scenarios import SCENARIOS
from orbit import tools
from orbit.agents import detect
from orbit.api import create_app
from orbit.graph import Orbit
from orbit.policy import Policy
from orbit.store import Store
from simulator.sim import Sim

SC = {s.name: s for s in SCENARIOS}


def incident(name, store=None, sim=None):
    sim = sim or Sim()
    orbit = Orbit(sim, store or Store())
    sim.wait(1200)
    SC[name].setup(sim)
    while not detect(sim):
        sim.wait(5)
    s, why = detect(sim)
    return sim, orbit, orbit.investigate(orbit.open_incident(s, dict(reason=why))["id"])


def test_high_risk_waits_for_human_then_recovers_and_is_audited():
    sim, orbit, inc = incident("bad_deploy")
    assert inc["status"] == "AWAITING_APPROVAL" and inc["rca"]["category"] == "deployment"
    assert sim.metrics()[("orders", "error_rate")] > 0.2          # nothing executed yet
    assert inc["actions"][0]["execution_status"] == "not_started"
    inc = orbit.approve(inc["id"], "alice")
    assert inc["status"] == "CLOSED" and inc["final_status"] == "RECOVERED" and inc["mttr_s"] > 0
    assert sim.metrics()[("orders", "error_rate")] < 0.03        # recovery verified by telemetry
    assert orbit.store.audit_ok() and any(e for e in orbit.store.audit_log if "alice" in e)


def test_low_risk_auto_executes_without_approval():
    _, _, inc = incident("memory_leak")
    assert inc["final_status"] == "RECOVERED" and inc["approvals"] == []


def test_rejected_approval_escalates_and_executes_nothing():
    sim, orbit, inc = incident("bad_deploy")
    inc = orbit.approve(inc["id"], "bob", approved=False)
    assert inc["final_status"] == "ESCALATED" and inc["actions"][0]["execution_status"] == "not_started"
    assert sim.metrics()[("orders", "error_rate")] > 0.2


def test_no_safe_action_escalates():
    _, _, inc = incident("dependency_down")
    assert inc["final_status"] == "ESCALATED" and inc["actions"] == [] and inc["rca"]["category"] == "dependency"


def _blind(sim):
    sim.logs = sim.traces = lambda *a, **k: []   # logs/traces backend down
    return sim


def test_traces_disambiguate_benign_deploy_from_db_leak():
    _, _, inc = incident("db_exhaustion_decoy_deploy")
    assert inc["rca"]["category"] == "database" and [a["action_type"] for a in inc["actions"]] == ["restart_service"]
    assert any(e["source"] == "traces" for e in inc["evidence"]) and any(e["source"] == "logs" for e in inc["evidence"])


def test_missing_logs_and_traces_degrade_to_metrics_only_and_replan():
    sim, orbit, inc = incident("db_exhaustion_decoy_deploy", sim=_blind(Sim()))
    while inc["status"] == "AWAITING_APPROVAL":
        inc = orbit.approve(inc["id"], "carol")
    assert not any(e["source"] in ("logs", "traces") for e in inc["evidence"])
    assert [a["action_type"] for a in inc["actions"]] == ["rollback_deployment", "restart_service"]  # wrong first guess, then replan
    assert inc["final_status"] == "RECOVERED"


def test_log_and_trace_agents_find_what_changed():
    from orbit.agents import log_agent, metrics_agent, trace_agent
    sim = Sim(); sim.wait(1200); sim.inject("bad_deploy", "orders"); sim.wait(90)
    onset = min(a["onset"] for a in metrics_agent(sim))
    logs, tr = log_agent(sim, onset), trace_agent(sim, "orders", onset)
    assert logs[0]["is_new"] and "pool exhausted" in logs[0]["template"] and "<n>" in logs[0]["template"]
    assert tr["new_ops"] == ["OrderRepository.fetch_batch"] and tr["bottleneck"]["name"] == "db.pool.acquire"
    assert tr["path"][0] == "POST /orders" and tr["path"][-1] == "db.pool.acquire"


def test_policy_never_lets_confidence_authorize_high_risk():
    p = Policy("policies/policy.yaml")
    assert p.decide("rollback_deployment", "AUTO_EXECUTE", 0.99)["decision"] == "HUMAN_APPROVAL"
    assert p.decide("restart_service", "AUTO_EXECUTE", 0.4)["decision"] == "HUMAN_APPROVAL"
    assert p.decide("restart_service", "AUTO_EXECUTE", 0.9)["decision"] == "AUTO_EXECUTE"
    assert p.decide("rm_rf", "AUTO_EXECUTE", 1.0)["decision"] == "BLOCK"
    with pytest.raises(PermissionError):
        tools.run(Sim(), "rm_rf", {})
    with pytest.raises(ValueError):
        tools.run(Sim(), "restart_service", {"service": "orders", "cmd": "whoami"})


def test_memory_of_past_incident_becomes_evidence():
    store = Store()
    _, _, first = incident("cpu_saturation", store)
    _, _, second = incident("cpu_saturation", store)
    assert any(e["type"] == "similar_incident" and first["id"] in e["content"] for e in second["evidence"])


def test_secrets_are_redacted_in_audit():
    s = Store()
    s.audit(incident_id="x", note='api_key="sk-123" token: abc', password="hunter2")
    assert not any(x in s.audit_log[0] for x in ("sk-123", "abc", "hunter2")) and s.audit_ok()


def test_api_flow():
    sim = Sim()
    sim.wait(1200)
    c = TestClient(create_app(Orbit(sim, Store())))
    c.post("/api/sim/inject", json=dict(name="bad_deploy", service="orders", delay=60))
    assert c.post("/api/detect").json()["detected"] is False
    c.post("/api/sim/advance", json=dict(seconds=150))
    inc = c.post("/api/detect").json()["incident"]
    assert inc["status"] == "AWAITING_APPROVAL"
    assert c.get(f"/api/incidents/{inc['id']}/hypotheses").json()[0]["category"] == "deployment"
    assert c.post(f"/api/incidents/{inc['id']}/remediation/approve", json=dict(by="dev")).json()["final_status"] == "RECOVERED"
    assert c.post(f"/api/incidents/{inc['id']}/remediation/approve", json=dict(by="dev")).status_code == 409
    assert c.get("/api/audit/verify").json()["chain_ok"]


class _Masked(Sim):
    """Callers mask a Redis outage with a DB fallback: no user-facing error or latency signal at all."""
    def metrics(self):
        return {k: v for k, v in super().metrics().items() if k[1] not in ("error_rate", "p95_latency")}

    def history(self):
        return [(t, {k: v for k, v in m.items() if k[1] not in ("error_rate", "p95_latency")}) for t, m in super().history()]


def test_detector_pages_on_masked_component_outage():
    sim = _Masked()
    sim.wait(1200)
    assert detect(sim) is None                       # healthy: no page
    sim.inject("redis_down", "redis")
    sim.wait(30)
    assert detect(sim) is None                       # not sustained yet
    sim.wait(60)
    svc, why = detect(sim)
    assert svc == "orders" and "redis_up" in why     # opened on a service that lost its cache


def test_slo_breach_still_takes_priority_over_component_trigger():
    sim = Sim()
    sim.wait(1200)
    sim.inject("redis_down", "redis")                # the simulator's redis_down also breaches error rate / latency
    sim.wait(120)
    assert "redis_up" not in detect(sim)[1]
