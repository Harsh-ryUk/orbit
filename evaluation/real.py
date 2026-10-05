"""Run fault scenarios against the REAL docker stack (needs it up). `python -m evaluation.real [scenario ...]`
Slow by design: every scenario resets the stack, warms up, injects, waits for detection, remediates and verifies in real time."""
import json
import sys
import time
from pathlib import Path

from orbit.real import RealTarget
from .run import ablation, report, run_one, summarize
from .scenarios import Scenario


def _decoy(t):
    t.benign_deploy("orders")
    t.wait(90)
    t.inject("db_exhaustion", "orders")


SCENARIOS = [
    Scenario("bad_deploy", lambda t: t.inject("bad_deploy", "orders"), "deployment", "orders", ("rollback_deployment",)),
    Scenario("db_exhaustion", lambda t: t.inject("db_exhaustion", "orders"), "database", "orders", ("restart_service",)),
    Scenario("db_exhaustion_decoy_deploy", _decoy, "database", "orders", ("restart_service",)),
    Scenario("config_regression", lambda t: t.inject("config_regression", "orders"), "configuration", "orders", ("rollback_deployment",)),
    Scenario("memory_leak", lambda t: t.inject("memory_leak", "orders"), "memory", "orders", ("restart_service",)),
    Scenario("redis_down", lambda t: t.inject("redis_down"), "cache", "orders", ("restart_service",)),
    Scenario("dependency_down", lambda t: t.inject("dependency_down"), "dependency", "orders"),
]

if __name__ == "__main__":
    args = sys.argv[1:]
    reps = int(args.pop(args.index("--repeat") + 1)) if "--repeat" in args else 1
    args = [a for a in args if a != "--repeat"]
    chosen = [s for s in SCENARIOS if not args or s.name in args] * reps
    target = RealTarget()
    rs = []
    for sc in chosen:
        print("running", sc.name, flush=True)
        rs.append(run_one(sc, target=target, warm=150, poll_max=120))
        with open(Path(__file__).parent / "reports" / "orbit_real_runs.jsonl", "a") as f:   # raw per-run record, never overwritten
            f.write(json.dumps(dict(rs[-1], run_at=time.time())) + "\n")
        print({k: v for k, v in rs[-1].items() if k in ("rca_ok", "final", "actions", "mttr_s", "rca_conf")}, flush=True)
    target.reset()
    out = report(rs, summarize(rs)).replace("(simulator)", "(real docker stack: OTel -> Prometheus/Loki/Tempo)")
    out = out.replace("simulated seconds", "seconds").replace("Virtual-time simulator; numbers measure the pipeline, not production.", "Real containers and real telemetry on one laptop; wall-clock times.")
    Path(__file__).parent.joinpath("reports", "real_latest.md").write_text(out)
    print(out)
