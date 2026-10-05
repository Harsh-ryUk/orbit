# ORBIT evaluation (simulator)

Virtual-time simulator; numbers measure the pipeline, not production.

## Summary

- scenarios: 12
- detection accuracy: 100.0%
- RCA accuracy: 91.7%
- handled correctly (recovered or correctly escalated): 100.0%
- recovery success (fixable incidents): 100.0%
- remediation accuracy (recovered / actions executed): 90.0%
- wrong-action rate (actions outside ground-truth fix set): 10.0%
- human intervention rate: 58.3%
- mean MTTR, simulated seconds: 333.3
- mean investigation wall time, ms: 13.0

## Scenarios

| scenario | RCA | conf | final | actions | approvals | MTTR s |
|---|---|---|---|---|---|---|
| bad_deploy | ok | 80% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| bad_deploy_payments | ok | 80% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| db_exhaustion | ok | 94% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| db_exhaustion_decoy_deploy | WRONG | 80% | RECOVERED (want RECOVERED) | rollback_deployment, restart_service | 2 | 600 |
| config_regression | ok | 95% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| cpu_saturation | ok | 91% | RECOVERED (want RECOVERED) | scale_service | 0 | 300 |
| memory_leak | ok | 91% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| memory_leak_decoy_other_service_deploy | ok | 91% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| redis_down | ok | 95% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| dependency_down | ok | 98% | ESCALATED (want ESCALATED) | - | 0 | None |
| dependency_down_decoy_old_deploy | ok | 98% | ESCALATED (want ESCALATED) | - | 0 | None |
| network_latency | ok | 94% | ESCALATED (want ESCALATED) | - | 0 | None |
