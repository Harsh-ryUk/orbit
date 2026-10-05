"""RealTarget parsing/state logic against canned backend responses (no docker needed)."""
import httpx
import pytest

from orbit.agents import _span_stats
from orbit.real import RealTarget


def target(handler, tmp_path):
    t = RealTarget(state_path=tmp_path / "s.json", compose=False)
    t.http = httpx.Client(transport=httpx.MockTransport(handler))
    return t


def prom(rows):
    return {"status": "success", "data": {"result": [{"metric": m, "value": [0, v]} for m, v in rows]}}


def test_metrics_map_to_orbit_vocabulary_and_drop_nan(tmp_path):
    def h(req):
        q = req.url.params["query"]
        if "shop_redis_up" in q:
            return httpx.Response(200, json=prom([({}, "0")]))
        if q.startswith("(sum by (service)(rate(shop_requests_total{status=\"error\"}"):
            return httpx.Response(200, json=prom([({"service": "orders"}, "0.31"), ({"service": "users"}, "NaN"), ({"service": "external"}, "0.9")]))
        return httpx.Response(200, json=prom([]))
    m = target(h, tmp_path).metrics()
    assert m == {("orders", "error_rate"): 0.31, ("redis", "redis_up"): 0.0}   # NaN dropped, unmonitored service ignored


def test_logs_levels_and_prefix(tmp_path):
    body = {"data": {"result": [{"stream": {"service_name": "orders", "severity_text": "ERROR"},
                                 "values": [["2000000000", "ERROR PoolError: exhausted"], ["1000000000", "WARN slow"]]},
                                {"stream": {"service_name": "users", "severity_text": "WARNING"}, "values": [["3000000000", "plain line"]]}]}}
    L = target(lambda r: httpx.Response(200, json=body), tmp_path).logs(0, 9)
    assert [(l["t"], l["service"], l["level"], l["msg"]) for l in L] == [
        (1.0, "orders", "ERROR", "slow"), (2.0, "orders", "ERROR", "PoolError: exhausted"), (3.0, "users", "WARN", "plain line")]


def span(name, parent, t0, t1, kind, err=None, sid="x"):
    s = {"name": name, "spanId": sid, "startTimeUnixNano": str(int(t0 * 1e9)), "endTimeUnixNano": str(int(t1 * 1e9)),
         "attributes": [{"key": "orbit.kind", "value": {"stringValue": kind}}]}
    if parent:
        s["parentSpanId"] = parent
    if err:
        s["status"] = {"code": 2, "message": err}
    return s


def test_trace_conversion_keeps_root_first_and_cross_service_spans(tmp_path):
    doc = {"batches": [
        {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payments"}}]},
         "scopeSpans": [{"spans": [span("external_api.call", "b", 1.1, 1.2, "external", "503 Service Unavailable", "c")]}]},
        {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "orders"}}]},
         "scopeSpans": [{"spans": [span("db.query", "a", 1.02, 1.05, "db", sid="d"), span("POST /orders", None, 1.0, 1.3, "server", "x", "a")]}]}]}
    tr = RealTarget._convert(doc, "orders")
    assert [s["name"] for s in tr["spans"]] == ["POST /orders", "db.query", "external_api.call"]
    assert tr["spans"][2]["service"] == "payments" and tr["spans"][2]["err"] == "503 Service Unavailable" and tr["spans"][1]["err"] is None
    assert round(tr["spans"][0]["dur"], 2) == 0.3 and tr["service"] == "orders" and tr["t"] == 1.0
    assert _span_stats([tr])["external_api.call"]["errs"] == 1          # the trace agent consumes this shape unchanged


def test_rollback_reverts_the_right_change_and_cannot_be_replayed(tmp_path):
    t = target(lambda r: httpx.Response(404), tmp_path)
    t.inject("bad_deploy", "orders")
    t.inject("config_regression", "payments")
    assert t.state["versions"]["orders"] == "v2.8.1" and t.state["configs"]["payments"] == "timeout=0.05"
    t.apply("rollback_deployment", service="orders", target_version="v2.8.0")
    assert t.state["versions"]["orders"] == "v2.8.0" and t.state["configs"]["payments"] == "timeout=0.05"
    with pytest.raises(ValueError):
        t.apply("rollback_deployment", service="orders", target_version="v2.8.0")
    with pytest.raises(ValueError):
        t.apply("rollback_deployment", service="orders", target_version="v9.9.9")


def test_only_allowlisted_services_and_actions(tmp_path):
    t = target(lambda r: httpx.Response(404), tmp_path)
    for bad in (lambda: t.apply("restart_service", service="postgres"), lambda: t.apply("scale_service", service="orders"),
                lambda: t.apply("rm_rf", path="/")):
        with pytest.raises((ValueError, AttributeError)):
            bad()
