"""RealTarget: the same target interface as simulator.Sim, backed by Prometheus, Loki, Tempo and docker compose.

Read side  -> metrics()/history() PromQL, logs() LogQL, traces() TraceQL; all over HTTP.
Write side -> apply() runs ONLY the allowlisted actions below via `docker compose` on the host. There is no
              generic exec path. inject()/reset() are chaos tooling for evaluation and are not reachable from ORBIT's tools.
"""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-p", "orbit", "-f", str(ROOT / "infra/docker/docker-compose.yml")]
APPS = {"orders": 18001, "payments": 18002, "users": 18003, "external": 18004}
MONITORED = ["orders", "payments", "users"]
W = "30s"  # rate window; scrape interval is 5s

# metric name (ORBIT vocabulary) -> PromQL returning one series per `service`
# numerator falls back to 0 so "no errors yet" reads as 0 instead of a missing series
_ratio = lambda n, d: f"(sum by (service)({n}) or 0 * sum by (service)({d})) / sum by (service)({d})"
QUERIES = {
    "error_rate": _ratio(f'rate(shop_requests_total{{status="error"}}[{W}])', f"rate(shop_requests_total[{W}])"),
    "p95_latency": f"histogram_quantile(0.95, sum by (service, le)(rate(shop_request_duration_seconds_bucket[{W}])))",
    "cpu": "max by (service)(shop_cpu_utilization)",
    "memory": "max by (service)(shop_memory_utilization)",
    "db_pool": "max by (service)(shop_db_pool_utilization)",
    "cache_hit": _ratio(f'rate(shop_cache_requests_total{{result="hit"}}[{W}])', f"rate(shop_cache_requests_total[{W}])"),
    "dep_error_rate": _ratio(f'rate(shop_external_calls_total{{status="error"}}[{W}])', f"rate(shop_external_calls_total[{W}])"),
    "upstream_latency": f"histogram_quantile(0.95, sum by (service, le)(rate(shop_db_query_duration_seconds_bucket[{W}])))",
}
REDIS_UP = "min(shop_redis_up)"
_LEVELS = {"WARNING": "WARN", "WARN": "WARN", "ERROR": "ERROR", "INFO": "INFO", "FATAL": "ERROR", "DEBUG": "INFO"}


