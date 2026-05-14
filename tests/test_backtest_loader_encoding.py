from __future__ import annotations

from pathlib import Path

import pytest

from dazro_trade.backtest.data_loader import _load_single_csv, load_csv_timeframes


def _mt5_unicode_text_bytes(rows: int = 5, sep: str = "\t") -> bytes:
    header = f"<DATE>{sep}<TIME>{sep}<OPEN>{sep}<HIGH>{sep}<LOW>{sep}<CLOSE>{sep}<TICKVOL>{sep}<VOL>{sep}<SPREAD>\n"
    body = ""
    for i in range(rows):
        body += f"2025.05.{i+1:02d}{sep}00:00:00{sep}4700.00{sep}4702.50{sep}4698.50{sep}4701.00{sep}1234{sep}0{sep}10\n"
    content = header + body
    return b"\xff\xfe" + content.encode("utf-16-le")


def test_loads_utf16_le_with_bom_and_tab_separator(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_unicode_text_bytes(rows=5))
    df = _load_single_csv(path)
    assert {"time", "open", "high", "low", "close", "tick_volume", "spread"}.issubset(df.columns)
    assert len(df.columns) == len(set(df.columns))
    assert len(df) == 5
    assert df["time"].iloc[0].isoformat().startswith("2025-05-01")
    assert df.attrs["source_encoding"] == "utf-16-le"


def test_loads_utf8_sig_with_comma(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "time,open,high,low,close\n2025-05-01T00:00:00,4700,4702,4698,4701\n2025-05-01T01:00:00,4701,4703,4699,4702\n"
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    df = _load_single_csv(path)
    assert len(df) == 2
    assert df["close"].iloc[1] == 4702
    assert df.attrs["source_encoding"] == "utf-8-sig"


def test_loads_cp1252_with_semicolon(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "time;open;high;low;close\n2025-05-01T00:00:00;4700;4702;4698;4701\n"
    path.write_bytes(content.encode("cp1252"))
    df = _load_single_csv(path)
    assert len(df) == 1
    assert df.attrs["source_separator"] == ";"


def test_loads_plain_utf8_comma(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "time,open,high,low,close,tick_volume\n2025-05-01T00:00:00,4700,4702,4698,4701,123\n"
    path.write_bytes(content.encode("utf-8"))
    df = _load_single_csv(path)
    assert len(df) == 1
    assert int(df["tick_volume"].iloc[0]) == 123


def test_load_csv_timeframes_handles_mt5_format(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_unicode_text_bytes(rows=8))
    loaded = load_csv_timeframes("XAUUSD", ["H1"], data_dir=str(tmp_path))
    assert "H1" in loaded
    assert len(loaded["H1"]) == 8
    assert set(loaded["H1"].columns) >= {"time", "open", "high", "low", "close"}


def test_unreadable_file_raises(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x01\x02\x03this is not a csv at all")
    with pytest.raises(ValueError):
        _load_single_csv(path)


def test_tickvol_and_vol_dont_create_duplicate_columns(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_unicode_text_bytes(rows=3))
    df = _load_single_csv(path)
    assert list(df.columns).count("tick_volume") == 1


def _mt5_headerless_utf16(rows: int = 5, ncols: int = 7) -> bytes:
    """MT5 export without header row, UTF-16 LE BOM, comma separator, MT5 date format."""
    lines = []
    for i in range(rows):
        if ncols == 5:
            lines.append(f"2025.03.{i+1:02d} 01:00,2857.88,2876.88,2855.10,2870.81")
        elif ncols == 6:
            lines.append(f"2025.03.{i+1:02d} 01:00,2857.88,2876.88,2855.10,2870.81,3989")
        elif ncols == 7:
            lines.append(f"2025.03.{i+1:02d} 01:00,2857.88,2876.88,2855.10,2870.81,3989,0")
        elif ncols == 8:
            lines.append(f"2025.03.{i+1:02d} 01:00,2857.88,2876.88,2855.10,2870.81,3989,0,2")
    content = "\n".join(lines) + "\n"
    return b"\xff\xfe" + content.encode("utf-16-le")


def test_loads_headerless_mt5_7col(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_headerless_utf16(rows=8, ncols=7))
    df = _load_single_csv(path)
    assert list(df.columns) == ["time", "open", "high", "low", "close", "tick_volume", "spread"]
    assert len(df) == 8
    assert df["time"].iloc[0].isoformat().startswith("2025-03-01")
    assert float(df["close"].iloc[0]) == 2870.81


def test_loads_headerless_mt5_5col(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_headerless_utf16(rows=4, ncols=5))
    df = _load_single_csv(path)
    assert list(df.columns) == ["time", "open", "high", "low", "close"]
    assert len(df) == 4


def test_loads_headerless_mt5_8col(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_mt5_headerless_utf16(rows=3, ncols=8))
    df = _load_single_csv(path)
    assert "real_volume" in df.columns
    assert "tick_volume" in df.columns
    assert "spread" in df.columns
    assert len(df) == 3


def test_headerless_format_with_tab_separator(tmp_path):
    path = tmp_path / "XAUUSD" / "H1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"2025.03.{i+1:02d} 01:00\t2857.88\t2876.88\t2855.10\t2870.81\t3989\t0" for i in range(5)]
    content = "\n".join(lines) + "\n"
    path.write_bytes(b"\xff\xfe" + content.encode("utf-16-le"))
    df = _load_single_csv(path)
    assert list(df.columns)[:5] == ["time", "open", "high", "low", "close"]
    assert len(df) == 5
