"""Steady synthetic traffic so baselines exist. Open-loop Poisson arrivals: rate is independent of response time."""
import asyncio
import os
import random

import httpx

TARGETS = [(os.environ.get("ORDERS_URL", "http://orders:8000") + "/orders", "POST", float(os.environ.get("RPS_ORDERS", "8"))),
           (os.environ.get("USERS_URL", "http://users:8000") + "/users/{}", "GET", float(os.environ.get("RPS_USERS", "3")))]


async def one(c, url, method):
    try:
        await c.request(method, url.format(random.randint(1, 100)))
    except Exception:
        pass


async def stream(c, url, method, rps):
    while True:
        await asyncio.sleep(random.expovariate(rps))
        asyncio.create_task(one(c, url, method))


async def main():
    async with httpx.AsyncClient(timeout=4.0, limits=httpx.Limits(max_connections=200)) as c:
        await asyncio.gather(*(stream(c, *t) for t in TARGETS))


asyncio.run(main())
