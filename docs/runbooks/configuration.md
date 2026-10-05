---
category: configuration
title: Configuration regression
actions:
  - rollback_deployment service=$service target_version=$previous_version
---
A config change (timeouts, env vars) preceded the incident. Revert to the last known-good config. Restarting does not help.
