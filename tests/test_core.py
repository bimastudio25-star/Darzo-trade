import pandas as pd
from analysis import detect_crt, find_reverse_levels
from reverse_manager import ReverseManager


def test_detect_crt_returns_none_on_short_df():
    df = pd.DataFrame([{"o":1,"h":2,"l":0.5,"c":1.5} for _ in range(3)])
    assert detect_crt(df) is None


def test_find_reverse_levels_buy_basic():
    df = pd.DataFrame([
        {"h": 10.0, "l": 9.0},
        {"h": 10.1, "l": 9.1},
        {"h": 10.0, "l": 9.2},
        {"h": 10.2, "l": 9.3},
    ])
    out = find_reverse_levels(
        "BUY", 9.5,
        [{"type":"bearish_ob","top":10.3,"bot":9.7}],
        [{"type":"bearish_fvg","top":10.0,"bot":9.8}],
        [],
        df, df, 0.1,
        {"range_low":9.1},
        {"bot":9.2},
    )
    assert out["reverse_level"] is not None
    assert out["invalidation_level"] == 9.1


def test_reverse_manager_add_and_check():
    rm = ReverseManager()
    rm.add_trade({"direction":"BUY","entry":100,"sl":90,"tp1":110,"tp2":120,"bias_h1":"bullish"},{"reverse_level":115,"invalidation_level":95,"reverse_reason":"x"})
    alerts = rm.check_all_trades(94, "bullish")
    assert any(a[0] == "invalidated" for a in alerts)
