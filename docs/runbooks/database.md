---
category: database
title: Database connection exhaustion
actions:
  - restart_service service=$service
dangerous:
  - database_operation
---
Pool utilization pinned near 100% without a recent change implies leaked connections. Restart the service to release them.
Never kill sessions or fail over the database automatically.
