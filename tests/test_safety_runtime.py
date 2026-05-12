from __future__ import annotations

from dazro_trade.core.config import Settings
from dazro_trade.execution.demo_executor import DemoExecutor
from dazro_trade.notifications.telegram_bot import TelegramBot, format_signal_message
from dazro_trade.paper.ledger import PaperLedger
from dazro_trade.risk.manager import RiskManager
from dazro_trade.risk.sizing import suggested_lot_size
from dazro_trade.risk.validation import validate_trade


def valid_signal():
    return {"signal_id": "sig-1", "symbol": "XAUUSD", "direction": "BUY", "entry": 100.0, "sl": 99.0, "tp": 103.0, "lot_size": 0.1}


def test_risk_validation_and_sizing():
    settings = Settings(min_rr=2.0, max_spread_pips=30)
    result = validate_trade(valid_signal(), settings, spread=1)
    assert result["accepted"]
    assert suggested_lot_size(10000, 0.005, 100, 99) == 0.5
    bad = validate_trade({"direction": "BUY", "entry": 100, "sl": 101, "tp": 102}, settings)
    assert "impossible_sl_direction" in bad["rejection_reasons"]


def test_risk_manager_duplicate_rejection():
    manager = RiskManager(Settings())
    assert manager.validate(valid_signal())["accepted"]
    manager.register_signal("sig-1")
    assert "duplicate_signal" in manager.validate(valid_signal())["rejection_reasons"]


def test_ledger_write_read(tmp_path):
    db = tmp_path / "ledger.sqlite"
    ledger = PaperLedger(str(db))
    row = {
        "timestamp": "2026-05-11T00:00:00Z",
        "signal_id": "sig-1",
        "setup_type": "CRT",
        "direction": "BUY",
        "entry": 100,
        "sl": 99,
        "tp": 103,
        "rr": 3,
        "lot_size": 0.5,
        "risk_pct": 0.005,
        "final_decision": "paper",
    }
    ledger.insert_trade(row)
    assert ledger.count() == 1
    assert ledger.fetch_trade("sig-1")["direction"] == "BUY"


def test_telegram_formatting_and_missing_credentials():
    message = format_signal_message({**valid_signal(), "rr": 3, "risk_pct": 0.005, "timestamp_utc": "now"})
    assert "Paper/demo signal only. No real-money execution." in message
    assert TelegramBot(Settings(telegram_enabled=True)).send_signal(valid_signal())["ok"] is False


def test_demo_executor_safety_lock_disabled():
    assert DemoExecutor(enabled=False).place_order(valid_signal())["reason"] == "demo_execution_disabled"


def test_demo_executor_rejects_unverified_account():
    class MT5:
        @staticmethod
        def account_info():
            return None

    settings = Settings(demo_execution=True, mt5_login="1", mt5_password="x", mt5_server="Demo")
    assert DemoExecutor(settings, mt5_module=MT5()).place_order(valid_signal(), {"accepted": True})["reason"] == "account_type_unverified_or_live"


def test_demo_executor_mock_demo_account():
    class Account:
        trade_mode = "demo"
        server = "Demo"
        name = "Demo"

    class Result:
        retcode = 10009
        order = 123

    class MT5:
        @staticmethod
        def account_info():
            return Account()

        @staticmethod
        def order_send(request):
            return Result()

    settings = Settings(demo_execution=True, mt5_login="1", mt5_password="x", mt5_server="Demo")
    result = DemoExecutor(settings, mt5_module=MT5()).place_order(valid_signal(), {"accepted": True})
    assert result["ok"] is True
