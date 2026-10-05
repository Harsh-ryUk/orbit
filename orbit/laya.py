"""Laya decision layer interface + a transparent heuristic stand-in.

`HeuristicLaya` is NOT Laya. It is the baseline that implements the same bounded-decision contract
so the pipeline, policy gate and evaluation harness run end to end. Swap in the real model by
implementing `decide(category, payload) -> Decision` (same labels) and passing it to Orbit.
"""
import time
from dataclasses import dataclass, asdict

from .tools import TOOLS, NO_ACTION


@dataclass
class Decision:
    category: str
    label: str
    confidence: float
    rationale: str
    latency_ms: float = 0.0
    engine: str = "laya-heuristic"

    def dict(self):
        return asdict(self)


class HeuristicLaya:
    def decide(self, category, payload):
        t0 = time.perf_counter()
        label, conf, why = getattr(self, "_" + category)(**payload)
        return Decision(category, label, conf, why, (time.perf_counter() - t0) * 1000)

    def _severity(self, error_rate, services_affected):
        if error_rate >= 0.25 or services_affected >= 3:
            return "P0", 0.8, f"error_rate {error_rate:.0%}, {services_affected} service(s) affected"
        if error_rate >= 0.10 or services_affected >= 2:
            return "P1", 0.75, f"error_rate {error_rate:.0%}, {services_affected} service(s) affected"
        return ("P2" if error_rate >= 0.05 else "P3"), 0.7, f"error_rate {error_rate:.0%}"

    def _action(self, candidates, tried, rca_confidence):
        """Pick the first untried candidate (candidates are ordered by hypothesis rank)."""
        for c in candidates:
            if c["key"] not in tried:
                return c["label"], round(rca_confidence * (1.0 if c["rank"] == 1 else 0.7), 3), \
                    f"top untried action from hypothesis #{c['rank']} ({c['category']})"
        return NO_ACTION, 0.9, "no safe untried action available"

    def _risk(self, tool):
        return (TOOLS[tool].risk if tool in TOOLS else "CRITICAL"), 1.0, "tool registry risk rating"

    def _approval(self, risk, confidence):
        if risk in ("HIGH", "CRITICAL"):
            return "HUMAN_APPROVAL", 0.95, f"risk {risk}"
        if confidence < 0.7:
            return "HUMAN_APPROVAL", 0.8, f"confidence {confidence:.0%} < 70%"
        return "AUTO_EXECUTE", 0.8, f"risk {risk}, confidence {confidence:.0%}"

    def _recovery(self, verification):
        return verification["status"], 0.9, f"{verification['healthy']}/{verification['total']} metrics healthy"

    def _escalation(self, attempts, max_attempts, no_action):
        if no_action or attempts >= max_attempts:
            return "ESCALATE", 0.95, "no action left" if no_action else f"{attempts} failed attempts"
        return "CONTINUE", 0.8, f"{attempts}/{max_attempts} attempts used"
