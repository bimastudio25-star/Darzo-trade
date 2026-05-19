from __future__ import annotations

from pathlib import Path


NEW_RESEARCH_FILES = [
    Path("dazro_trade/analysis/human_trade_management.py"),
    Path("dazro_trade/analysis/local_ai_trade_judge.py"),
    Path("dazro_trade/analytics/strategy_2_hourly_session_diagnostics.py"),
    Path("scripts/analyze_human_trade_management_overlay.py"),
]


def test_new_research_modules_do_not_call_broker_or_telegram_execution():
    joined = "\n".join(path.read_text(encoding="utf-8") for path in NEW_RESEARCH_FILES)
    forbidden_call_patterns = [
        "order_send(",
        ".order_send",
        "send_signal(",
        ".send_signal",
        "send_text(",
        ".send_text",
        "send_message(",
        ".send_message",
        "run_telegram_polling(",
    ]
    for pattern in forbidden_call_patterns:
        assert pattern not in joined


def test_new_research_modules_do_not_import_live_runtime_or_notifications():
    import_lines = []
    for path in NEW_RESEARCH_FILES:
        text = path.read_text(encoding="utf-8")
        import_lines.extend(line for line in text.splitlines() if line.startswith("import ") or line.startswith("from "))
    imports = "\n".join(import_lines)
    assert "dazro_trade.notifications" not in imports
    assert "dazro_trade.runtime" not in imports
    assert "dazro_trade.execution" not in imports
    assert "MetaTrader5" not in imports
