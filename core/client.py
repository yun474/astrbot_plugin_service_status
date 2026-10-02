import asyncio
import time
from dataclasses import replace

import aiohttp

from .statuspage import StatuspageAdapter
from .uptime import fetch_uptime

ADAPTERS = {"statuspage": StatuspageAdapter}


class StatusClient:
    def __init__(self):
        self._cache = {}
        self._locks = {}

    async def fetch(self, service, timeout=15, cache_seconds=60, proxy="", show_uptime=True):
        key = (
            service.id,
            service.url,
            service.adapter,
            proxy,
            show_uptime,
        )
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < cache_seconds:
                return cached[1]
            adapter = ADAPTERS[service.adapter]()
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
                trust_env=True,
                headers={"User-Agent": "AstrBot-ServiceStatus", "Accept": "application/json"},
            ) as session:
                snapshot = await adapter.fetch(service, session, proxy)
                if show_uptime and service.uptime_source:
                    try:
                        uptime = await fetch_uptime(service, snapshot, session, proxy)
                    except (
                        aiohttp.ClientError,
                        asyncio.TimeoutError,
                        ValueError,
                        KeyError,
                        TypeError,
                    ):
                        uptime = {}
                    snapshot = replace(snapshot, uptime=uptime)
                if not show_uptime:
                    snapshot = replace(snapshot, uptime={})
            self._cache[key] = (time.monotonic(), snapshot)
            return snapshot

    def clear(self):
        self._cache.clear()
        self._locks.clear()
