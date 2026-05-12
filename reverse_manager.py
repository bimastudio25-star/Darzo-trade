from datetime import datetime, timedelta, timezone
import uuid


class ReverseManager:
    def __init__(self):
        self.active_trades = []
        self.force_reverse_analysis_flag = False

    def add_trade(self, signal: dict, reverse_levels: dict):
        trade = {
            "id": str(uuid.uuid4()),
            "direction": signal.get("direction"),
            "entry": signal.get("entry"),
            "sl": signal.get("sl"),
            "tp1": signal.get("tp1"),
            "tp2": signal.get("tp2"),
            "reverse_level": reverse_levels.get("reverse_level"),
            "reverse_reason": reverse_levels.get("reverse_reason", ""),
            "invalidation_level": reverse_levels.get("invalidation_level"),
            "sent_at": datetime.now(timezone.utc),
            "status": "active",
            "bias_at_entry": signal.get("bias_h1", "neutral"),
            "alerts_sent": set(),
        }
        self.active_trades.append(trade)

    def check_all_trades(self, current_price: float, current_bias: str):
        alerts = []
        for t in self.active_trades:
            if t["status"] != "active":
                continue
            is_buy = t["direction"] == "BUY"
            if is_buy and t.get("sl") and current_price < t["sl"] and "sl_hit" not in t["alerts_sent"]:
                t["status"] = "sl_hit"; t["alerts_sent"].add("sl_hit")
                alerts.append(("sl_hit", t))
            if (not is_buy) and t.get("sl") and current_price > t["sl"] and "sl_hit" not in t["alerts_sent"]:
                t["status"] = "sl_hit"; t["alerts_sent"].add("sl_hit")
                alerts.append(("sl_hit", t))
            if is_buy and t.get("tp1") and current_price >= t["tp1"] and "tp1_hit" not in t["alerts_sent"]:
                t["alerts_sent"].add("tp1_hit")
                alerts.append(("tp1_hit", t))
            if (not is_buy) and t.get("tp1") and current_price <= t["tp1"] and "tp1_hit" not in t["alerts_sent"]:
                t["alerts_sent"].add("tp1_hit")
                alerts.append(("tp1_hit", t))
            inv = t.get("invalidation_level")
            if inv is not None:
                cond = (is_buy and current_price < inv) or ((not is_buy) and current_price > inv)
                if cond and "invalidated" not in t["alerts_sent"]:
                    t["status"] = "invalidated"; t["alerts_sent"].add("invalidated")
                    alerts.append(("invalidated", t))
                    self.force_reverse_analysis_flag = True
            rv = t.get("reverse_level")
            if rv is not None:
                cond = (is_buy and current_price >= rv) or ((not is_buy) and current_price <= rv)
                if cond and "reverse_zone" not in t["alerts_sent"]:
                    t["alerts_sent"].add("reverse_zone")
                    alerts.append(("reverse_zone", t))
            if current_bias and current_bias != t.get("bias_at_entry") and "structure_flip" not in t["alerts_sent"]:
                t["status"] = "invalidated"; t["alerts_sent"].add("structure_flip")
                alerts.append(("structure_flip", t))
                self.force_reverse_analysis_flag = True
        return alerts

    def remove_expired(self):
        now = datetime.now(timezone.utc)
        keep = []
        for t in self.active_trades:
            age = now - t["sent_at"]
            if t["status"] in {"sl_hit", "tp2_hit", "invalidated"}:
                continue
            if age > timedelta(hours=8):
                continue
            keep.append(t)
        self.active_trades = keep

    def get_active_count(self):
        return len([t for t in self.active_trades if t["status"] == "active"])

    def force_reverse_analysis(self):
        return self.force_reverse_analysis_flag

    def clear_force_flag(self):
        self.force_reverse_analysis_flag = False
