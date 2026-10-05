"""Tiny instrumented shop used as ORBIT's real target. One image, role chosen by SERVICE:
orders -> (redis, postgres, payments), payments -> (postgres, external), users -> (redis, postgres), external -> mock provider.

Emits OpenTelemetry traces, metrics and logs to the collector. Faults are in-process flags set via /admin/fault
(chaos only; ORBIT never calls it) plus VERSION / TIMEOUT env, which the ops layer changes by recreating the container.
"""
import asyncio
import contextlib
import logging
import os
import random
import time
import uuid

import httpx
import psutil
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from psycopg_pool import AsyncConnectionPool, PoolTimeout

SVC = os.environ.get("SERVICE", "orders")
VERSION = os.environ.get("VERSION", "v2.8.0")
TIMEOUT = float(os.environ.get("TIMEOUT", "5.0"))            # seconds for the downstream call (a config "knob")
POOL = int(os.environ.get("DB_POOL", "4"))
MEM_LIMIT = float(os.environ.get("MEM_LIMIT_MB", "256")) * 1024 * 1024
DSN = os.environ.get("DATABASE_URL", "postgresql://orbit:orbit@postgres:5432/orbit")
OTLP = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

# ---- telemetry -----------------------------------------------------------------------------
res = Resource.create({"service.name": SVC, "service.version": VERSION})
tp = TracerProvider(resource=res)
tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP, insecure=True), schedule_delay_millis=1000))
trace.set_tracer_provider(tp)
tracer = trace.get_tracer("shop")
mp = MeterProvider(resource=res, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=OTLP, insecure=True), export_interval_millis=5000)],
                   views=[View(instrument_name="shop.*.duration", aggregation=ExplicitBucketHistogramAggregation(BUCKETS))])
meter = mp.get_meter("shop")
lp = LoggerProvider(resource=res)
lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTLP, insecure=True), schedule_delay_millis=1000))
log = logging.getLogger("shop")
log.setLevel(logging.INFO)
log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
log.addHandler(logging.StreamHandler())

requests_c = meter.create_counter("shop.requests")
req_dur = meter.create_histogram("shop.request.duration", unit="s")
cache_c = meter.create_counter("shop.cache.requests")
ext_c = meter.create_counter("shop.external.calls")
db_dur = meter.create_histogram("shop.db.query.duration", unit="s")
A = {"service": SVC}

# ---- state ---------------------------------------------------------------------------------
pool = None
rds = None
redis_ok = 1.0
faults = {"db_leak": False, "mem_leak": False, "down": False}
leaked_conns, leaked_mem = [], []
proc = psutil.Process()
proc.cpu_percent(None)


def _gauge(name, fn):
    meter.create_observable_gauge(name, callbacks=[lambda o: [Observation(fn(), A)]])


_gauge("shop.cpu.utilization", lambda: min(proc.cpu_percent(None) / 100, 1.0))
_gauge("shop.memory.utilization", lambda: proc.memory_info().rss / MEM_LIMIT)
_gauge("shop.db.pool.utilization", lambda: 1 - pool.get_stats().get("pool_available", POOL) / POOL if pool else 0.0)
if SVC in ("orders", "users"):
    _gauge("shop.redis.up", lambda: redis_ok)


@contextlib.asynccontextmanager
async def lifespan(app):
    global pool, rds
    if SVC != "external":
        pool = AsyncConnectionPool(DSN, min_size=POOL, max_size=POOL, open=False, timeout=1.0)
        await pool.open(wait=True, timeout=30)
        async with pool.connection() as c:
            await c.execute("select pg_advisory_xact_lock(42)")  # services start concurrently
            await c.execute("create table if not exists orders(id serial primary key, user_id int, amount int, ts timestamptz default now())")
        if SVC in ("orders", "users"):
            rds = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"), socket_connect_timeout=0.3, socket_timeout=0.3)
            asyncio.create_task(_redis_watch())
    log.info("INFO %s %s started", SVC, VERSION)
    yield


async def _redis_watch():
    global redis_ok
    while True:
        try:
            await rds.ping()
            redis_ok = 1.0
        except Exception:
            redis_ok = 0.0
        await asyncio.sleep(2)


app = FastAPI(lifespan=lifespan)