class RealTarget:
    verify_offsets = [0, 15, 30, 60, 120]   # real seconds; the sim's 300s tail would make every check 5 minutes
    baseline_exclude = 120                  # needs >2 min of healthy history before a fault

    def __init__(self, prom="http://localhost:19090", loki="http://localhost:13100", tempo="http://localhost:13200",
                 state_path=None, history_s=1800, compose=True):
        self.prom, self.loki, self.tempo, self.history_s = prom, loki, tempo, history_s
        self.http = httpx.Client(timeout=20)
        self.state_path = Path(state_path or ROOT / "data" / "ops_state.json")
        self._compose_enabled = compose
        self._hist_cache = (0.0, [])
        self.epoch = 0.0  # history before this is ignored (set by reset() so one scenario's faults don't pollute the next baseline)
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else self._fresh_state()
        self.services = MONITORED + ["redis"]

    # ---- target interface: read side ------------------------------------------------------------------
    def now(self):
        return time.time()

    def wait(self, seconds):
        time.sleep(seconds)

    def _vec(self, q):
        r = self.http.get(f"{self.prom}/api/v1/query", params={"query": q}).json()["data"]["result"]
        return [(x["metric"].get("service"), float(x["value"][1])) for x in r if x["value"][1] not in ("NaN", "+Inf", "-Inf")]

    def metrics(self):
        out = {}
        for name, q in QUERIES.items():
            for svc, v in self._vec(q):
                if svc in MONITORED:
                    out[(svc, name)] = v
        out.update({("redis", "redis_up"): v for _, v in self._vec(REDIS_UP)})
        return out

    def history(self):
        """[(t, {(service, metric): value})] over the last `history_s`, 10s resolution. Cached for 5s."""
        if time.time() - self._hist_cache[0] < 5:
            return self._hist_cache[1]
        end = time.time()
        rows = {}
        for name, q in {**QUERIES, "redis_up": REDIS_UP}.items():
            r = self.http.get(f"{self.prom}/api/v1/query_range", params=dict(query=q, start=max(end - self.history_s, self.epoch), end=end, step=10)).json()["data"]["result"]
            for series in r:
                svc = series["metric"].get("service") or "redis"
                if svc not in self.services:
                    continue
                for ts, v in series["values"]:
                    if v not in ("NaN", "+Inf", "-Inf"):
                        rows.setdefault(float(ts), {})[(svc, name)] = float(v)
        self._hist_cache = (time.time(), sorted(rows.items()))
        return self._hist_cache[1]

    def changes(self):
        return [dict(c) for c in self.state["changes"]]

    def logs(self, since, until, service=None):
        sel = f'{{service_name="{service}"}}' if service else '{service_name=~".+"}'
        r = self.http.get(f"{self.loki}/loki/api/v1/query_range", params=dict(
            query=sel, start=int(since * 1e9), end=int(until * 1e9), limit=5000, direction="forward")).json()["data"]["result"]
        out = []
        for st in r:
            lab = st["stream"]
            lvl = _LEVELS.get(lab.get("severity_text", "INFO").upper(), "INFO")
            for ns, line in st["values"]:
                head, _, rest = line.partition(" ")
                out.append(dict(t=int(ns) / 1e9, service=lab.get("service_name"), level=lvl, msg=rest if head in _LEVELS else line))
        return sorted(out, key=lambda l: l["t"])

    def traces(self, since, until, service=None, limit=60):
        q = '{ span.orbit.kind = "server" }' if service is None else f'{{ resource.service.name = "{service}" && span.orbit.kind = "server" }}'
        r = self.http.get(f"{self.tempo}/api/search", params=dict(q=q, start=int(since), end=int(until), limit=limit)).json().get("traces", [])
        with ThreadPoolExecutor(8) as ex:
            full = list(ex.map(lambda t: self._trace(t["traceID"]), r))
        return [self._convert(f, service) for f in full if f]

    def _trace(self, tid):
        r = self.http.get(f"{self.tempo}/api/traces/{tid}")
        return r.json() if r.status_code == 200 else None

    @staticmethod
    def _convert(doc, service):
        """Tempo/OTLP JSON -> ORBIT trace {t, service, spans[{name, kind, dur, err, service}]}, root span first."""
        spans = []
        for b in doc.get("batches", []):
            svc = next((a["value"]["stringValue"] for a in b["resource"]["attributes"] if a["key"] == "service.name"), "?")
            for ss in b.get("scopeSpans") or b.get("instrumentationLibrarySpans") or []:
                for sp in ss["spans"]:
                    at = {a["key"]: next(iter(a["value"].values())) for a in sp.get("attributes", [])}
                    st = sp.get("status", {})
                    bad = st.get("code") in (2, "STATUS_CODE_ERROR")
                    t0, t1 = int(sp["startTimeUnixNano"]), int(sp["endTimeUnixNano"])
                    spans.append(dict(name=sp["name"], kind=at.get("orbit.kind", "internal"), dur=(t1 - t0) / 1e9, service=svc, _t=t0,
                                      err=(st.get("message") or "error") if bad else None, _root=not sp.get("parentSpanId")))
        spans.sort(key=lambda s: (not s["_root"], s["_t"]))
        root = spans[0]
        return dict(t=root["_t"] / 1e9, service=service or root["service"],
                    spans=[{k: v for k, v in s.items() if not k.startswith("_")} for s in spans])

    # ---- chaos / evaluation tooling (not exposed to ORBIT's tools) -------------------------------------
    @staticmethod
    def _fresh_state():
        return dict(versions={s: "v2.8.0" for s in MONITORED}, configs={s: "timeout=5.0" for s in MONITORED}, changes=[])

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1))

    def _env(self):
        e = dict(os.environ)
        for s in MONITORED:
            e[f"{s.upper()}_VERSION"] = self.state["versions"][s]
            e[f"{s.upper()}_TIMEOUT"] = self.state["configs"][s].split("=")[1]
        return e

    def _dc(self, *args):
        if self._compose_enabled:
            subprocess.run([*COMPOSE, *args], env=self._env(), check=True, capture_output=True, timeout=180)

    def _healthy(self, service, timeout=90):
        end = time.time() + timeout
        while self._compose_enabled and service in APPS and time.time() < end:
            try:
                if self.http.get(f"http://localhost:{APPS[service]}/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)

    def _recreate(self, service):
        self._dc("up", "-d", "--no-deps", "--force-recreate", service)
        self._healthy(service)

    def _fault(self, service, name, on=True):
        self.http.post(f"http://localhost:{APPS[service]}/admin/fault", json=dict(name=name, on=on)).raise_for_status()

    def _change(self, service, kind, ref):
        key = "versions" if kind == "deploy" else "configs"
        self.state["changes"].append(dict(t=time.time(), service=service, kind=kind, ref=ref, previous=self.state[key][service], rolled_back=False))
        self.state[key][service] = ref
        self._save()

    def inject(self, name, service="orders", delay=0.0, **_):
        assert delay == 0, "RealTarget.inject is immediate"
        if name == "bad_deploy":
            self._change(service, "deploy", "v2.8.1")
            self._recreate(service)
        elif name == "config_regression":
            self._change(service, "config", "timeout=0.05")
            self._recreate(service)
        elif name == "db_exhaustion":
            self._fault(service, "db_leak")
        elif name == "memory_leak":
            self._fault(service, "mem_leak")
        elif name == "redis_down":
            self._dc("stop", "redis")
        elif name == "dependency_down":
            self._fault("external", "down")
        else:
            raise ValueError(f"unsupported fault {name}")

    def benign_deploy(self, service, version="v2.7.9"):
        self._change(service, "deploy", version)
        self._recreate(service)

    def reset(self):
        """Back to a clean, healthy stack (versions/config defaults, faults cleared, history of changes dropped)."""
        self.state = self._fresh_state()
        self._save()
        self._hist_cache = (0.0, [])
        self._dc("up", "-d", "--no-deps", "--force-recreate", "redis", "external", *MONITORED)
        for s in MONITORED + ["external"]:
            self._healthy(s)
        self.epoch = time.time()

    # ---- remediation primitives (the allowlist; dispatched by orbit.tools via apply) ---------------------
    def apply(self, action, **p):
        return getattr(self, "_do_" + action)(**p)

    def _check(self, service):
        if service not in self.services:
            raise ValueError(f"unknown service {service}")

    def _do_restart_service(self, service):
        self._check(service)
        self._dc("restart", service)
        self._dc("up", "-d", "--no-deps", service)  # also starts it if it was stopped
        self._healthy(service)
        return {"ok": True, "detail": f"restarted {service}"}

    def _do_clear_cache(self, service):
        self._check(service)
        self._dc("exec", "-T", "redis", "redis-cli", "flushall")
        return {"ok": True, "detail": "flushed redis"}

    def _do_scale_service(self, service, **_):
        raise ValueError("scale_service is not implemented for the compose target (no load balancer in front of replicas)")

    def _do_rollback_deployment(self, service, target_version):
        self._check(service)
        ch = next((c for c in reversed(self.state["changes"]) if c["service"] == service and c["previous"] == target_version
                   and not c["rolled_back"]), None)
        if ch is None:
            raise ValueError(f"no change on {service} to roll back to {target_version}")
        ch["rolled_back"] = True
        self.state["versions" if ch["kind"] == "deploy" else "configs"][service] = target_version
        self._save()
        self._recreate(service)
        return {"ok": True, "detail": f"rolled {service} back to {target_version}"}
