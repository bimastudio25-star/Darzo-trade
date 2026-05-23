from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.strategy_2_human_trade_alignment import (
    HUMAN_TRADE_FIELDS,
    align_human_trades_to_bot_candidates,
    build_human_trade_alignment_pack,
    load_bot_candidates,
    write_human_trade_alignment_outputs,
)


def _bot_row(
    sample_id: str,
    *,
    symbol: str = "XAUUSD",
    direction: str = "LONG",
    decision_time: str = "2026-05-01T09:50:00+00:00",
    entry_price: float | str = 2400.0,
    descriptor: str = "FAST_REENTRY",
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "symbol": symbol,
        "h1_context_id": f"CTX_{sample_id}",
        "direction_candidate": direction,
        "layer_a_state": "VALID_LONG" if direction == "LONG" else "VALID_SHORT",
        "layer_a_valid": True,
        "layer_b_eligible": True,
        "layer_b_measurable": True,
        "layer_b_funnel_state": "MEASURABLE_REACTION_WINDOW",
        "entry_status_audit": "ENTRY_TRIGGERED_MAE_AND_RANGE_REENTRY",
        "decision_time": decision_time,
        "entry_price": entry_price,
        "reaction_descriptor": descriptor,
        "layer_b_candidate_label": "STRONG_REACTION_CANDIDATE",
        "pip_factor_used": 10,
    }


def _human_row(
    trade_id: str,
    *,
    symbol: str = "XAUUSD",
    direction: str = "LONG",
    open_time: str = "2026-05-01T10:00:00+00:00",
    entry_price: float | str = 2401.0,
    strategy_tag: str = "strategy_2_liquidity_expansion",
) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in HUMAN_TRADE_FIELDS}
    row.update(
        {
            "human_trade_id": trade_id,
            "source": "fixture",
            "symbol": symbol,
            "direction": direction,
            "open_time": open_time,
            "entry_price": entry_price,
            "strategy_tag_optional": strategy_tag,
            "notes": "test fixture only",
        }
    )
    return row


