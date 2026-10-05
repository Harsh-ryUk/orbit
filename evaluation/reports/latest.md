# ORBIT evaluation (simulator)

Virtual-time simulator; numbers measure the pipeline, not production.

## Summary

- scenarios: 12
- detection accuracy: 100.0%
- RCA accuracy: 100.0%
- handled correctly (recovered or correctly escalated): 100.0%
- recovery success (fixable incidents): 100.0%
- remediation accuracy (recovered / actions executed): 100.0%
- wrong-action rate (actions outside ground-truth fix set): 0.0%
- human intervention rate: 50.0%
- mean MTTR, simulated seconds: 300.0
- mean investigation wall time, ms: 16.3

## Scenarios

| scenario | RCA | conf | final | actions | approvals | MTTR s |
|---|---|---|---|---|---|---|
| bad_deploy | ok | 92% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| bad_deploy_payments | ok | 92% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| db_exhaustion | ok | 100% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| db_exhaustion_decoy_deploy | ok | 85% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| config_regression | ok | 99% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 300 |
| cpu_saturation | ok | 99% | RECOVERED (want RECOVERED) | scale_service | 0 | 300 |
| memory_leak | ok | 98% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| memory_leak_decoy_other_service_deploy | ok | 98% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| redis_down | ok | 99% | RECOVERED (want RECOVERED) | restart_service | 0 | 300 |
| dependency_down | ok | 100% | ESCALATED (want ESCALATED) | - | 0 | None |
| dependency_down_decoy_old_deploy | ok | 100% | ESCALATED (want ESCALATED) | - | 0 | None |
| network_latency | ok | 99% | ESCALATED (want ESCALATED) | - | 0 | None |

## Ablation: do logs + traces help?

| metric | metrics only | + logs & traces |
|---|---|---|
| RCA accuracy | 91.7% | 100.0% |
| handled correctly (recovered or correctly escalated) | 100.0% | 100.0% |
| wrong-action rate (actions outside ground-truth fix set) | 10.0% | 0.0% |
| mean MTTR, simulated seconds | 333 | 300 |
