"""LangGraph incident workflow: triage -> evidence -> hypotheses -> RCA -> Laya -> policy -> execute -> verify."""
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import hypothesis as hyp
from . import tools as toolbox
from .agents import deployment_agent, fmt, metrics_agent, timeline
from .laya import HeuristicLaya
from .policy import Policy
from .rag import load_runbooks, retrieve
from .verify import verify

ROOT = Path(__file__).resolve().parent.parent


class IncidentState(TypedDict, total=False):
    incident_id: str
    iteration: int
    tried: list
    anomalies: list
    changes: list
    hypotheses: list
    root_cause: dict
    candidates: list
    selected_action: dict
    laya_decision: dict
    policy_decision: dict
    approval: dict
    execution_result: dict
    recovery_result: dict
    final_status: str


class Orbit:
    def __init__(self, target, store, laya=None, policy=None, runbooks=None):
        self.target, self.store = target, store
        self.laya = laya or HeuristicLaya()
        self.policy = policy or Policy(ROOT / "policies" / "policy.yaml")
        self.runbooks = runbooks or load_runbooks(ROOT / "docs" / "runbooks")
        self.graph = self._build()

    # ---- public ---------------------------------------------------------------
    def open_incident(self, service, trigger):
        inc = self.store.create(service=service, environment="production", severity=None, trigger=trigger,
                                started_at=self.target.now(), resolved_at=None, root_cause_confidence=None)
        self.store.audit(incident_id=inc["id"], agent="incident_manager", decision="opened", trigger=trigger)
        return inc

    def investigate(self, id):
        self.graph.invoke({"incident_id": id}, {"configurable": {"thread_id": id}})
        return self.store.get(id)

    def approve(self, id, by, approved=True):
        cfg = {"configurable": {"thread_id": id}}
        if self.store.get(id)["status"] != "AWAITING_APPROVAL":
            raise ValueError("incident is not awaiting approval")
        self.store.audit(incident_id=id, agent="human", decision="approved" if approved else "rejected", approved_by=by)
        self.graph.update_state(cfg, {"approval": {"approved": approved, "by": by}})
        self.graph.invoke(None, cfg)
        return self.store.get(id)

    # ---- helpers --------------------------------------------------------------
    def _set(self, id, status, **f):
        return self.store.update(id, status=status, **f)

    def _ev(self, id, source, typ, content, relevance="high"):
        inc = self.store.get(id)
        e = dict(id=f"E{len(inc['evidence']) + 1}", source=source, type=typ, timestamp=self.target.now(),
                 content=content, relevance=relevance)
        self.store.update(id, evidence=inc["evidence"] + [e])

    def _decide(self, id, category, payload):
        d = self.laya.decide(category, payload)
        self.store.audit(incident_id=id, agent=category, decision_engine=d.engine, decision=d.label,
                         confidence=d.confidence, rationale=d.rationale)
        return d

    # ---- graph ----------------------------------------------------------------
    def _build(self):
        S, st, tg = self, self.store, self.target

        def intake(s):
            S._set(s["incident_id"], "INVESTIGATING")
            return dict(iteration=0, tried=[])

        def triage(s):
            inc = st.get(s["incident_id"])
            anoms = metrics_agent(tg)
            err = tg.metrics().get((inc["service"], "error_rate"), 0.0)
            d = S._decide(inc["id"], "severity", dict(error_rate=err, services_affected=len({a["service"] for a in anoms})))
            st.update(inc["id"], severity=d.label)
            return {}

        def collect(s):
            id = s["incident_id"]
            anoms = metrics_agent(tg)
            for a in anoms:
                S._ev(id, "metrics", "anomaly", fmt(a))
            onset = min((a["onset"] for a in anoms), default=tg.now())
            changes = deployment_agent(tg, onset)
            for c in changes:
                S._ev(id, "deployment", c["kind"], f"{c['kind']} {c['service']} {c['previous']} -> {c['ref']} "
                      f"{c['delta_s']:.0f}s before onset (correlation {c['correlation']})")
            return dict(anomalies=anoms, changes=changes)

        def build_timeline(s):
            st.update(s["incident_id"], timeline=timeline(s["anomalies"], s["changes"], tg.now()))
            return {}

        def generate(s):
            hs = hyp.generate(s["anomalies"], s["changes"])
            S._set(s["incident_id"], "HYPOTHESIS_FORMED", hypotheses=hs)
            return dict(hypotheses=hs)

        def test(s):
            id = s["incident_id"]
            hs = hyp.test_all(s["hypotheses"], st.get(id)["service"], s["anomalies"], s["changes"])
            for h in hs:
                for t in h["tests"]:
                    S._ev(id, "hypothesis_test", h["category"], f"{h['category']}: predicts '{t['prediction']}' -> {t['observed']} "
                          f"({'+' if t['weight'] > 0 else ''}{t['weight']})", "medium")
            st.update(id, hypotheses=hs)
            return dict(hypotheses=hs)

        def rag(s):
            id, hs = s["incident_id"], s["hypotheses"]
            for h in hs[:3]:
                for rb in retrieve(S.runbooks, h["category"]):
                    S._ev(id, "rag", "runbook", f"{rb['source']}: {rb['body']}", "medium")
            symptoms = {a["metric"] for a in s["anomalies"]}
            for m in st.similar(st.get(id)["service"], symptoms):
                S._ev(id, "memory", "similar_incident", f"{m['incident_id']} (similarity {m['similarity']}): root cause "
                      f"{m['category']}, fixed by {m['remediation']}, result {m['result']}", "medium")
                if m["result"] == "RECOVERED":  # history is evidence, a nudge, never an instruction
                    for h in hs:
                        if h["category"] == m["category"]:
                            h["score"] += 0.5 * m["similarity"]
                            h["tests"].append(dict(prediction="similar past incident", observed=m["incident_id"], weight=0.5 * m["similarity"]))
            hs = hyp.normalize(hs)
            st.update(id, hypotheses=hs)
            return dict(hypotheses=hs)

        def rca(s):
            id, h = s["incident_id"], s["hypotheses"][0]
            inc = st.get(id)
            r = dict(root_cause=f"{h['description']} on {inc['service']}", category=h["category"], confidence=h["confidence"],
                     supporting_evidence=h["supporting"], contradicting_evidence=h["contradicting"],
                     affected_services=sorted({a["service"] for a in s["anomalies"]}), timeline=inc["timeline"])
            S._set(id, "RCA_CONFIRMED", root_cause=r["root_cause"], root_cause_confidence=h["confidence"], rca=r)
            S.store.audit(incident_id=id, agent="rca", decision=h["category"], confidence=h["confidence"])
            return dict(root_cause=r)

        def remediate(s):
            id, svc = s["incident_id"], st.get(s["incident_id"])["service"]
            cands = []
            for rank, h in enumerate(s["hypotheses"][:3], 1):
                if h["confidence"] < 0.05:
                    continue
                kind = "config" if h["category"] == "configuration" else "deploy"
                prev = next((c["previous"] for c in reversed(s["changes"]) if c["service"] == svc and c["kind"] == kind
                             and not c["rolled_back"]), None)
                for rb in retrieve(S.runbooks, h["category"]):
                    for line in rb["actions"]:
                        name, *kv = line.split()
                        params = {k: v.replace("$service", svc).replace("$previous_version", prev or "") for k, v in (x.split("=") for x in kv)}
                        if name in toolbox.TOOLS and all(params.values()):
                            cands.append(dict(key=f"{name}:{sorted(params.items())}", tool=name, params=params,
                                              label=toolbox.TOOLS[name].label, category=h["category"], rank=rank, runbook=rb["source"]))
            S._set(id, "REMEDIATION_PROPOSED")
            return dict(candidates=cands)

        def decide(s):
            id, rc = s["incident_id"], s["root_cause"]["confidence"]
            a = S._decide(id, "action", dict(candidates=s["candidates"], tried=s["tried"], rca_confidence=rc))
            if a.label == toolbox.NO_ACTION:
                return dict(selected_action=None, laya_decision=a.dict(), policy_decision=dict(decision="BLOCK", reasons=["no action"]), approval=None)
            c = next(c for c in s["candidates"] if c["key"] not in s["tried"] and c["label"] == a.label)
            risk = S._decide(id, "risk", dict(tool=c["tool"]))
            appr = S._decide(id, "approval", dict(risk=risk.label, confidence=a.confidence))
            pol = S.policy.decide(c["tool"], appr.label, rc)
            S.store.audit(incident_id=id, agent="policy", decision=pol["decision"], action=c["tool"], reasons=pol["reasons"])
            rec = dict(id=f"A{len(st.get(id)['actions']) + 1}", action_type=c["tool"], parameters=c["params"], risk=risk.label,
                       approval_status="pending" if pol["decision"] == "HUMAN_APPROVAL" else "auto", execution_status="not_started",
                       executed_at=None, laya=a.dict(), policy=pol)
            st.update(id, actions=st.get(id)["actions"] + [rec])
            if pol["decision"] == "HUMAN_APPROVAL":
                S._set(id, "AWAITING_APPROVAL")
            return dict(selected_action=c, laya_decision=a.dict(), policy_decision=pol, approval=None)

        def route_policy(s):
            return {"AUTO_EXECUTE": "execute", "HUMAN_APPROVAL": "await_approval"}.get(s["policy_decision"]["decision"], "escalate")

        def await_approval(s):  # graph is interrupted before this node; resumes once update_state sets approval
            ap = s.get("approval") or {}
            inc = st.get(s["incident_id"])
            acts = inc["actions"]
            acts[-1]["approval_status"] = "approved" if ap.get("approved") else "rejected"
            st.update(inc["id"], actions=acts, approvals=inc["approvals"] + [ap])
            return {}

        def route_approval(s):
            return "execute" if (s.get("approval") or {}).get("approved") else "escalate"

        def execute(s):
            id, c = s["incident_id"], s["selected_action"]
            S._set(id, "EXECUTING")
            try:
                res = toolbox.run(tg, c["tool"], c["params"])
            except Exception as e:  # a failed execution counts as a failed attempt, never a crash
                res = dict(ok=False, detail=str(e))
            inc = st.get(id)
            acts = inc["actions"]
            acts[-1].update(execution_status="success" if res["ok"] else "failed", executed_at=tg.now(), result=res.get("detail"))
            st.update(id, actions=acts)
            S.store.audit(incident_id=id, agent="executor", action=c["tool"], parameters=c["params"], execution="success" if res["ok"] else "failed",
                          approved_by=(s.get("approval") or {}).get("by", "policy"))
            return dict(execution_result=res)

        def verify_node(s):
            id, c = s["incident_id"], s["selected_action"]
            S._set(id, "VERIFYING")
            v = verify(tg, s["anomalies"]) if s["execution_result"]["ok"] else dict(status="FAILED", healthy=0, total=len(s["anomalies"]), samples=[], rows=[])
            d = S._decide(id, "recovery", dict(verification=v))
            st.update(id, recovery=v["rows"])
            tried = s["tried"] + [c["key"]]
            if v["status"] == "RECOVERED":
                return dict(recovery_result=v, tried=tried)
            # ponytail: no undo executed; restart/clear_cache have nothing to undo, scale-up is harmless, a failed rollback stays rolled back.
            S._set(id, "INVESTIGATING")
            return dict(recovery_result=v, tried=tried, iteration=s["iteration"] + 1)

        def route_verify(s):
            if s["recovery_result"]["status"] == "RECOVERED":
                return "memory"
            e = S._decide(s["incident_id"], "escalation", dict(attempts=s["iteration"], max_attempts=S.policy.cfg["max_attempts"],
                                                               no_action=False))
            return "escalate" if e.label == "ESCALATE" else "decide"

        def memory(s):
            id, c = s["incident_id"], s["selected_action"]
            inc = st.get(id)
            now = tg.now()
            mttr = now - inc["started_at"]
            S._set(id, "RECOVERED", resolved_at=now, mttr_s=mttr, final_status="RECOVERED")
            st.remember(id, dict(incident_id=id, service=inc["service"], symptoms=sorted({a["metric"] for a in s["anomalies"]}),
                                 category=s["root_cause"]["category"], root_cause=inc["root_cause"], remediation=c["tool"],
                                 result="RECOVERED", mttr=mttr))
            S.store.audit(incident_id=id, agent="memory", decision="stored", mttr_s=mttr)
            return dict(final_status="RECOVERED")

        def close(s):
            S._set(s["incident_id"], "CLOSED")
            return {}

        def escalate(s):
            id = s["incident_id"]
            why = "approval rejected" if (s.get("approval") or {}).get("approved") is False else \
                "no safe automated action" if not s.get("selected_action") else "remediation attempts exhausted or blocked"
            S._set(id, "ESCALATED", final_status="ESCALATED", escalation_reason=why, resolved_at=None)
            S.store.audit(incident_id=id, agent="escalation", decision="ESCALATE", rationale=why)
            return dict(final_status="ESCALATED")

        g = StateGraph(IncidentState)
        for n, f in [("intake", intake), ("triage", triage), ("collect", collect), ("timeline", build_timeline), ("generate", generate),
                     ("test", test), ("rag", rag), ("rca", rca), ("remediate", remediate), ("decide", decide), ("await_approval", await_approval),
                     ("execute", execute), ("verify", verify_node), ("memory", memory), ("close", close), ("escalate", escalate)]:
            g.add_node(n, f)
        g.add_edge(START, "intake")
        for a, b in zip(["intake", "triage", "collect", "timeline", "generate", "test", "rag", "rca", "remediate", "decide"],
                        ["triage", "collect", "timeline", "generate", "test", "rag", "rca", "remediate", "decide", "x"]):
            if b != "x":
                g.add_edge(a, b)
        g.add_conditional_edges("decide", route_policy, ["execute", "await_approval", "escalate"])
        g.add_conditional_edges("await_approval", route_approval, ["execute", "escalate"])
        g.add_edge("execute", "verify")
        g.add_conditional_edges("verify", route_verify, ["memory", "decide", "escalate"])
        g.add_edge("memory", "close")
        g.add_edge("close", END)
        g.add_edge("escalate", END)
        return g.compile(checkpointer=MemorySaver(), interrupt_before=["await_approval"])
