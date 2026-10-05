"""In-process stand-in for a production system.

Metrics follow first-order lag toward targets derived from active faults, so
remediation produces a realistic recovery curve (31% -> 19% -> 4%) instead of
an instant flip. Time is virtual: `wait()` advances it, nothing really sleeps.

This is the interface ORBIT expects from any target (a Prometheus/K8s adapter
would implement the same methods): now, wait, services, metrics, history,
changes, apply, logs(since, until), traces(since, until).

Logs and traces are generated from the same fault state as the metrics. The signals are authored here
(message templates, span names); the agents that read them are generic.
"""
import math
import time

SERVICES = ["orders", "payments", "users"]
HEALTHY = dict(error_rate=0.02, p95_latency=0.32, cpu=0.43, memory=0.5, db_pool=0.51,
               cache_hit=0.9, dep_error_rate=0.01, upstream_latency=0.05)
TAU = 30.0   # seconds; lag time constant
STEP = 5.0   # seconds; metric sample interval
ROOT = {"orders": "POST /orders", "payments": "POST /payments", "users": "GET /users"}
REPO = {"orders": "OrderRepository.fetch_batch", "payments": "LedgerRepository.fetch_batch", "users": "UserRepository.fetch_batch"}
_LOG = {  # fault -> (level, template); {n} varies per line, {rid} is a request id
    "bad_deploy": ("ERROR", "PoolError: connection pool exhausted (max=20, waiting={n}) in %s req={rid}"),
    "db_exhaustion": ("ERROR", "PoolError: connection pool exhausted (max=20, waiting={n}) req={rid}"),
    "config_regression": ("ERROR", "ReadTimeout: upstream call exceeded timeout=1s req={rid}"),
    "cpu_saturation": ("WARN", "worker queue depth {n}, request deadline exceeded req={rid}"),
    "memory_leak": ("ERROR", "OutOfMemory: heap usage {n}% GC overhead limit exceeded"),
    "redis_down": ("ERROR", "ConnectionRefusedError: redis:6379 connection refused req={rid}"),
    "dependency_down": ("ERROR", "api.elevenlabs.io returned 503 Service Unavailable req={rid}"),
    "network_latency": ("WARN", "slow upstream call took {n}ms req={rid}"),
}
# faults that overlay symptoms on one service; value = metric overrides
_SYMPTOMS = {
    "bad_deploy": dict(error_rate=0.31, p95_latency=2.1, db_pool=0.97),
    "db_exhaustion": dict(error_rate=0.31, p95_latency=2.1, db_pool=0.97),
    "config_regression": dict(error_rate=0.20, p95_latency=5.0),
    "cpu_saturation": dict(cpu=1.0, p95_latency=1.5, error_rate=0.08),
    "memory_leak": dict(memory=0.97, p95_latency=1.0, error_rate=0.15),
    "network_latency": dict(upstream_latency=1.1, p95_latency=1.2, error_rate=0.03),
}


