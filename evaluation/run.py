"""Run every scenario through ORBIT and report measured accuracy. `python -m evaluation.run`"""
import time
from pathlib import Path

from orbit.agents import detect
from orbit.graph import Orbit
from orbit.store import Store
from simulator.sim import Sim
from .scenarios import SCENARIOS


def run_one(sc, laya=None):
    sim, store = Sim(), Store()
    orbit = Orbit(sim, store, laya=laya)
    sim.wait(1200)                          # healthy history for baselines
    t_fault = sim.now()
    sc.setup(sim)
    hit = None
    for _ in range(240):                    # poll the detector every 5s for up to 20 min
        hit = detect(sim)
        if hit:
            break
        sim.wait(5)
    r = dict(name=sc.name, detected=bool(hit))
    if not hit:
        return r
    inc = orbit.open_incident(*hit) if False else orbit.open_incident(hit[0], dict(reason=hit[1]))
    t0 = time.perf_counter()
    inc = orbit.investigate(inc["id"])
    approvals = 0
    while inc["status"] == "AWAITING_APPROVAL":
        approvals += 1
        inc = orbit.approve(inc["id"], by="eval-human")
    done = [a for a in inc["actions"] if a["execution_status"] != "not_started"]
    cat = (inc["rca"] or {}).get("category")
    recovered = inc["final_status"] == "RECOVERED"
    wrong = [a for a in done if a["action_type"] not in sc.fix]
    r.update(detect_latency_s=inc["started_at"] - t_fault, rca_ok=cat == sc.category, rca_conf=(inc["rca"] or {}).get("confidence"),
             service_ok=inc["service"] == sc.service, expected="ESCALATED" if not sc.fix else "RECOVERED",
             final=inc["final_status"], handled=inc["final_status"] == ("RECOVERED" if sc.fix else "ESCALATED"),
             actions=[a["action_type"] for a in done], n_actions=len(done), n_wrong=len(wrong), approvals=approvals,
             human=bool(approvals) or inc["final_status"] == "ESCALATED", mttr_s=inc.get("mttr_s") if recovered else None,
             investigate_ms=(time.perf_counter() - t0) * 1000, severity=inc["severity"], audit_ok=store.audit_ok())
    return r


def summarize(rs):
    n = len(rs)
    det = [r for r in rs if r["detected"]]
    fixable = [r for r in det if r["expected"] == "RECOVERED"]
    acts = sum(r["n_actions"] for r in det)
    mt = [r["mttr_s"] for r in det if r["mttr_s"]]
    return {
        "scenarios": n,
        "detection accuracy": len(det) / n,
        "RCA accuracy": sum(r["rca_ok"] for r in det) / n,
        "handled correctly (recovered or correctly escalated)": sum(r["handled"] for r in det) / n,
        "recovery success (fixable incidents)": sum(r["final"] == "RECOVERED" for r in fixable) / max(len(fixable), 1),
        "remediation accuracy (recovered / actions executed)": sum(r["final"] == "RECOVERED" for r in det) / max(acts, 1),
        "wrong-action rate (actions outside ground-truth fix set)": sum(r["n_wrong"] for r in det) / max(acts, 1),
        "human intervention rate": sum(r["human"] for r in det) / n,
        "mean MTTR, simulated seconds": sum(mt) / len(mt) if mt else None,
        "mean investigation wall time, ms": sum(r["investigate_ms"] for r in det) / max(len(det), 1),
    }


def report(rs, s):
    L = ["# ORBIT evaluation (simulator)", "", "Virtual-time simulator; numbers measure the pipeline, not production.", "", "## Summary", ""]
    L += [f"- {k}: {v:.1%}" if isinstance(v, float) and v <= 1 else f"- {k}: {v:.1f}" if isinstance(v, float) else f"- {k}: {v}" for k, v in s.items() if v is not None]
    L += ["", "## Scenarios", "", "| scenario | RCA | conf | final | actions | approvals | MTTR s |", "|---|---|---|---|---|---|---|"]
    for r in rs:
        if not r["detected"]:
            L.append(f"| {r['name']} | NOT DETECTED | | | | | |")
            continue
        L.append(f"| {r['name']} | {'ok' if r['rca_ok'] else 'WRONG'} | {r['rca_conf']:.0%} | {r['final']} (want {r['expected']}) | "
                 f"{', '.join(r['actions']) or '-'} | {r['approvals']} | {r['mttr_s'] and round(r['mttr_s'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    rs = [run_one(sc) for sc in SCENARIOS]
    out = report(rs, summarize(rs))
    p = Path(__file__).parent / "reports" / "latest.md"
    p.write_text(out)
    print(out)
