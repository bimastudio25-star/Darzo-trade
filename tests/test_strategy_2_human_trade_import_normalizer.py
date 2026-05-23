from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

from dazro_trade.analytics.strategy_2_human_trade_alignment import HUMAN_TRADE_FIELDS
from dazro_trade.analytics.strategy_2_human_trade_import_normalizer import (
    NORMALIZED_COLUMNS,
    build_column_mapping,
    import_strategy_2_human_trades,
    parse_number,
    write_import_outputs,
)


def _canonical_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "human_trade_id": "RAW_ID_IGNORED",
        "source": "mt5",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "open_time": "2026-05-01 10:00:00",
        "close_time": "2026-05-01 10:30:00",
        "entry_price": "2345.67",
        "exit_price": "2348.00",
        "stop_loss": "2335.00",
        "take_profit": "2360.00",
        "volume": "0.10",
        "result_optional": "12.5",
        "screenshot_path_optional": "",
        "notes": "real export row",
        "strategy_tag_optional": "",
        "Ticket": "12345",
    }
    row.update(updates)
    return row


def _write_csv(path: Path, rows: list[dict[str, object]], *, sep: str = ",", encoding: str = "utf-8-sig") -> Path:
    pd.DataFrame(rows).to_csv(path, index=False, sep=sep, encoding=encoding)
    return path


def test_csv_import_works_with_canonical_template_columns(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row()])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert len(result.normalized) == 1
    row = result.normalized.iloc[0]
    assert row["symbol"] == "XAUUSD"
    assert row["direction"] == "LONG"
    assert row["entry_price"] == "2345.67"


def test_semicolon_csv_import_works(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(direction="sell")], sep=";")
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.summary["detected_delimiters"] == [";"]
    assert result.normalized.iloc[0]["direction"] == "SHORT"


def test_tsv_import_works(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.tsv", [_canonical_row()], sep="\t")
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.summary["detected_delimiters"] == ["tab"]
    assert len(result.normalized) == 1


def test_direction_normalization_works(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(direction="short")])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.normalized.iloc[0]["direction"] == "SHORT"


def test_xauusd_symbol_normalization_for_configured_variants(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(symbol="XAUUSDm")])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.normalized.iloc[0]["symbol"] == "XAUUSD"


def test_missing_required_fields_fail_loudly(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(open_time="")])
    with pytest.raises(ValueError, match="no valid human trades normalized"):
        import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")


def test_missing_optional_fields_produce_warnings(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(close_time="", exit_price="", stop_loss="", take_profit="", volume="", notes="")])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    warnings = result.normalized.iloc[0]["import_warning_flags"]
    assert "MISSING_CLOSE_TIME" in warnings
    assert "MISSING_STOP_LOSS" in warnings
    assert result.errors.empty


def test_no_fake_trades_are_created_when_input_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        import_strategy_2_human_trades(input_path=tmp_path / "missing.csv", output_dir=tmp_path / "out")


def test_duplicate_human_trade_id_is_detected_and_exact_duplicate_dropped(tmp_path: Path):
    row = _canonical_row(Ticket="DUP1")
    source = _write_csv(tmp_path / "trades.csv", [row, row])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert len(result.normalized) == 1
    assert result.summary["duplicates_detected"] == 1
    assert result.summary["duplicates_dropped_exact"] == 1


def test_unknown_direction_fails(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(direction="hold")])
    with pytest.raises(ValueError, match="no valid human trades normalized"):
        import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")


def test_normalized_output_matches_human_trades_template_columns(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row()])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.normalized.columns.tolist()[: len(HUMAN_TRADE_FIELDS)] == HUMAN_TRADE_FIELDS
    assert result.normalized.columns.tolist() == NORMALIZED_COLUMNS


def test_no_strategy_3_or_adelin_files_are_touched_by_code():
    paths = [
        Path("dazro_trade/analytics/strategy_2_human_trade_import_normalizer.py"),
        Path("scripts/import_strategy_2_human_trades.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "order_send(" not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined


def test_no_performance_claims_are_generated(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row()])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    text = str(result.summary).lower() + result.readme_markdown.lower()
    assert "profit_factor" not in text
    assert "win_rate" not in text
    assert result.summary["performance_claim_made"] is False
    assert result.summary["safety"]["wr_pf_r_claim_made"] is False


def test_utf16_le_bom_csv_import_works(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row()], encoding="utf-16")
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert len(result.normalized) == 1
    assert "utf-16" in result.summary["detected_encodings"]


def test_european_decimal_comma_prices_parse_correctly(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(entry_price="2345,67", exit_price="2348,10", Ticket="C1")], sep=";")
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out", decimal_separator="auto")
    assert result.normalized.iloc[0]["entry_price"] == "2345.67"
    assert result.normalized.iloc[0]["exit_price"] == "2348.1"


