"""Remediation tool registry. The only way ORBIT touches the target: allowlisted, typed, risk-rated."""
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    label: str                 # Laya's action vocabulary
    description: str
    params: tuple
    risk: str                  # LOW | MEDIUM | HIGH | CRITICAL
    permissions: str
    rollback_strategy: str
    verification_strategy: str


_VERIFY = "all metrics anomalous at incident time return inside their healthy thresholds"
TOOLS = {t.name: t for t in [
    Tool("restart_service", "restart", "Restart a service (or redis)", ("service",), "LOW",
         "svc:restart", "none (stateless restart)", _VERIFY),
    Tool("scale_service", "scale", "Add capacity to a service", ("service",), "LOW",
         "svc:scale", "scale back to previous replica count", _VERIFY),
    Tool("clear_cache", "clear_cache", "Clear a service's cache", ("service",), "LOW",
         "cache:clear", "none (cache refills)", _VERIFY),
    Tool("rollback_deployment", "rollback", "Roll a service back to a previous version/config", ("service", "target_version"),
         "HIGH", "deploy:rollback", "redeploy the version rolled back from", _VERIFY),
]}
NO_ACTION = "no_action"


def run(target, name, params):
    """Execute an allowlisted tool with exactly its declared params. Raises on anything else."""
    tool = TOOLS.get(name)
    if tool is None:
        raise PermissionError(f"tool {name!r} is not in the allowlist")
    if set(params) != set(tool.params):
        raise ValueError(f"{name} takes exactly {tool.params}, got {tuple(params)}")
    return target.apply(name, **params)
