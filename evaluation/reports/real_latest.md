# ORBIT evaluation (real docker stack: OTel -> Prometheus/Loki/Tempo)

Real containers and real telemetry on one laptop; wall-clock times.

## Summary

- scenarios: 2
- detection accuracy: 100.0%
- RCA accuracy: 100.0%
- handled correctly (recovered or correctly escalated): 100.0%
- recovery success (fixable incidents): 100.0%
- remediation accuracy (recovered / actions executed): 100.0%
- wrong-action rate (actions outside ground-truth fix set): 0.0%
- human intervention rate: 0.0%
- mean MTTR, seconds: 92.5
- mean investigation wall time, ms: 92458.7

## Scenarios

| scenario | RCA | conf | final | actions | approvals | MTTR s |
|---|---|---|---|---|---|---|
| redis_down | ok | 99% | RECOVERED (want RECOVERED) | restart_service | 0 | 62 |
| redis_down | ok | 99% | RECOVERED (want RECOVERED) | restart_service | 0 | 123 |
