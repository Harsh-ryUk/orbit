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


def _extra(cat, svc, changes, logs, tr):
    """Tests that use log signatures and trace comparisons. Keyword matching on signatures is deliberately
    simple (ponytail: let an LLM read the signatures when a provider is wired in)."""
    def L(*words):
        return next((g for g in logs if any(w in g["template"].lower() for w in words)), None)

    def sig(g):
        return f"log signature x{g['count']}: {g['template']}" if g else "no matching log signature"

    errs = tr["error_spans"] if tr else []
    bn = tr["bottleneck"] if tr else None
    new = tr["new_ops"] if tr else []
    t = []
    if cat == "deployment" and tr:
        has = any(c["kind"] == "deploy" and c["service"] == svc for c in changes)
        t.append(("a new code path (span) appears after the change", 2.0 if new and has else (-0.75 if has else 0.0),
                  f"new operations in traces: {new}" if new else "no new operations in traces"))
    elif cat == "configuration":
        e = next((e for e in errs if "timeout=" in (e["sample"] or "")), None)
        g = L("timeout=")
        t.append(("errors cite a configured limit (timeout=)", 1.5 if e or g else 0.0, e["sample"] if e else sig(g)))
    elif cat == "database":
        pool = bn and bn["name"] == "db.pool.acquire" or any(e["name"] == "db.pool.acquire" for e in errs)
        if tr:
            t.append(("db.pool.acquire is the latency bottleneck or failing", 1.0 if pool else -0.5,
                      f"bottleneck {bn['name']} (+{bn['delta']:.2f}s)" if bn else "no bottleneck span"))
            t.append(("no new code path explains the pool pressure", 0.5 if not new else -1.0,
                      "traces use the same operations as baseline" if not new else f"new operations {new}"))
        t.append(("logs show pool exhaustion", 1.0 if L("pool exhausted") else 0.0, sig(L("pool exhausted"))))
    elif cat == "dependency":
        e = next((e for e in errs if e["kind"] == "external" and "timeout=" not in (e["sample"] or "")), None)
        if tr:
            t.append(("an external-call span fails with a provider error", 1.5 if e else -0.5, e["sample"] if e else "no failing external span"))
        t.append(("logs show provider unavailability", 1.0 if L("unavailable", "503") else 0.0, sig(L("unavailable", "503"))))
    elif cat == "network" and tr:
        ok = bn and bn["kind"] in ("db", "external") and bn["share"] >= 0.6 and not any(e["name"] == bn["name"] for e in errs)
        t.append(("latency is concentrated in one upstream span that is slow but not failing", 1.5 if ok else -0.5,
                  f"{bn['name']} explains {bn['share']:.0%} of added latency" if bn else "no bottleneck"))
    elif cat == "cpu":
        if tr:
            t.append(("added latency is spread across all spans, no single bottleneck", 1.0 if bn and bn["share"] < 0.6 else 0.0,
                      f"largest single span explains {bn['share']:.0%}" if bn else "no bottleneck"))
        t.append(("logs show queueing / deadline pressure", 1.0 if L("queue depth", "deadline") else 0.0, sig(L("queue depth", "deadline"))))
    elif cat == "memory":
        t.append(("logs show heap exhaustion / GC pressure", 1.5 if L("heap", "outofmemory", "gc overhead") else 0.0,
                  sig(L("heap", "outofmemory", "gc overhead"))))
    elif cat == "cache":
        e = next((e for e in errs if e["kind"] == "cache"), None)
        if tr:
            t.append(("cache spans are failing", 1.0 if e else 0.0, e["sample"] if e else "cache spans healthy"))
        t.append(("logs show redis connection failures", 1.0 if L("redis") else 0.0, sig(L("redis"))))
    return t


def test_all(hyps, svc, anoms, changes, logs=(), traces=None):
    for h in hyps:
        for pred, w, text in _tests(h["category"], svc, anoms, changes) + _extra(h["category"], svc, changes, logs, traces):
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
