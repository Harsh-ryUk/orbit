"""Evidence collection: anomaly rules, metrics agent, deployment agent, timeline."""
from statistics import median

# metric -> (breach(v, baseline), healthy(v, baseline)). Healthy has hysteresis vs breach.
RULES = {
    "error_rate": (lambda v, b: v > max(0.05, b * 3), lambda v, b: v < max(b * 1.5, 0.03)),
    "p95_latency": (lambda v, b: v > b * 2, lambda v, b: v < b * 1.3),
    "cpu": (lambda v, b: v > 0.9, lambda v, b: v < 0.8),
    "memory": (lambda v, b: v > 0.9, lambda v, b: v < 0.8),
    "db_pool": (lambda v, b: v > 0.85, lambda v, b: v < 0.8),
    "cache_hit": (lambda v, b: v < 0.5, lambda v, b: v > 0.7),
    "dep_error_rate": (lambda v, b: v > 0.1, lambda v, b: v < 0.05),
    "upstream_latency": (lambda v, b: v > 0.5, lambda v, b: v < 0.2),
    "redis_up": (lambda v, b: v < 0.5, lambda v, b: v > 0.5),
}


def baseline(target, key, exclude_last=600):
    # ponytail: median of history older than 10 min; real deployments want same-hour-last-week
    t_end = target.now() - exclude_last
    vals = [m[key] for t, m in target.history() if t < t_end] or [m[key] for _, m in target.history()]
    return median(vals)


def metrics_agent(target):
    """Return anomalous (service, metric) pairs with baseline, current value and onset time."""
    out = []
    hist = target.history()
    for key, cur in target.metrics().items():
        rule = RULES.get(key[1])
        if not rule:
            continue
        b = baseline(target, key)
        if not rule[0](cur, b):
            continue
        onset = hist[-1][0]
        for t, m in reversed(hist):
            if not rule[0](m[key], b):
                break
            onset = t
        out.append(dict(service=key[0], metric=key[1], baseline=b, current=cur, onset=onset))
    return sorted(out, key=lambda a: a["onset"])


def deployment_agent(target, onset, window=1800):
    """Changes (deploys/config) in the `window` seconds before `onset`, with correlation strength."""
    out = []
    for c in target.changes():
        delta = onset - c["t"]
        if -60 <= delta <= window:  # a change landing just after onset is still suspicious clock skew
            out.append({**c, "delta_s": delta, "correlation": "HIGH" if delta <= 900 else "MEDIUM"})
    return out


def fmt(a):
    return f"{a['service']}.{a['metric']} {a['baseline']:.3g} -> {a['current']:.3g}"


def timeline(anoms, changes, now):
    ev = [(c["t"], f"{c['kind']} {c['service']} {c['previous']} -> {c['ref']}") for c in changes]
    ev += [(a["onset"], "anomaly " + fmt(a)) for a in anoms]
    ev.append((now, "incident detected"))
    return [dict(t=t, event=e) for t, e in sorted(ev)]


def detect(target, sustain=60):
    """SLO-style trigger (like Prometheus `for:`): a user-facing service breaching error rate or latency for
    `sustain` seconds, so slower-moving symptoms have surfaced before we investigate. Returns (service, reason) or None."""
    hits = [a for a in metrics_agent(target) if a["service"] != "redis" and a["metric"] in ("error_rate", "p95_latency")
            and target.now() - a["onset"] >= sustain]
    return (hits[0]["service"], fmt(hits[0])) if hits else None
