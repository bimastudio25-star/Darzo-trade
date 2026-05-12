from dazro_trade.analysis.crt import detect_crt
from dazro_trade.structure.line_structure import close_based_bos, choch
from dazro_trade.liquidity.pools import equal_highs_lows
from dazro_trade.quarterly.quarterly_theory import classify_quarter
from dazro_trade.smt.divergence import smt_divergence
from dazro_trade.risk.manager import RiskManager
from dazro_trade.paper.ledger import PaperLedger
from dazro_trade.notifications.telegram_format import format_signal_message
from dazro_trade.execution.demo_executor import DemoExecutor
from dazro_trade.runtime.config import Settings


def test_crt_bearish_detect():
    c = [
        {'h':10,'l':9,'c':9.7},
        {'h':10.5,'l':9.2,'c':10.1},
        {'h':10.1,'l':9.1,'c':9.8},
    ]
    out = detect_crt(c)
    assert out and out['type'] == 'bearish_crt'


def test_line_structure_and_choch():
    assert close_based_bos([1,2,3], 2.5, 'bullish')
    assert choch('bullish','bearish')


def test_liquidity_equal_levels():
    assert equal_highs_lows([10,10.03,11], 0.05)


def test_quarterly_and_smt():
    assert classify_quarter(5) == 'Q2'
    assert smt_divergence([1,2],[2,1])


def test_risk_manager_limits():
    rm = RiskManager(max_daily_signals=1, max_consecutive_losses=2)
    assert rm.can_signal()
    rm.register_signal()
    assert not rm.can_signal()


def test_ledger_persist(tmp_path):
    db = tmp_path / 'paper.db'
    l = PaperLedger(str(db))
    l.insert_trade({'signal_id':'1','ts':'t','symbol':'XAUUSD','direction':'BUY','entry':1,'sl':0.5,'tp1':2,'rr':2})
    assert l.count() == 1


def test_telegram_format_and_demo_executor():
    msg = format_signal_message({'direction':'BUY','symbol':'XAUUSD','setup_type':'CRT','entry':1,'sl':0.5,'tp1':2,'rr':2,'timestamp':'now'})
    assert 'Disclaimer' in msg
    ex = DemoExecutor(enabled=False)
    assert ex.place_order({'signal_id':'1'})['ok'] is False


def test_settings_safe_defaults():
    s = Settings()
    assert s.paper_mode is True
