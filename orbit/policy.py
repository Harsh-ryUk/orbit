"""Policy engine: final execution decision = most restrictive of Laya, action policy, evidence quality."""
import yaml

_ORDER = ["AUTO_EXECUTE", "HUMAN_APPROVAL", "BLOCK"]


class Policy:
    def __init__(self, path):
        self.cfg = yaml.safe_load(open(path))

    def decide(self, tool_name, laya_approval, rca_confidence):
        reasons, verdicts = [], [laya_approval]
        rule = self.cfg["actions"].get(tool_name)
        if rule is None:
            return dict(decision="BLOCK", reasons=[f"{tool_name} has no policy entry"])
        if rule.get("approval_required") or not rule.get("auto_execute"):
            verdicts.append("HUMAN_APPROVAL")
            reasons.append(f"policy: {tool_name} requires approval (risk {rule['risk']})")
        if self.cfg["autonomy_level"] < 4:
            verdicts.append("HUMAN_APPROVAL")
            reasons.append(f"autonomy level {self.cfg['autonomy_level']} < 4")
        if rca_confidence < self.cfg["min_rca_confidence"]:
            verdicts.append("HUMAN_APPROVAL")
            reasons.append(f"RCA confidence {rca_confidence:.0%} below {self.cfg['min_rca_confidence']:.0%}")
        if laya_approval != "AUTO_EXECUTE":
            reasons.append(f"laya: {laya_approval}")
        return dict(decision=max(verdicts, key=_ORDER.index), reasons=reasons or ["policy: auto-execute permitted"])
