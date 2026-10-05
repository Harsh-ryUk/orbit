# ORBIT evaluation (real docker stack: OTel -> Prometheus/Loki/Tempo)

Real containers and real telemetry on one laptop; wall-clock times. n=7, one run each (no repeats, no variance estimate).
`bad_deploy` was run in a separate earlier invocation; the other six in one batch (`python -m evaluation.real <names>`).

## Summary

- scenarios: 7
- detection accuracy: 100.0%
- RCA accuracy: 100.0%
- handled correctly (recovered or correctly escalated): 100.0%
- recovery success (fixable incidents, 6): 100.0%
- remediation accuracy (recovered / actions executed): 100.0%
- wrong-action rate (actions outside ground-truth fix set): 0.0%
- human intervention rate (approvals + escalations): 42.9%
- mean MTTR, seconds (detection to verified recovery, 6 recovered): 77.5

## Scenarios

| scenario | RCA | conf | final | actions | approvals | MTTR s |
|---|---|---|---|---|---|---|
| bad_deploy | ok | 92% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 130 |
| db_exhaustion | ok | 100% | RECOVERED (want RECOVERED) | restart_service | 0 | 65 |
| db_exhaustion_decoy_deploy | ok | 85% | RECOVERED (want RECOVERED) | restart_service | 0 | 65 |
| config_regression | ok | 98% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 66 |
| memory_leak | ok | 98% | RECOVERED (want RECOVERED) | restart_service | 0 | 66 |
| redis_down | ok | 99% | RECOVERED (want RECOVERED) | restart_service | 0 | 72 |
| dependency_down | ok | 100% | ESCALATED (want ESCALATED) | - | 0 | None |