@contextlib.asynccontextmanager
async def step(name, kind, parent_err=None):
    """Child span (+ error status). Re-raises so the handler decides the HTTP outcome."""
    with tracer.start_as_current_span(name, attributes={"orbit.kind": kind}) as sp:
        try:
            yield sp
        except Exception as e:
            sp.set_status(Status(StatusCode.ERROR, str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"))
            raise


def fail(request, msg, status=503):
    request.state.err = msg
    log.error("ERROR %s req=%s", msg, request.state.rid)
    return JSONResponse({"error": msg}, status_code=status)


@app.middleware("http")
async def observe(request: Request, call_next):
    if request.url.path in ("/health", "/admin/fault"):
        return await call_next(request)
    request.state.rid, request.state.err = uuid.uuid4().hex[:8], None
    t0 = time.perf_counter()
    with tracer.start_as_current_span(f"{request.method} {request.url.path}", context=extract(request.headers),
                                      kind=SpanKind.SERVER, attributes={"orbit.kind": "server"}) as sp:
        resp = await call_next(request)
        route = request.scope.get("route")
        if route:
            sp.update_name(f"{request.method} {route.path}")
        err = resp.status_code >= 500
        if err:
            sp.set_status(Status(StatusCode.ERROR, request.state.err or "internal error"))
    requests_c.add(1, {**A, "status": "error" if err else "ok"})
    req_dur.record(time.perf_counter() - t0, A)
    return resp


@app.get("/health")
async def health():
    return {"ok": True, "service": SVC, "version": VERSION}


@app.post("/admin/fault")
async def admin_fault(body: dict):
    faults[body["name"]] = bool(body.get("on", True))
    return faults


async def cache_lookup(key):
    async with step("redis.get", "cache"):
        try:
            v = await rds.get(key)
        except Exception as e:  # cache failure degrades to a DB read, it does not fail the request
            cache_c.add(1, {**A, "result": "error"})
            raise RuntimeError(f"ConnectionRefusedError: redis:6379 {type(e).__name__}") from e
        cache_c.add(1, {**A, "result": "hit" if v else "miss"})
        if not v:
            await rds.set(key, "1", ex=30)


async def with_conn(request, work):
    """Acquire a pooled connection (span db.pool.acquire), run work(conn), always release."""
    try:
        async with step("db.pool.acquire", "db"):
            if faults["db_leak"]:  # fault: leak one connection per request until the pool is dry
                leaked_conns.append(await pool.getconn(timeout=1.0))
            conn = await pool.getconn(timeout=1.0)
    except PoolTimeout:
        raise RuntimeError(f"PoolError: connection pool exhausted (max={POOL})")
    try:
        return await work(conn)
    finally:
        await pool.putconn(conn)


async def db_write(conn, user_id, amount):
    async with step("db.query", "db"):
        t = time.perf_counter()
        await conn.execute("insert into orders(user_id, amount) values (%s, %s)", (user_id, amount))
        await conn.commit()
        db_dur.record(time.perf_counter() - t, A)


def _mem_guard(request):
    if faults["mem_leak"]:
        if proc.memory_info().rss / MEM_LIMIT < 0.9:
            leaked_mem.append(b"x" * 512 * 1024)
        elif random.random() < 0.5:
            raise RuntimeError("OutOfMemory: heap usage 97% GC overhead limit exceeded")


@app.post("/orders")
async def orders(request: Request):
    if faults["down"]:
        return fail(request, "service unavailable")
    try:
        _mem_guard(request)
        try:
            await cache_lookup("product:1")
        except RuntimeError as e:
            log.warning("WARN %s req=%s", e, request.state.rid)

        async def work(conn):
            if VERSION == "v2.8.1":  # regression: holds the connection while doing slow batch work
                async with step("OrderRepository.fetch_batch", "internal"):
                    await asyncio.sleep(1.0)
            await db_write(conn, random.randint(1, 100), random.randint(5, 500))

        await with_conn(request, work)
        async with step("payments.charge", "client"):
            h = {}
            inject(h)
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                    r = await c.post(os.environ.get("PAYMENTS_URL", "http://payments:8000") + "/charge", headers=h)
                if r.status_code >= 500:
                    ext_c.add(1, {**A, "status": "error"})
                    raise RuntimeError(f"HTTP {r.status_code} from payments")
                ext_c.add(1, {**A, "status": "ok"})
            except httpx.TimeoutException:
                ext_c.add(1, {**A, "status": "error"})
                raise RuntimeError(f"ReadTimeout: upstream call exceeded timeout={TIMEOUT}s")
        return {"ok": True}
    except Exception as e:
        return fail(request, str(e))


def payments_charge():
    @app.post("/charge")
    async def charge(request: Request):
        try:
            async def work(conn):
                await db_write(conn, 0, 1)
    
            await with_conn(request, work)
            async with step("external_api.call", "external"):
                try:
                    async with httpx.AsyncClient(timeout=2.0) as c:
                        r = await c.post(os.environ.get("EXTERNAL_URL", "http://external:8000") + "/charge")
                except httpx.HTTPError as e:
                    ext_c.add(1, {**A, "status": "error"})
                    raise RuntimeError(f"ConnectionError: api.provider unreachable ({type(e).__name__})")
                if r.status_code >= 500:
                    ext_c.add(1, {**A, "status": "error"})
                    raise RuntimeError(f"api.provider returned {r.status_code} Service Unavailable")
                ext_c.add(1, {**A, "status": "ok"})
            return {"ok": True}
        except Exception as e:
            return fail(request, str(e))


@app.get("/users/{uid}")
async def users(uid: int, request: Request):
    try:
        try:
            await cache_lookup(f"user:{uid % 20}")
        except RuntimeError as e:
            log.warning("WARN %s req=%s", e, request.state.rid)

        async def work(conn):
            async with step("db.query", "db"):
                t = time.perf_counter()
                await (await conn.execute("select count(*) from orders")).fetchone()
                db_dur.record(time.perf_counter() - t, A)

        await with_conn(request, work)
        return {"ok": True}
    except Exception as e:
        return fail(request, str(e))


def external_charge():
    @app.post("/charge")
    async def provider_charge(request: Request):
        await asyncio.sleep(0.04)
        if faults["down"]:
            return JSONResponse({"error": "unavailable"}, status_code=503)
        return {"ok": True}


(external_charge if SVC == "external" else payments_charge)()
