"""Hypothesis engine: generate competing causes, then try to disprove each with live telemetry."""
import math

CATEGORIES = ["deployment", "configuration", "database", "dependency", "network", "cache", "cpu", "memory"]
CORE = {"deployment", "dependency", "database", "network"}  # always tested so they can be visibly disproved
SIGNATURE = {"configuration": None, "cache": "cache_hit", "cpu": "cpu", "memory": "memory"}
DESC = {
    "deployment": "Recent deployment regression", "configuration": "Recent configuration change regression",
    "database": "Database connection pool exhaustion", "dependency": "External dependency degradation",
    "network": "Network latency to upstream", "cache": "Cache (Redis) failure",
    "cpu": "CPU saturation", "memory": "Memory leak / exhaustion",
}


def _find(anoms, metric, service=None):
    return next((a for a in anoms if a["metric"] == metric and (service is None or a["service"] == service)), None)


def generate(anoms, changes):
    metrics = {a["metric"] for a in anoms}
    kinds = {c["kind"] for c in changes}
    cats = [c for c in CATEGORIES if c in CORE or (c == "configuration" and "config" in kinds)
            or (SIGNATURE.get(c) in metrics)]
    return [dict(category=c, description=DESC[c], score=0.0, tests=[]) for c in cats]


def _tests(cat, svc, anoms, changes):
    """Each test: (prediction, weight if prediction holds, weight if it does not, observed-text)."""
    others = {a["service"] for a in anoms} - {svc}
    ch = [c for c in changes if c["service"] == svc]
    kind = lambda k: [c for c in ch if c["kind"] == k]
    if cat in ("deployment", "configuration"):
        k = "deploy" if cat == "deployment" else "config"
        c = kind(k)
        near = c and min(x["delta_s"] for x in c)
        t = [(f"a {k} change on {svc} precedes onset", 2.5 if c else -2.0,
              f"{k} {c[-1]['ref']} was {near:.0f}s before onset" if c else f"no {k} change on {svc} in window")]
        t.append(("other services stay healthy", 0.5 if not others else -0.5,
                  "only " + svc + " affected" if not others else "also affected: " + ", ".join(sorted(others))))
        return t
    if cat == "database":
        a = _find(anoms, "db_pool", svc)
        t = [("db_pool utilization is abnormal", 1.5 if a else -2.0,
              f"db_pool {a['baseline']:.0%} -> {a['current']:.0%}" if a else "db_pool normal")]
        t.append(("no recent change explains it", 1.0 if not ch else 0.0,
                  "no change in window" if not ch else f"{len(ch)} recent change(s) are a competing explanation"))
        return t
    if cat == "dependency":
        a = _find(anoms, "dep_error_rate", svc)
        t = [("dependency error rate is abnormal", 2.5 if a else -1.5,
              f"dep_error_rate {a['baseline']:.0%} -> {a['current']:.0%}" if a else "dependency error rate normal")]
        t.append(("dependency failure hits every caller", 1.0 if a and others else (-1.5 if a else 0.0),
                  f"other affected services: {sorted(others)}" if others else "only one service affected"))
        return t
    if cat == "network":
        a = _find(anoms, "upstream_latency", svc)
        return [("upstream latency is abnormal", 2.5 if a else -1.0,
                 f"upstream_latency {a['baseline']:.2f}s -> {a['current']:.2f}s" if a else "upstream latency normal")]
    if cat == "cache":
        a = _find(anoms, "redis_up") or _find(anoms, "cache_hit", svc)
        return [("redis is down or cache hit ratio collapsed", 3.0 if a else -1.5,
                 f"{a['service']}.{a['metric']} {a['baseline']:.2g} -> {a['current']:.2g}" if a else "cache healthy")]
    m = "cpu" if cat == "cpu" else "memory"
    a = _find(anoms, m, svc)
    return [(f"{m} saturation on {svc}", 2.5 if a else -1.5,
             f"{m} {a['baseline']:.0%} -> {a['current']:.0%}" if a else f"{m} normal")]


def test_all(hyps, svc, anoms, changes):
    for h in hyps:
        for pred, w, text in _tests(h["category"], svc, anoms, changes):
            h["tests"].append(dict(prediction=pred, observed=text, weight=w))
        h["score"] = sum(t["weight"] for t in h["tests"])
    return normalize(hyps)


def normalize(hyps):
    """Softmax over scores -> confidence; rank, assign ids and status."""
    z = sum(math.exp(h["score"]) for h in hyps) or 1.0
    for h in hyps:
        h["confidence"] = math.exp(h["score"]) / z
    hyps.sort(key=lambda h: -h["confidence"])
    for i, h in enumerate(hyps, 1):
        h["id"] = f"H{i}"
        h["status"] = "strengthened" if i == 1 and h["confidence"] > 0.5 else ("rejected" if h["confidence"] < 0.05 else "weakened" if i > 1 else "open")
        h["supporting"] = [t["observed"] for t in h["tests"] if t["weight"] > 0]
        h["contradicting"] = [t["observed"] for t in h["tests"] if t["weight"] < 0]
    return hyps
