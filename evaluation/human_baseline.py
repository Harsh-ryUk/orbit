"""Human MTTR baseline on the real stack, so "ORBIT reduced MTTR by X%" has something to be measured against.

  python -m evaluation.human_baseline run --operator NAME [--seed N] [--scenarios a b]   # terminal 1: runs blinded sessions
  python -m evaluation.human_baseline ops <cmd> ...                                      # terminal 2: the operator's action tools
  python -m evaluation.human_baseline report                                             # compare with ORBIT's recorded runs

Protocol (docs/human-baseline.md): scenario order is shuffled and names hidden; the operator sees only the alert text the ORBIT detector
would see. Tools: Grafana (:13000), Prometheus (:19090), docs/runbooks, and the ops CLI below (the same allowlisted actions ORBIT has).
Clock: alert -> two consecutive healthy samples >= 15s apart (the same recovery criterion ORBIT's verifier uses).
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path
from statistics import median

from orbit.agents import RULES, detect, metrics_agent
from orbit.hypothesis import CATEGORIES
from orbit.real import RealTarget
from .real import SCENARIOS

DATA = Path(__file__).resolve().parent.parent / "data"
EVENTS, SESSION = DATA / "human_events.jsonl", DATA / "human_session.json"
REPORTS = Path(__file__).parent / "reports"
HUMAN_OUT, ORBIT_RUNS = REPORTS / "human_baseline.jsonl", REPORTS / "orbit_real_runs.jsonl"


# ---- operator tools -------------------------------------------------------------------------------------
def ops(argv):
    cmd, *a = argv
    if not SESSION.exists() or not json.loads(SESSION.read_text()).get("active"):
        sys.exit("no active session (the alert has not fired yet, or the session has ended)")

    def log(kind, **kw):
        with EVENTS.open("a") as f:
            f.write(json.dumps(dict(t=time.time(), kind=kind, **kw)) + "\n")

    t = RealTarget()
    if cmd == "changes":
        for c in t.changes():
            print(f"{time.time() - c['t']:6.0f}s ago  {c['service']:9s} {c['kind']:6s} {c['previous']} -> {c['ref']}{'  (rolled back)' if c['rolled_back'] else ''}")
        print(f"current: versions={t.state['versions']} configs={t.state['configs']}")
    elif cmd in ("restart", "clearcache"):
        log(cmd, service=a[0])
        print(t.apply("restart_service" if cmd == "restart" else "clear_cache", service=a[0])["detail"])
    elif cmd == "rollback":  # rollback <service> <previous version/config from `ops changes`>
        try:
            print(t.apply("rollback_deployment", service=a[0], target_version=a[1])["detail"])
            log("rollback", service=a[0], to=a[1])
        except ValueError as e:
            log("failed_action", action="rollback", error=str(e))
            print("failed:", e)
    elif cmd == "diagnose":  # diagnose <category>: record your root-cause call (does not stop the clock)
        if a[0] not in CATEGORIES + ["unknown"]:
            sys.exit(f"category must be one of {CATEGORIES + ['unknown']}")
        log("diagnose", category=a[0])
        print("recorded")
    elif cmd == "escalate":  # you judge there is no safe fix you can apply: ends the session
        log("escalate")
        print("recorded: escalating to a human owner")
    else:
        sys.exit("ops commands: changes | restart <svc> | clearcache <svc> | rollback <svc> <prev> | diagnose <category> | escalate")


# ---- session runner ---------------------------------------------------------------------------------------
def healthy(target, anoms):
    m = target.metrics()
    return all(k in m and RULES[a["metric"]][1](m[k], a["baseline"]) for a in anoms for k in [(a["service"], a["metric"])])


def session(target, sc, i, n, operator, warm, timeout):
    print(f"\n=== Session {i}/{n}: resetting stack, then {warm}s of healthy traffic. Do not look at the system yet. ===", flush=True)
    DATA.mkdir(exist_ok=True)
    SESSION.write_text(json.dumps(dict(active=False)))
    EVENTS.write_text("")
    target.reset()
    target.wait(warm)
    t_fault = target.now()
    sc.setup(target)
    hit, end = None, time.time() + 600
    while not hit and time.time() < end:
        hit = detect(target)
        target.wait(5)
    if not hit:
        print("(the fault was not detected; session discarded)")
        return None
    anoms, t_alert = metrics_agent(target), target.now()
    SESSION.write_text(json.dumps(dict(active=True)))
    print(f"\n!!! ALERT  {hit[0]}: {hit[1]}\n    Clock started. Tools: Grafana http://localhost:13000 (dashboard: Shop golden signals), Prometheus :19090,\n"
          f"    docs/runbooks, `python -m evaluation.human_baseline ops ...` (changes|restart|clearcache|rollback|diagnose|escalate)\n"
          f"    Resolve it, or `ops escalate` if there is no safe fix. Recovery is detected automatically.", flush=True)
    outcome, t_done, first_ok = None, None, None
    while time.time() - t_alert < timeout and not outcome:
        target.wait(5)
        ev = [e for e in map(json.loads, filter(None, EVENTS.read_text().splitlines())) if e["t"] >= t_alert]
        if any(e["kind"] == "escalate" for e in ev):
            outcome, t_done = "ESCALATED", next(e["t"] for e in ev if e["kind"] == "escalate")
        elif healthy(target, anoms) and any(e["kind"] in ("restart", "rollback", "clearcache") for e in ev):
            first_ok = first_ok or time.time()
            if time.time() - first_ok >= 15:
                outcome, t_done = "RECOVERED", time.time()
        else:
            first_ok = None
    ev = [e for e in map(json.loads, filter(None, EVENTS.read_text().splitlines())) if e["t"] >= t_alert]
    SESSION.write_text(json.dumps(dict(active=False)))
    acts = [e for e in ev if e["kind"] in ("restart", "rollback", "clearcache")]
    tool = {"restart": "restart_service", "rollback": "rollback_deployment", "clearcache": "clear_cache"}
    diag = next((e["category"] for e in ev if e["kind"] == "diagnose"), None)
    row = dict(operator=operator, scenario=sc.name, order=i, alert_reason=hit[1], outcome=outcome or "TIMEOUT",
               expected="ESCALATED" if not sc.fix else "RECOVERED", time_to_resolution_s=t_done and t_done - t_alert,
               fault_to_resolution_s=t_done and t_done - t_fault, detect_latency_s=t_alert - t_fault,
               time_to_first_action_s=acts and acts[0]["t"] - t_alert or None, diagnosis=diag, diagnosis_ok=diag == sc.category,
               actions=[tool[e["kind"]] for e in acts], n_wrong=sum(tool[e["kind"]] not in sc.fix for e in acts),
               failed_actions=sum(e["kind"] == "failed_action" for e in ev), run_at=time.time())
    print(f"-> recorded: {row['outcome']} in {row['time_to_resolution_s'] and round(row['time_to_resolution_s'])}s", flush=True)
    return row


def run(args):
    scs = [s for s in SCENARIOS if not args.scenarios or s.name in args.scenarios]
    random.Random(args.seed).shuffle(scs)
    target = RealTarget()
    out = Path(args.out)
    for i, sc in enumerate(scs, 1):
        row = session(target, sc, i, len(scs), args.operator, args.warm, args.timeout)
        if row:
            with out.open("a") as f:
                f.write(json.dumps(row) + "\n")
    target.reset()
    print(f"\nDone. {len(scs)} sessions. Scenario names stay hidden until you run `report`.")


# ---- comparison --------------------------------------------------------------------------------------------
def load(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()] if Path(p).exists() else []


def med(xs):
    xs = [x for x in xs if x is not None]
    return (median(xs), len(xs)) if xs else (None, 0)


def report(args):
    H, O = load(args.human), load(ORBIT_RUNS)
    names = sorted({r["scenario"] for r in H})
    L = ["# Human baseline vs ORBIT (real docker stack)", "",
         f"Operators: {sorted({r['operator'] for r in H}) or 'none'}. Times in seconds from the alert (detector trigger). "
         "ORBIT's rollback approvals are granted instantly in these runs, so its times EXCLUDE human approval wait; the human's include everything.", "",
         "| scenario | human median (n) | ORBIT median (n) | reduction | human diag ok | ORBIT RCA ok |", "|---|---|---|---|---|---|"]
    ratios = []
    for n in names:
        h = [r for r in H if r["scenario"] == n and r["outcome"] == r["expected"]]
        o = [r for r in O if r["name"] == n and r.get("final") == r.get("expected")]
        (hm, hn), (om, on) = med([r["time_to_resolution_s"] for r in h]), med([r.get("time_to_resolution_s") for r in o])
        red = (1 - om / hm) if hm and om is not None else None
        if red is not None:
            ratios.append(red)
        hd = [r["diagnosis_ok"] for r in H if r["scenario"] == n]
        od = [r["rca_ok"] for r in O if r["name"] == n and "rca_ok" in r]
        L.append(f"| {n} | {hm and round(hm)} ({hn}) | {om and round(om)} ({on}) | {red is not None and f'{red:.0%}' or '-'} | "
                 f"{sum(hd)}/{len(hd)} | {sum(od)}/{len(od)} |")
    if ratios:
        L += ["", f"Median per-scenario reduction: {median(ratios):.0%} (range {min(ratios):.0%} to {max(ratios):.0%}) over {len(ratios)} scenarios.",
              f"Human outcomes: {sum(r['outcome'] == r['expected'] for r in H)}/{len(H)} correct; wrong actions: {sum(r['n_wrong'] for r in H)}."]
    L += ["", "Read with care: small n, operators who know the system, one stack on one laptop. A reduction figure is only as good as the sessions behind it."]
    print("\n".join(L))
    (REPORTS / "human_vs_orbit.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["ops"]:
        ops(sys.argv[2:])
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("mode", choices=["run", "report"])
        ap.add_argument("--operator", default="anon")
        ap.add_argument("--seed", type=int, default=7)
        ap.add_argument("--scenarios", nargs="*")
        ap.add_argument("--warm", type=int, default=150)
        ap.add_argument("--timeout", type=int, default=900)
        ap.add_argument("--out", default=str(HUMAN_OUT))
        ap.add_argument("--human", default=str(HUMAN_OUT))
        a = ap.parse_args()
        run(a) if a.mode == "run" else report(a)