def test_thousands_separator_plus_decimal_comma_parses_correctly():
    value, error = parse_number("2.345,67", decimal_separator="auto")
    assert error == ""
    assert value == 2345.67


def test_deterministic_human_trade_id_is_stable_across_repeated_imports(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(Ticket="")])
    first = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out1")
    second = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out2")
    assert first.normalized.iloc[0]["human_trade_id"] == second.normalized.iloc[0]["human_trade_id"]


def test_mt5_deal_level_grouped_by_position_id_produces_one_normalized_trade(tmp_path: Path):
    rows = [
        {"Deal": "1", "Order": "10", "Position ID": "500", "Entry": "IN", "Time": "2026-05-01 10:00:00", "Type": "buy", "Symbol": "XAUUSD", "Price": "2345.00", "Volume": "0.10", "Profit": "0"},
        {"Deal": "2", "Order": "10", "Position ID": "500", "Entry": "OUT", "Time": "2026-05-01 10:20:00", "Type": "sell", "Symbol": "XAUUSD", "Price": "2348.00", "Volume": "0.10", "Profit": "30"},
    ]
    source = _write_csv(tmp_path / "deals.csv", rows)
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    assert result.summary["detected_export_granularities"] == ["DEAL_LEVEL_GROUPED"]
    assert len(result.normalized) == 1
    assert result.normalized.iloc[0]["source_position_id_optional"] == "500"
    assert result.normalized.iloc[0]["direction"] == "LONG"


def test_ambiguous_partial_close_deal_group_is_flagged_not_fabricated(tmp_path: Path):
    rows = [
        {"Deal": "1", "Position ID": "500", "Entry": "IN", "Time": "2026-05-01 10:00:00", "Type": "buy", "Symbol": "XAUUSD", "Price": "2345.00", "Volume": "0.20"},
        {"Deal": "2", "Position ID": "500", "Entry": "OUT", "Time": "2026-05-01 10:10:00", "Type": "sell", "Symbol": "XAUUSD", "Price": "2346.00", "Volume": "0.10"},
        {"Deal": "3", "Position ID": "500", "Entry": "OUT", "Time": "2026-05-01 10:20:00", "Type": "sell", "Symbol": "XAUUSD", "Price": "2348.00", "Volume": "0.10"},
    ]
    source = _write_csv(tmp_path / "deals.csv", rows)
    with pytest.raises(ValueError, match="no valid human trades normalized"):
        import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")


def test_input_dir_processes_multiple_files_deterministically(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_csv(raw_dir / "b.csv", [_canonical_row(Ticket="B")])
    _write_csv(raw_dir / "a.csv", [_canonical_row(Ticket="A")])
    result = import_strategy_2_human_trades(input_dir=raw_dir, output_dir=tmp_path / "out")
    assert result.summary["files_processed"] == [str(raw_dir / "a.csv"), str(raw_dir / "b.csv")]
    assert len(result.normalized) == 2


def test_conflicting_duplicate_human_trade_id_fails_loudly(tmp_path: Path):
    source = _write_csv(
        tmp_path / "trades.csv",
        [
            _canonical_row(Ticket="DUP1", entry_price="2345.00"),
            _canonical_row(Ticket="DUP1", entry_price="2346.00"),
        ],
    )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")


def test_overwrite_false_fails_if_outputs_already_exist(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row()])
    out = tmp_path / "out"
    out.mkdir()
    (out / "human_trades_filled_normalized.csv").write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        import_strategy_2_human_trades(input_path=source, output_dir=out, overwrite=False)


def test_column_mapping_audit_file_is_generated(tmp_path: Path):
    source = _write_csv(tmp_path / "trades.csv", [_canonical_row(ExtraColumn="ignored")])
    result = import_strategy_2_human_trades(input_path=source, output_dir=tmp_path / "out")
    paths = write_import_outputs(result, tmp_path / "out")
    mapping = pd.read_csv(paths["column_mapping_csv"])
    assert Path(paths["column_mapping_csv"]).exists()
    assert "ExtraColumn" in set(mapping["original_column_name"])


def test_unmapped_source_columns_are_reported():
    mapping = build_column_mapping(["Symbol", "Mystery Column"])
    row = mapping[mapping["original_column_name"].eq("Mystery Column")].iloc[0]
    assert row["match_method"] == "unmapped"
    assert row["confidence"] == "low"


def test_import_safe_script():
    module = importlib.import_module("scripts.import_strategy_2_human_trades")
    assert hasattr(module, "main")
    assert hasattr(module, "run")
