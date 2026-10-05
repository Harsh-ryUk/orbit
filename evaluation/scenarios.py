"""Reproducible fault scenarios with ground truth. `fix` = acceptable remediation tools; empty = should escalate."""
from dataclasses import dataclass
from typing import Callable


@dataclass
class Scenario:
    name: str
    setup: Callable          # (sim) -> None; injects the fault (may advance time for decoys)
    category: str            # ground-truth root-cause category
    service: str             # ground-truth affected service
    fix: tuple = ()          # acceptable remediation tools; () => correct behavior is to escalate


def _d(sim, svc, secs):  # decoy: benign deploy `secs` before the fault
    sim.benign_deploy(svc)
    sim.wait(secs)


SCENARIOS = [
    Scenario("bad_deploy", lambda s: s.inject("bad_deploy", "orders", delay=228), "deployment", "orders", ("rollback_deployment",)),
    Scenario("bad_deploy_payments", lambda s: s.inject("bad_deploy", "payments", delay=120), "deployment", "payments", ("rollback_deployment",)),
    Scenario("db_exhaustion", lambda s: s.inject("db_exhaustion", "orders"), "database", "orders", ("restart_service",)),
    Scenario("db_exhaustion_decoy_deploy", lambda s: (_d(s, "orders", 300), s.inject("db_exhaustion", "orders")), "database", "orders", ("restart_service",)),
    Scenario("config_regression", lambda s: s.inject("config_regression", "orders", delay=60), "configuration", "orders", ("rollback_deployment",)),
    Scenario("cpu_saturation", lambda s: s.inject("cpu_saturation", "orders"), "cpu", "orders", ("scale_service",)),
    Scenario("memory_leak", lambda s: s.inject("memory_leak", "orders"), "memory", "orders", ("restart_service",)),
    Scenario("memory_leak_decoy_other_service_deploy", lambda s: (_d(s, "users", 200), s.inject("memory_leak", "orders")), "memory", "orders", ("restart_service",)),
    Scenario("redis_down", lambda s: s.inject("redis_down", "redis"), "cache", "orders", ("restart_service",)),
    Scenario("dependency_down", lambda s: s.inject("dependency_down", "orders"), "dependency", "orders"),
    Scenario("dependency_down_decoy_old_deploy", lambda s: (_d(s, "orders", 600), s.inject("dependency_down", "orders")), "dependency", "orders"),
    Scenario("network_latency", lambda s: s.inject("network_latency", "orders"), "network", "orders"),
]
