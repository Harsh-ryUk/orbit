---
category: cache
title: Redis unavailable
actions:
  - restart_service service=redis
---
Cache hit ratio collapses and backend load rises when Redis is down. Restart redis; services recover as the cache refills.
