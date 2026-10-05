---
category: memory
title: Memory leak
actions:
  - restart_service service=$service
---
Memory climbing toward the limit leads to OOM and restart loops. Restart to reclaim memory, then file a bug for the leak.
