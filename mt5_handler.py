import logging
import time
import MetaTrader5 as mt5
import pandas as pd
from config import TIMEFRAMES
from dazro_trade.core.symbols import get_symbol_spec

log = logging.getLogger(__name__)


class MT5Handler:
    def __init__(self, login: str, password: str, server: str):
        self.login = int(login) if login else None
        self.password = password
        self.server = server
        self.symbol = None

    def connect(self, retries: int = 3) -> bool:
        for i in range(retries):
            ok = mt5.initialize(login=self.login, password=self.password, server=self.server)
            if ok:
                return True
            log.error("MT5 initialize fallito: %s", mt5.last_error())
            time.sleep(2)
        return False

    def shutdown(self):
        mt5.shutdown()

    def terminal_name(self) -> str:
        info = mt5.terminal_info()
        return info.name if info else "Unknown"

    def resolve_symbol(self, candidates: list[str]) -> str | None:
        for s in candidates:
            if mt5.symbol_info(s):
                self.symbol = s
                return s
        return None

    def get_candles(self, tf: str, n: int) -> pd.DataFrame:
        try:
            rates = mt5.copy_rates_from_pos(self.symbol, getattr(mt5, f"TIMEFRAME_{tf}"), 0, n)
            if rates is None or len(rates) == 0:
                return pd.DataFrame()
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"})
            columns = ["time", "o", "h", "l", "c", "vol"]
            for optional in ("spread", "real_volume"):
                if optional in df.columns:
                    columns.append(optional)
            return df[columns]
        except Exception as e:
            log.error("Errore get_candles %s: %s", tf, e)
            return pd.DataFrame()

    def get_price(self) -> float:
        tick = mt5.symbol_info_tick(self.symbol)
        return round((tick.ask + tick.bid) / 2, 2) if tick else 0.0

    def get_tick_snapshot(self) -> dict:
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return {"symbol": self.symbol, "ok": False, "reason": "tick_unavailable"}
        spec = get_symbol_spec(self.symbol or "XAUUSD")
        bid = float(tick.bid)
        ask = float(tick.ask)
        mid = round((ask + bid) / 2, spec.digits)
        spread_price = abs(ask - bid)
        return {
            "symbol": self.symbol,
            "ok": True,
            "bid": round(bid, spec.digits),
            "ask": round(ask, spec.digits),
            "mid": mid,
            "spread_price": round(spread_price, spec.digits),
            "spread_pips": round(spread_price / spec.pip_size, 2),
            "time": getattr(tick, "time", None),
        }

    def get_spread_pips(self, pip_value: float | None = None) -> tuple[float, bool]:
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return 999.0, False
        spec = get_symbol_spec(self.symbol or "XAUUSD")
        spread = abs(tick.ask - tick.bid) / (pip_value or spec.pip_size)
        return round(spread, 2), True
