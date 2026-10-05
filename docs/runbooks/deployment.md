---
category: deployment
title: Bad deployment regression
actions:
  - rollback_deployment service=$service target_version=$previous_version
dangerous:
  - database_operation
---
Error rate and latency spike shortly after a deploy, usually with db_pool pressure. Roll the service back to the
previous version. Do not roll back services that were not changed. Verify error rate returns to baseline within 2 minutes.
