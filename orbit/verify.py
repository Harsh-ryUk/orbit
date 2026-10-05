"""Recovery verification: telemetry, not exit codes, decides success."""
from .agents import RULES

OFFSETS = [0, 30, 60, 120, 300]


def verify(target, anomalies):
    """Sample at T+offsets. RECOVERED after two consecutive all-healthy samples (or healthy at the end),
    PARTIAL if >= half the anomalies cleared or the worst metric moved >50% back to baseline, else FAILED."""
    before = {(a["service"], a["metric"]): a for a in anomalies}
    samples, streak, last = [], 0, 0
    for off in OFFSETS:
        target.wait(off - last)
        last = off
        cur = target.metrics()
        ok = {k: RULES[k[1]][1](cur[k], a["baseline"]) for k, a in before.items()}
        samples.append(dict(offset=off, healthy=sum(ok.values()), total=len(ok), values={f"{k[0]}.{k[1]}": cur[k] for k in before}))
        streak = streak + 1 if all(ok.values()) else 0
        if streak >= 2:
            break
    healthy, total = samples[-1]["healthy"], samples[-1]["total"]
    moved = [(a["current"] - cur[k]) / (a["current"] - a["baseline"]) for k, a in before.items() if a["current"] != a["baseline"]]
    status = "RECOVERED" if streak >= 2 or healthy == total else \
        "PARTIAL" if healthy >= total / 2 or (moved and max(moved) > 0.5 and min(moved) > 0.0) else "FAILED"
    rows = [dict(metric=f"{k[0]}.{k[1]}", baseline=a["baseline"], before_value=a["current"], after_value=cur[k],
                 threshold="healthy" if ok[k] else "breached", status="RECOVERED" if ok[k] else "FAILED")
            for k, a in before.items()]
    return dict(status=status, healthy=healthy, total=total, samples=samples, rows=rows)
