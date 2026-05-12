import logging
from datetime import datetime, timedelta, timezone
import requests

log = logging.getLogger(__name__)


class NewsHandler:
    def __init__(self, news_api_key: str, tavily_api_key: str):
        self.news_api_key = news_api_key
        self.tavily_api_key = tavily_api_key
        self._news_cache = []
        self._news_ts = None
        self._tavily_cache = ""
        self._tavily_ts = None

    def _now(self):
        return datetime.now(timezone.utc)

    def latest_news(self):
        if self._news_ts and (self._now() - self._news_ts).total_seconds() < 1800:
            return self._news_cache
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": "gold OR XAU OR Federal Reserve OR inflation OR geopolitical",
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 5,
                    "apiKey": self.news_api_key,
                },
                timeout=15,
            )
            r.raise_for_status()
            items = r.json().get("articles", [])[:5]
            self._news_cache = [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "source": (a.get("source") or {}).get("name", ""),
                    "timestamp": a.get("publishedAt", ""),
                }
                for a in items
            ]
            self._news_ts = self._now()
        except Exception as e:
            log.warning("NewsAPI error: %s", e)
        return self._news_cache

    def ff_events(self):
        try:
            r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15)
            r.raise_for_status()
            data = r.json()
            out = []
            now = self._now()
            for e in data:
                if e.get("impact") != "High":
                    continue
                cur = (e.get("currency") or "").upper()
                title = (e.get("title") or "")
                if cur != "USD" and "XAU" not in title.upper():
                    continue
                dt = e.get("date")
                tm = e.get("time")
                if not dt or not tm or "All Day" in tm:
                    continue
                try:
                    ev = datetime.fromisoformat(f"{dt}T{tm}:00+00:00")
                except Exception:
                    continue
                delta = (ev - now).total_seconds() / 60
                out.append({"title": title, "currency": cur, "impact": "High", "event_time": ev.isoformat(), "minutes_to_event": int(delta)})
            out.sort(key=lambda x: x["minutes_to_event"])
            return out
        except Exception as e:
            log.warning("FF calendar error: %s", e)
            return []

    def tavily_summary(self):
        if self._tavily_ts and (self._now() - self._tavily_ts).total_seconds() < 3600:
            return self._tavily_cache
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": "XAU USD gold price news today geopolitical",
                    "max_results": 3,
                },
                timeout=20,
            )
            r.raise_for_status()
            res = r.json().get("results", [])[:3]
            self._tavily_cache = " | ".join([x.get("content", "")[:180] for x in res if x.get("content")])
            self._tavily_ts = self._now()
        except Exception as e:
            log.warning("Tavily error: %s", e)
        return self._tavily_cache

    @staticmethod
    def event_block(events):
        near = [e for e in events if 0 <= e.get("minutes_to_event", 9999) <= 30]
        return (len(near) > 0, near[0] if near else None)

    @staticmethod
    def upcoming_4h(events):
        return [e for e in events if 0 <= e.get("minutes_to_event", 9999) <= 240]

    @staticmethod
    def next_event_text(events):
        if not events:
            return "Nessuno"
        e = min(events, key=lambda x: x.get("minutes_to_event", 9999))
        mins = max(0, e.get("minutes_to_event", 0))
        h, m = mins // 60, mins % 60
        return f"{e.get('title','Evento')} tra {h}h {m}min ⚠️"
