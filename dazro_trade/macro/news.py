from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TTLCache:
    ttl_seconds: int = 300
    values: dict[str, tuple[float, Any]] = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        item = self.values.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl_seconds:
            self.values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self.values[key] = (time.time(), value)


class NewsClient:
    def __init__(self, api_key: str = "", fetcher: Callable[..., Any] | None = None, cache: TTLCache | None = None):
        self.api_key = api_key
        self.fetcher = fetcher
        self.cache = cache or TTLCache()

    def high_impact_usd_block(self) -> dict:
        if not self.api_key and self.fetcher is None:
            return {"blocked": False, "state": "uncertain", "reason": "news_api_not_configured"}
        cached = self.cache.get("usd_events")
        if cached is not None:
            return cached
        try:
            events = self.fetcher() if self.fetcher else []
            blocked = any(str(event.get("currency", "")).upper() == "USD" and str(event.get("impact", "")).lower() == "high" for event in events)
            result = {"blocked": blocked, "state": "risk_off" if blocked else "clear", "reason": "high_impact_usd_event" if blocked else "no_high_impact_usd_event"}
        except Exception as exc:
            result = {"blocked": False, "state": "uncertain", "reason": f"news_fetch_failed:{exc.__class__.__name__}"}
        self.cache.set("usd_events", result)
        return result