def _write_bot_source(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "layer_b_reaction_features_per_sample.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_human_trades(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "human_trades.csv"
    pd.DataFrame(rows, columns=HUMAN_TRADE_FIELDS).to_csv(path, index=False)
    return path


def test_template_is_generated_when_no_trade_file_exists(tmp_path: Path):
    bot_source = _write_bot_source(tmp_path, [_bot_row("BOT_001")])
    missing_human_file = tmp_path / "missing_human_trades.csv"
    result = build_human_trade_alignment_pack(bot_source, human_trades_path=missing_human_file, output_dir=tmp_path / "out")
    paths = write_human_trade_alignment_outputs(result, tmp_path / "out")
    template = pd.read_csv(paths["human_trades_template"])
    assert list(template.columns) == HUMAN_TRADE_FIELDS
    assert result.summary["status"] == "HUMAN_TRADES_NOT_PROVIDED_YET"
    assert result.summary["real_human_trades_provided"] is False


def test_no_fake_trades_are_treated_as_real_evidence(tmp_path: Path):
    bot_source = _write_bot_source(tmp_path, [_bot_row("BOT_001")])
    human_template = _write_human_trades(tmp_path, [])
    result = build_human_trade_alignment_pack(bot_source, human_trades_path=human_template, output_dir=tmp_path / "out")
    assert result.summary["real_human_trades_provided"] is False
    assert result.summary["no_fake_trades_used_as_evidence"] is True
    assert result.per_trade is None


def test_matching_requires_same_symbol_and_direction(tmp_path: Path):
    bot_source = _write_bot_source(
        tmp_path,
        [
            _bot_row("BOT_LONG", symbol="XAUUSD", direction="LONG"),
            _bot_row("BOT_SHORT", symbol="XAUUSD", direction="SHORT"),
            _bot_row("BOT_EUR", symbol="EURUSD", direction="LONG"),
        ],
    )
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", symbol="XAUUSD", direction="LONG")])
    per_trade, _ = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_trade.iloc[0]["matched_bot_sample_ids"] == "BOT_LONG"


def test_time_tolerance_works(tmp_path: Path):
    bot_source = _write_bot_source(
        tmp_path,
        [
            _bot_row("BOT_IN_WINDOW", decision_time="2026-05-01T09:10:00+00:00"),
            _bot_row("BOT_TOO_EARLY", decision_time="2026-05-01T08:59:00+00:00"),
            _bot_row("BOT_TOO_LATE", decision_time="2026-05-01T10:16:00+00:00"),
        ],
    )
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", open_time="2026-05-01T10:00:00+00:00")])
    per_trade, _ = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_trade.iloc[0]["matched_bot_sample_ids"] == "BOT_IN_WINDOW"
    assert per_trade.iloc[0]["alignment_classification"] == "BOT_MATCHED_BEFORE_ENTRY"


def test_price_tolerance_works(tmp_path: Path):
    bot_source = _write_bot_source(
        tmp_path,
        [
            _bot_row("BOT_PRICE_MATCH", entry_price=2401.5),
            _bot_row("BOT_PRICE_FAR", entry_price=2410.0),
        ],
    )
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", entry_price=2400.0)])
    per_trade, _ = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_trade.iloc[0]["matched_bot_sample_ids"] == "BOT_PRICE_MATCH"


def test_ambiguous_multiple_matches_are_flagged(tmp_path: Path):
    bot_source = _write_bot_source(
        tmp_path,
        [
            _bot_row("BOT_A", decision_time="2026-05-01T09:58:00+00:00", entry_price=2400.5),
            _bot_row("BOT_B", decision_time="2026-05-01T09:59:00+00:00", entry_price=2401.0),
        ],
    )
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", open_time="2026-05-01T10:00:00+00:00", entry_price=2401.0)])
    per_trade, per_bot = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_trade.iloc[0]["alignment_classification"] == "AMBIGUOUS_MULTIPLE_MATCHES"
    assert set(per_bot["bot_candidate_alignment_status"]) == {"AMBIGUOUS_MATCH"}


def test_unmatched_human_trade_becomes_bot_missed(tmp_path: Path):
    bot_source = _write_bot_source(tmp_path, [_bot_row("BOT_001", decision_time="2026-05-01T08:00:00+00:00")])
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", open_time="2026-05-01T10:00:00+00:00")])
    per_trade, _ = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_trade.iloc[0]["alignment_classification"] == "BOT_MISSED"


def test_unmatched_bot_candidates_are_not_called_false_positives(tmp_path: Path):
    bot_source = _write_bot_source(tmp_path, [_bot_row("BOT_UNMATCHED")])
    bots = load_bot_candidates(bot_source)
    trades = pd.DataFrame([_human_row("H1", direction="SHORT")])
    _, per_bot = align_human_trades_to_bot_candidates(trades, bots, config=_config())
    assert per_bot.iloc[0]["bot_candidate_alignment_status"] == "UNMATCHED_BOT_CANDIDATE"
    assert bool(per_bot.iloc[0]["unmatched_bot_candidates_are_false_positives"]) is False
    assert "false" not in per_bot.iloc[0]["bot_candidate_alignment_status"].lower()


def test_no_performance_claims_are_generated(tmp_path: Path):
    bot_source = _write_bot_source(tmp_path, [_bot_row("BOT_001")])
    human_trades = _write_human_trades(tmp_path, [_human_row("H1")])
    result = build_human_trade_alignment_pack(bot_source, human_trades_path=human_trades, output_dir=tmp_path / "out")
    text = json_text(result.summary) + result.readme_markdown.lower()
    assert "profit_factor" not in text
    assert "win_rate" not in text
    assert "validated edge" not in text
    assert result.summary["safety"]["performance_claim_made"] is False
    assert result.summary["safety"]["wr_pf_r_claim_made"] is False


def test_no_strategy_3_or_adelin_files_are_touched_by_code():
    paths = [
        Path("dazro_trade/analytics/strategy_2_human_trade_alignment.py"),
        Path("scripts/analyze_strategy_2_human_trade_alignment.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    forbidden_strategy = "strategy" + "_3"
    forbidden_adelin = "dazro_trade." + "adelin"
    assert forbidden_strategy not in combined
    assert forbidden_adelin not in combined
    assert "order_send(" not in combined
    assert "to_csv(\"data" not in combined
    assert "write_text(\"data" not in combined
    assert "grid_search" not in combined


def test_import_safe_script():
    module = importlib.import_module("scripts.analyze_strategy_2_human_trade_alignment")
    assert hasattr(module, "main")
    assert hasattr(module, "run")


def _config() -> dict[str, object]:
    return {
        "symbol": "XAUUSD",
        "max_signal_lead_minutes": 60,
        "max_signal_lag_minutes": 15,
        "near_entry_minutes": 5,
        "max_entry_price_distance_usd": 3.0,
        "tolerances_are_diagnostic_assumptions": True,
        "optimize_tolerances": False,
        "unmatched_bot_candidates_are_not_false_positives": True,
    }


def json_text(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True, default=str).lower()
