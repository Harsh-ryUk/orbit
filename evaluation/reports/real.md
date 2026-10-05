# ORBIT evaluation (real docker stack: OTel -> Prometheus/Loki/Tempo)

Real containers and real telemetry on one laptop; wall-clock times.

## Summary

- scenarios: 1
- detection accuracy: 100.0%
- RCA accuracy: 100.0%
- handled correctly (recovered or correctly escalated): 100.0%
- recovery success (fixable incidents): 100.0%
- remediation accuracy (recovered / actions executed): 100.0%
- wrong-action rate (actions outside ground-truth fix set): 0.0%
- human intervention rate: 100.0%
- mean MTTR, seconds: 129.5
- mean investigation wall time, ms: 129535.1

## Scenarios

| scenario | RCA | conf | final | actions | approvals | MTTR s |
|---|---|---|---|---|---|---|
| bad_deploy | ok | 92% | RECOVERED (want RECOVERED) | rollback_deployment | 1 | 130 |