class Sim:
    def __init__(self, seed_time=None):
        self.t = seed_time if seed_time is not None else time.time()
        self.services = SERVICES + ["redis"]
        self.faults = []  # dicts: name, service, start
        self.versions = {s: "v2.8.0" for s in SERVICES}
        self.configs = {s: "timeout=30s" for s in SERVICES}
        self._changes = []  # {t, service, kind, ref, previous}
        self.cur = {(s, m): v for s in SERVICES for m, v in HEALTHY.items()}
        self.cur[("redis", "redis_up")] = 1.0
        self._hist = []  # (t, {key: value})
        self._logs, self._traces, self._seq = [], [], 0
        self._snap()

    # ---- target interface -------------------------------------------------
    def now(self):
        return self.t

    def wait(self, seconds):
        end = self.t + seconds
        while self.t < end - 1e-9:
            dt = min(STEP, end - self.t)
            k = 1 - math.exp(-dt / TAU)
            tgt = self._targets()
            for key, v in tgt.items():
                self.cur[key] += (v - self.cur[key]) * k
            self.t += dt
            self._snap()
            self._emit()

    def metrics(self):
        return dict(self.cur)

    def history(self):
        return self._hist

    def changes(self):
        return list(self._changes)

    def logs(self, since, until):
        return [l for l in self._logs if since <= l["t"] <= until]

    def traces(self, since, until):
        return [t for t in self._traces if since <= t["t"] <= until]

    def apply(self, action, **p):
        return getattr(self, "_do_" + action)(**p)

    # ---- fault injection (not part of the target interface) ---------------
    def inject(self, name, service="orders", delay=0.0, **extra):
        self.faults.append(dict(name=name, service=service, start=self.t + delay, **extra))
        if name == "bad_deploy":
            ver = extra.get("version", "v2.8.1")
            self._change(service, "deploy", ver, self.versions[service])
            self.versions[service] = ver
            self.faults[-1]["version"] = ver
        elif name == "config_regression":
            self._change(service, "config", "timeout=1s", self.configs[service])
            self.configs[service] = "timeout=1s"
            self.faults[-1]["version"] = "timeout=1s"

    def benign_deploy(self, service, version="v2.7.9"):
        self._change(service, "deploy", version, self.versions[service])
        self.versions[service] = version

    # ---- internals ----------------------------------------------------------
    def _change(self, service, kind, ref, previous):
        self._changes.append(dict(t=self.t, service=service, kind=kind, ref=ref, previous=previous, rolled_back=False))

    def _snap(self):
        self._hist.append((self.t, dict(self.cur)))

    def _active(self, s):
        return [f for f in self.faults if f["start"] <= self.t and (
            f["service"] == s or f["name"] == "redis_down" or (f["name"] == "dependency_down" and s in ("orders", "payments")))]

    def _emit(self):
        for s in SERVICES:
            act = self._active(s)
            err = self.cur[(s, "error_rate")]
            self._logs.append(dict(t=self.t, service=s, level="INFO", msg=f"health check ok in {self.cur[(s, 'p95_latency')] * 1000:.0f}ms"))
            for i in range(int(err * 20 + 0.5) if act else 0):
                f = act[i % len(act)]
                lvl, tpl = _LOG[f["name"]]
                self._seq += 1
                msg = (tpl % REPO[s] if "%s" in tpl else tpl).format(n=10 + self._seq % 7, rid=f"{self._seq:08x}")
                self._logs.append(dict(t=self.t, service=s, level=lvl, msg=msg))
            for i in range(3):
                self._traces.append(self._trace(s, i < round(err * 3), {f["name"] for f in act}))

    def _trace(self, s, failing, names):
        mult = 4 if "cpu_saturation" in names else 2 if "memory_leak" in names else 1
        sp = [dict(name=ROOT[s], kind="server", dur=self.cur[(s, "p95_latency")] * 0.8, err=None)]

        def add(name, kind, dur, err=None):
            sp.append(dict(name=name, kind=kind, dur=dur, err=err))

        pool = bool(names & {"bad_deploy", "db_exhaustion"})
        if "bad_deploy" in names:
            add(REPO[s], "internal", 0.15 * mult)
        add("db.pool.acquire", "db", 1.8 if pool else 0.02 * mult, "PoolTimeout: no connection in 2s" if pool and failing else None)
        add("db.query", "db", 1.0 if "network_latency" in names else 0.1 * mult)
        down = "redis_down" in names
        add("redis.get", "cache", 0.5 if down else 0.005 * mult, "ConnectionRefusedError: redis:6379" if down else None)
        if s != "users":
            if "config_regression" in names:
                add("external_api.call", "external", 1.0, "ReadTimeout after 1s (timeout=1s)" if failing else None)
            elif "dependency_down" in names:
                add("external_api.call", "external", 0.9, "503 Service Unavailable from api.elevenlabs.io" if failing else None)
            else:
                add("external_api.call", "external", 0.12 * mult)
        if failing:  # errors propagate to the root span
            errs = [x["err"] for x in sp[1:] if x["err"]]
            sp[0]["err"] = errs[0] if errs else ("ConnectionResetError: worker restarted" if "memory_leak" in names else "DeadlineExceeded")
        return dict(t=self.t, service=s, spans=sp)

    def _targets(self):
        tgt = {(s, m): v for s in SERVICES for m, v in HEALTHY.items()}
        tgt[("redis", "redis_up")] = 1.0

        def worse(key, v, low_is_bad=False):
            tgt[key] = min(tgt[key], v) if low_is_bad else max(tgt[key], v)

        for f in self.faults:
            if f["start"] > self.t:
                continue
            n, s = f["name"], f["service"]
            if n in _SYMPTOMS:
                for m, v in _SYMPTOMS[n].items():
                    worse((s, m), v)
            elif n == "redis_down":
                tgt[("redis", "redis_up")] = 0.0
                for x in SERVICES:
                    worse((x, "cache_hit"), 0.0, True)
                    worse((x, "p95_latency"), 0.9)
                    worse((x, "error_rate"), 0.10)
            elif n == "dependency_down":
                for x, e in (("orders", 0.25), ("payments", 0.40)):
                    worse((x, "dep_error_rate"), 0.9)
                    worse((x, "error_rate"), e)
        return tgt

    # ---- remediation primitives (called via apply) ---------------------------
    def _check(self, service):
        if service not in self.services:
            raise ValueError(f"unknown service {service}")

    def _clear(self, names, service):
        self.faults = [f for f in self.faults if not (f["name"] in names and f["service"] == service)]

    def _do_restart_service(self, service):
        self._check(service)
        self._clear({"db_exhaustion", "memory_leak", "redis_down"}, service)
        return {"ok": True, "detail": f"restarted {service}"}

    def _do_scale_service(self, service, replicas=None):
        self._check(service)
        self._clear({"cpu_saturation"}, service)
        return {"ok": True, "detail": f"scaled {service}"}

    def _do_clear_cache(self, service):
        self._check(service)
        return {"ok": True, "detail": f"cleared cache for {service}"}

    def _do_rollback_deployment(self, service, target_version):
        self._check(service)
        ch = next((c for c in reversed(self._changes)
                   if c["service"] == service and c["previous"] == target_version and not c["rolled_back"]), None)
        if ch is None:
            raise ValueError(f"no change on {service} to roll back to {target_version}")
        ch["rolled_back"] = True
        (self.versions if ch["kind"] == "deploy" else self.configs)[service] = target_version
        self.faults = [f for f in self.faults if not (f["service"] == service and f.get("version") == ch["ref"])]
        return {"ok": True, "detail": f"rolled {service} back to {target_version}"}
