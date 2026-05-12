from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RiskState:
    day: str = ""
    sent: int = 0
    discarded: int = 0
    fingerprints: dict = field(default_factory=dict)


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = RiskState()

    def _roll_day(self):
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day != d:
            self.state = RiskState(day=d)

    def validate_signal(self, sig: dict):
        self._roll_day()
        checks = [
            (self.cfg["sl_pips_min"] <= sig.get("sl_pips", 0) <= self.cfg["sl_pips_max"], "sl_pips fuori range"),
            (sig.get("tp_pips", 0) >= self.cfg["tp_pips_min"], "tp_pips troppo basso"),
            (sig.get("rr", 0) >= self.cfg["rr_min"], "rr troppo basso"),
            (sig.get("confidence", 0) >= self.cfg["conf_min"], "confidence troppo bassa"),
        ]
        for ok, reason in checks:
            if not ok:
                self.state.discarded += 1
                return False, reason
        return True, "ok"

    def can_send(self):
        self._roll_day()
        return self.state.sent < self.cfg["daily_max_signals"]

    def is_duplicate(self, sig: dict, now_ts: float):
        fp = f"{sig.get('direction')}_{round(sig.get('entry', 0), 0)}"
        for k, t in list(self.state.fingerprints.items()):
            if now_ts - t > self.cfg["dedup_cleanup_sec"]:
                del self.state.fingerprints[k]
        last = self.state.fingerprints.get(fp)
        if last and (now_ts - last) < self.cfg["dedup_window_sec"]:
            self.state.discarded += 1
            return True
        self.state.fingerprints[fp] = now_ts
        return False

    def mark_sent(self):
        self.state.sent += 1
