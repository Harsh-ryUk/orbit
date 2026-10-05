"""Evidence collection: anomaly rules, metrics agent, deployment agent, timeline."""
import re
from statistics import mean, median

from .store import redact

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


_VAR = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{8,}\b|\d+(?:\.\d+)?")


def _tmpl(msg):
    return _VAR.sub("<n>", msg)


def log_agent(target, onset):
    """Group WARN+ logs around the incident into signatures (variable parts stripped); flag ones unseen in the baseline."""
    now = target.now()
    seen = {(l["service"], _tmpl(l["msg"])) for l in target.logs(onset - 330, onset - 30)}
    groups = {}
    for l in target.logs(onset - 30, now):
        if l["level"] == "INFO":
            continue
        t = _tmpl(l["msg"])
        g = groups.setdefault((l["service"], l["level"], t), dict(service=l["service"], level=l["level"], template=t, count=0,
                              first_seen=l["t"], sample=redact(l["msg"]), is_new=(l["service"], t) not in seen))
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: -g["count"])


def _span_stats(traces):
    st = {}
    for tr in traces:
        for i, sp in enumerate(tr["spans"]):
            d = st.setdefault(sp["name"], dict(kind=sp["kind"], root=i == 0, durs=[], errs=0, sample=None))
            d["durs"].append(sp["dur"])
            if sp["err"]:
                d["errs"] += 1
                d["sample"] = sp["err"]
    return st


def trace_agent(target, service, onset):
    """Compare traces since onset with the pre-incident baseline: new operations, the latency bottleneck,
    failing spans, and a representative failing request path. None when there are no traces to compare."""
    cur = [t for t in target.traces(onset, target.now()) if t["service"] == service]
    base = [t for t in target.traces(onset - 360, onset - 60) if t["service"] == service]
    if not cur or not base:
        return None
    c, b = _span_stats(cur), _span_stats(base)
    root = next(n for n, d in c.items() if d["root"])
    root_delta = mean(c[root]["durs"]) - mean(b[root]["durs"]) if root in b else 0
    deltas = {n: mean(d["durs"]) - mean(b[n]["durs"]) for n, d in c.items() if n in b and not d["root"]}
    bn = max(deltas, key=deltas.get) if deltas else None
    errors = [dict(name=n, kind=d["kind"], rate=d["errs"] / len(d["durs"]), sample=d["sample"])
              for n, d in c.items() if not d["root"] and d["errs"] / len(d["durs"]) >= 0.2]
    failing = next((t for t in reversed(cur) if t["spans"][0]["err"]), None)
    path = [x["name"] for x in failing["spans"] if x["err"] or x is failing["spans"][0]] if failing else []
    return dict(service=service, n_traces=len(cur), new_ops=sorted(set(c) - set(b)), error_spans=errors, path=path,
                bottleneck=dict(name=bn, kind=c[bn]["kind"], delta=deltas[bn], share=deltas[bn] / root_delta if root_delta > 0.05 else 0) if bn else None)


def timeline(anoms, changes, now, logs=()):
    ev = [(c["t"], f"{c['kind']} {c['service']} {c['previous']} -> {c['ref']}") for c in changes]
    ev += [(a["onset"], "anomaly " + fmt(a)) for a in anoms]
    ev += [(g["first_seen"], f"new log signature on {g['service']}: {g['template']}") for g in logs if g["is_new"]]
    ev.append((now, "incident detected"))
    return [dict(t=t, event=e) for t, e in sorted(ev)]


def detect(target, sustain=60):
    """SLO-style trigger (like Prometheus `for:`): a user-facing service breaching error rate or latency for
    `sustain` seconds, so slower-moving symptoms have surfaced before we investigate. Returns (service, reason) or None."""
    hits = [a for a in metrics_agent(target) if a["service"] != "redis" and a["metric"] in ("error_rate", "p95_latency")
            and target.now() - a["onset"] >= sustain]
    return (hits[0]["service"], fmt(hits[0])) if hits else None
