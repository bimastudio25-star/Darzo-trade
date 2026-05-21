from __future__ import annotations

import ast
import csv
import importlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dazro_trade.analytics.adelin_v2_objective_outcome_replay import (
    FAST_SL_20,
    GOOD_FAST_REACTION,
    GOOD_SLOW_REACTION,
    NO_REACTION,
    ENTRY_DIRECTION_CONFLICT,
    ROUND_LEVEL,
    ROUND_LEVEL_TOUCH_ENTRY,
    SWEEP_EXTREME,
    SWEPT_LIQUIDITY_LEVEL,
    UNKNOWN_DIRECTION,
    UNKNOWN_ENTRY_LEVEL,
    UNKNOWN_INSUFFICIENT_FORWARD_DATA,
    DirectionInference,
    EntryHypothesis,
    ObjectiveReplayConfig,
    PRE_REGISTERED_VERDICT_CONTINUE,
    PRE_REGISTERED_VERDICT_INCONCLUSIVE,
    PRE_REGISTERED_VERDICT_STOP,
    ReplayInputSample,
    apply_pre_registered_decision,
    build_source_metrics_with_confidence,
    build_entry_hypothesis,
    detect_pre_anchor_sweep_control,
    effect_size_ci95,
    generate_control_samples,
    infer_reversal_direction,
    load_pre_registered_criteria,
    normal_proportion_ci95,
    replay_forward_path,
    resolve_pip_size,
    run_objective_replay,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _frame(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def _write_frame(path: Path, start: datetime, rows: int, minutes: int, *, base: float = 4900.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
        price = base
        for i in range(rows):
            ts = start + timedelta(minutes=minutes * i)
            close = price + (0.1 if i % 2 == 0 else -0.1)
            writer.writerow(
                [
                    ts.strftime("%Y-%m-%d %H:%M:%S"),
                    price,
                    max(price, close) + 0.2,
                    min(price, close) - 0.2,
                    close,
                    100,
                    0,
                ]
            )
            price = close


def _make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    _write_frame(data_dir / "XAUUSD" / "M1.csv", start, 12 * 60, 1)
    _write_frame(data_dir / "XAUUSD" / "M5.csv", start, 12 * 12, 5)
    _write_frame(data_dir / "XAUUSD" / "M15.csv", start, 12 * 4, 15)
    _write_frame(data_dir / "XAUUSD" / "H1.csv", start, 16, 60)
    return data_dir


def _make_visual_pack(tmp_path: Path, anchors: list[datetime]) -> Path:
    pack_dir = tmp_path / "visual_pack"
    (pack_dir / "examples").mkdir(parents=True, exist_ok=True)
    labels_path = pack_dir / "manual_labels_template.csv"
    fieldnames = [
        "sample_id",
        "source_mode",
        "symbol",
        "direction_guess",
        "window_start",
        "window_end",
        "anchor_timestamp",
        "anchor_timeframe",
        "chart_path",
        "html_path",
        "execution_data_status",
        "m1_candles_count",
        "m5_candles_count",
        "m15_candles_count",
        "execution_window_start",
        "execution_window_end",
    ]
    with labels_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, anchor in enumerate(anchors, start=1):
            sample_id = f"sample_{idx:03d}"
            html_path = f"examples/{sample_id}.html"
            (pack_dir / html_path).write_text(
                "<table>"
                "<tr><th>number_theory_level</th><td>4900.0</td></tr>"
                "<tr><th>candidate_reason_codes</th><td>TEST_ROUND_LEVEL</td></tr>"
                "</table>",
                encoding="utf-8",
            )
            writer.writerow(
                {
                    "sample_id": sample_id,
                    "source_mode": "CANDIDATE_WINDOW_MODE",
                    "symbol": "XAUUSD",
                    "direction_guess": "",
                    "window_start": (anchor - timedelta(hours=1)).isoformat(),
                    "window_end": (anchor + timedelta(hours=4)).isoformat(),
                    "anchor_timestamp": anchor.isoformat(),
                    "anchor_timeframe": "M15",
                    "chart_path": "",
                    "html_path": html_path,
                    "execution_data_status": "REVIEWABLE_M1_M5",
                    "m1_candles_count": "240",
                    "m5_candles_count": "48",
                    "m15_candles_count": "16",
                    "execution_window_start": anchor.isoformat(),
                    "execution_window_end": (anchor + timedelta(hours=4)).isoformat(),
                }
            )
    return pack_dir


def _path_frame(anchor: datetime, *, direction: str = "LONG", fast_100: bool = True, sl_first: bool = False) -> pd.DataFrame:
    rows: list[tuple[datetime, float, float, float, float]] = []
    entry = 4900.0
    for i in range(0, 66):
        ts = anchor + timedelta(minutes=i)
        open_ = entry
        high = entry + 0.3
        low = entry - 0.3
        close = entry
        if sl_first and i == 1:
            low = entry - 2.2
            close = entry - 1.5
        if direction == "LONG":
            if fast_100 and i == 10:
                high = entry + 10.0
                close = entry + 9.0
            elif not fast_100 and i == 35:
                high = entry + 10.0
                close = entry + 9.0
        else:
            high = entry + 0.3
            low = entry - 0.3
            if fast_100 and i == 10:
                low = entry - 10.0
                close = entry - 9.0
            elif not fast_100 and i == 35:
                low = entry - 10.0
                close = entry - 9.0
        rows.append((ts, open_, high, low, close))
    return _frame(rows)


def _sample(anchor: datetime, sample_id: str = "sample_001", row_type: str = "CANDIDATE") -> ReplayInputSample:
    return ReplayInputSample(
        row_type=row_type,
        sample_id=sample_id,
        symbol="XAUUSD",
        anchor_timestamp=anchor,
        source_mode="CANDIDATE_WINDOW_MODE" if row_type == "CANDIDATE" else "MATCHED_RANDOM_CONTROL",
        metadata={"number_theory_level": "4900.0"},
    )


def _entry() -> EntryHypothesis:
    return EntryHypothesis(
        ROUND_LEVEL_TOUCH_ENTRY,
        4900.0,
        ROUND_LEVEL,
        True,
        entry_level_confidence="HIGH",
        entry_level_reason_codes=("TEST_NUMBER_THEORY_LEVEL",),
    )


def _direction(value: str) -> DirectionInference:
    return DirectionInference(
        value,
        "M5",
        "UPWARD_SWEEP" if value == "SHORT" else "DOWNWARD_SWEEP",
        4901.0,
        None,
        "HIGH",
        ("TEST",),
        4903.0 if value == "SHORT" else 4897.0,
    )


def _decision_rows(
    *,
    source: str,
    candidate_n: int,
    control_n: int,
    candidate_fast: int = 0,
    control_fast: int = 0,
    candidate_sl20: int = 0,
    control_sl20: int = 0,
    candidate_runner: int = 0,
    control_runner: int = 0,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(candidate_n):
        label = FAST_SL_20 if i < candidate_sl20 else ("RUNNER_CANDIDATE" if i < candidate_runner else NO_REACTION)
        rows.append(
            {
                "row_type": "CANDIDATE",
                "sample_id": f"c_{source}_{i}",
                "entry_level_source": source,
                "entry_price": 4900.0,
                "fast_reaction_100pips_15m": i < candidate_fast,
                "automatic_outcome_label": label,
                "hit_500_pips": i < candidate_runner,
            }
        )
    for i in range(control_n):
        label = FAST_SL_20 if i < control_sl20 else ("RUNNER_CANDIDATE" if i < control_runner else NO_REACTION)
        rows.append(
            {
                "row_type": "CONTROL",
                "sample_id": f"k_{source}_{i}",
                "entry_level_source": source,
                "entry_price": 4900.0,
                "fast_reaction_100pips_15m": i < control_fast,
                "automatic_outcome_label": label,
                "hit_500_pips": i < control_runner,
            }
        )
    return rows


def test_module_import_is_safe():
    module = importlib.import_module("dazro_trade.analytics.adelin_v2_objective_outcome_replay")
    assert hasattr(module, "run_objective_replay")


def test_script_import_is_safe():
    module = importlib.import_module("scripts.analyze_adelin_v2_objective_outcome_replay")
    args = module.parse_args(["--symbol", "XAUUSD", "--forward-hours", "4"])
    assert args.symbol == "XAUUSD"
    assert args.forward_hours == 4


def test_no_live_telegram_broker_or_order_imports_are_used():
    paths = [
        REPO_ROOT / "dazro_trade" / "analytics" / "adelin_v2_objective_outcome_replay.py",
        REPO_ROOT / "scripts" / "analyze_adelin_v2_objective_outcome_replay.py",
    ]
    blocked_import_terms = {"telegram", "mt5", "execution", "broker", "order"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module.lower())
        assert not any(any(term in name for term in blocked_import_terms) for name in imported)
        source = path.read_text(encoding="utf-8")
        assert "order_send" not in source
        assert "send_message(" not in source


def test_pip_size_resolver_uses_project_symbol_registry():
    resolution = resolve_pip_size("XAUUSD")
    assert resolution.pip_size == 0.1
    assert resolution.source == "core.symbols.get_symbol_spec"


def test_pre_registered_criteria_can_be_loaded(tmp_path: Path):
    criteria = tmp_path / "decision_criteria.md"
    criteria.write_text("locked criteria", encoding="utf-8")
    loaded = load_pre_registered_criteria(tmp_path)
    assert loaded["loaded"] is True
    assert loaded["verbatim"] == "locked criteria"
    assert loaded["source_path"].endswith("decision_criteria.md")


def test_ci95_helpers_and_effect_excludes_zero():
    lower, upper = normal_proportion_ci95(50, 100)
    assert 0 <= lower <= upper <= 1
    effect_lower, effect_upper = effect_size_ci95(0.8, 100, 0.5, 100)
    assert effect_lower > 0
    assert effect_upper > effect_lower
    noisy_lower, noisy_upper = effect_size_ci95(0.17, 100, 0.10, 100)
    assert noisy_lower < 0 < noisy_upper


def test_pre_registered_verdict_continue_for_fast_reaction_plus_7pp():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=100, control_n=100, candidate_fast=20, control_fast=10)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_CONTINUE
    assert decision["decision_metric"] == "fast_reaction"


def test_pre_registered_verdict_continue_for_runner_plus_5pp():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=100, control_n=100, candidate_runner=10, control_runner=4)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_CONTINUE
    assert decision["decision_metric"] == "runner"


def test_pre_registered_verdict_continue_for_fast_sl20_minus_10pp():
    rows = _decision_rows(source=SWEEP_EXTREME, candidate_n=100, control_n=100, candidate_sl20=10, control_sl20=25)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_CONTINUE
    assert decision["decision_metric"] == "fast_sl20"


def test_ci95_metadata_does_not_alter_pre_registered_verdict():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=100, control_n=100, candidate_fast=17, control_fast=10)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_CONTINUE
    assert decision["decision_effect_size_excludes_zero"] is False
    assert "robustness is weak" in decision["decision_robustness_note"]


def test_pre_registered_verdict_stop_when_all_useful_sources_flat_or_worse():
    rows = []
    rows += _decision_rows(source=ROUND_LEVEL, candidate_n=60, control_n=100, candidate_fast=6, control_fast=10, candidate_sl20=21, control_sl20=35)
    rows += _decision_rows(source=SWEEP_EXTREME, candidate_n=90, control_n=100, candidate_fast=9, control_fast=10, candidate_sl20=32, control_sl20=35)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_STOP


def test_pre_registered_verdict_inconclusive_for_mixed_non_threshold_case():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=100, control_n=100, candidate_fast=14, control_fast=10, candidate_sl20=20, control_sl20=25)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["pre_registered_verdict"] == PRE_REGISTERED_VERDICT_INCONCLUSIVE


def test_ineligible_sources_under_min_n_are_excluded():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=49, control_n=100, candidate_fast=20, control_fast=1)
    decision = apply_pre_registered_decision(build_source_metrics_with_confidence(rows))
    assert decision["eligible_sources"] == []
    assert "ROUND_LEVEL" in decision["ineligible_sources"]


def test_summary_metrics_with_ci95_include_expected_fields():
    rows = _decision_rows(source=ROUND_LEVEL, candidate_n=100, control_n=100, candidate_fast=15, control_fast=10)
    metrics = build_source_metrics_with_confidence(rows)
    assert "candidate_fast_reaction_ci95_lower" in metrics[ROUND_LEVEL]
    assert "fast_reaction_effect_size_ci95_upper" in metrics[ROUND_LEVEL]
    assert metrics[ROUND_LEVEL]["fast_reaction_effect_size_excludes_zero"] is False


def test_round_level_entry_source_works():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    sample = ReplayInputSample(
        row_type="CANDIDATE",
        sample_id="round",
        symbol="XAUUSD",
        anchor_timestamp=anchor,
        source_mode="CANDIDATE_WINDOW_MODE",
        metadata={"number_theory_level": "4900.0"},
    )
    entry = build_entry_hypothesis(sample, {"M1": _path_frame(anchor)}, _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert entry.entry_price == 4900.0
    assert entry.entry_level_source == ROUND_LEVEL
    assert entry.entry_level_confidence == "HIGH"
    assert "EXPLICIT_ROUND_LEVEL_METADATA" in entry.entry_level_reason_codes


def test_visual_pack_entry_metadata_source_is_preserved():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    frames = {"M1": _frame([(anchor, 4914.0, 4914.2, 4913.8, 4914.0)])}
    sample = ReplayInputSample(
        "CANDIDATE",
        "explicit_sweep",
        "XAUUSD",
        anchor,
        "CANDIDATE_WINDOW_MODE",
        metadata={
            "entry_level_source": SWEEP_EXTREME,
            "entry_level_price": "4913.5",
            "entry_level_confidence": "LOW",
        },
    )
    entry = build_entry_hypothesis(sample, frames, _direction("SHORT"), symbol="XAUUSD", pip_size=0.1)
    assert entry.entry_price == 4913.5
    assert entry.entry_level_source == SWEEP_EXTREME
    assert "EXPLICIT_ENTRY_LEVEL_METADATA_FROM_VISUAL_PACK" in entry.entry_level_reason_codes


def test_sweep_extreme_entry_source_works_when_round_level_missing():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    frames = {"M1": _frame([(anchor, 4914.0, 4914.2, 4913.8, 4914.0)])}
    direction = DirectionInference(
        "SHORT",
        "M5",
        "UPWARD_SWEEP",
        4913.0,
        anchor,
        "HIGH",
        ("RECENT_LOCAL_HIGH_TAKEN_AND_REJECTED_OR_STALLED",),
        4915.4,
    )
    sample = ReplayInputSample("CANDIDATE", "sweep", "XAUUSD", anchor, "CANDIDATE_WINDOW_MODE", metadata={})
    entry = build_entry_hypothesis(sample, frames, direction, symbol="XAUUSD", pip_size=0.1)
    assert entry.entry_price == 4915.4
    assert entry.entry_level_source == SWEEP_EXTREME
    assert entry.entry_level_confidence == "MEDIUM"
    assert "DIRECTION_INFERRED_SWEEP_EXTREME_HEURISTIC" in entry.entry_level_reason_codes


def test_unknown_entry_remains_unknown_without_defensible_level():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    frames = {"M1": _frame([(anchor, 4914.0, 4914.2, 4913.8, 4914.0)])}
    direction = DirectionInference(UNKNOWN_DIRECTION, None, None, None, None, "UNKNOWN", ("NO_CLEAR_SWEEP",))
    sample = ReplayInputSample("CANDIDATE", "unknown", "XAUUSD", anchor, "CANDIDATE_WINDOW_MODE", metadata={})
    entry = build_entry_hypothesis(sample, frames, direction, symbol="XAUUSD", pip_size=0.1)
    assert entry.entry_price is None
    assert entry.entry_level_source == "UNKNOWN"
    assert entry.entry_level_confidence == "UNKNOWN"
    assert "DIRECTION_REQUIRED_FOR_SWEEP_ENTRY" in entry.entry_level_reason_codes


def test_entry_direction_conflict_is_detected():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    frames = {"M1": _frame([(anchor, 4914.0, 4914.2, 4913.8, 4914.0)])}
    sample = ReplayInputSample(
        row_type="CANDIDATE",
        sample_id="conflict",
        symbol="XAUUSD",
        anchor_timestamp=anchor,
        source_mode="CANDIDATE_WINDOW_MODE",
        metadata={"sweep_level": "4916.0"},
    )
    entry = build_entry_hypothesis(sample, frames, _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert entry.entry_price is None
    assert entry.limitation == ENTRY_DIRECTION_CONFLICT
    assert ENTRY_DIRECTION_CONFLICT in entry.entry_level_reason_codes


def test_direction_inference_upward_sweep_short():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    frame = _frame(
        [
            (anchor - timedelta(minutes=20), 4900, 4901, 4899, 4900),
            (anchor - timedelta(minutes=15), 4900, 4902, 4899, 4901),
            (anchor - timedelta(minutes=10), 4901, 4903, 4900, 4902),
            (anchor - timedelta(minutes=5), 4902, 4903.2, 4901, 4902.5),
            (anchor, 4902.5, 4904.5, 4901.8, 4902.0),
        ]
    )
    inference = infer_reversal_direction({"M5": frame}, anchor, pip_size=0.1)
    assert inference.direction_guess == "SHORT"
    assert inference.sweep_type == "UPWARD_SWEEP"


def test_direction_inference_downward_sweep_long():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    frame = _frame(
        [
            (anchor - timedelta(minutes=20), 4900, 4901, 4899, 4900),
            (anchor - timedelta(minutes=15), 4900, 4901, 4898, 4899),
            (anchor - timedelta(minutes=10), 4899, 4900, 4897, 4898),
            (anchor - timedelta(minutes=5), 4898, 4899, 4896.8, 4897.5),
            (anchor, 4897.5, 4898.8, 4895.5, 4897.2),
        ]
    )
    inference = infer_reversal_direction({"M5": frame}, anchor, pip_size=0.1)
    assert inference.direction_guess == "LONG"
    assert inference.sweep_type == "DOWNWARD_SWEEP"


def test_direction_inference_unclear_unknown():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    frame = _frame(
        [
            (anchor - timedelta(minutes=20), 4900, 4901, 4899, 4900),
            (anchor - timedelta(minutes=15), 4900, 4901, 4899, 4900),
            (anchor - timedelta(minutes=10), 4900, 4901, 4899, 4900),
        ]
    )
    inference = infer_reversal_direction({"M5": frame}, anchor, pip_size=0.1)
    assert inference.direction_guess == UNKNOWN_DIRECTION


def test_replay_computes_mfe_mae_for_long():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    row = replay_forward_path(_sample(anchor), {"M1": _path_frame(anchor, direction="LONG")}, _entry(), _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert row["max_favorable_pips"] == 100.0
    assert row["max_adverse_pips"] == 3.0
    assert row["automatic_outcome_label"] == GOOD_FAST_REACTION
    assert row["entry_level_confidence"] == "HIGH"
    assert row["entry_level_is_heuristic"] is True


def test_replay_computes_mfe_mae_for_short():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    row = replay_forward_path(_sample(anchor), {"M1": _path_frame(anchor, direction="SHORT")}, _entry(), _direction("SHORT"), symbol="XAUUSD", pip_size=0.1)
    assert row["max_favorable_pips"] == 100.0
    assert row["max_adverse_pips"] == 3.0
    assert row["automatic_outcome_label"] == GOOD_FAST_REACTION


def test_sl_20_40_detection_and_fast_sl_label():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    frame = _path_frame(anchor, direction="LONG", sl_first=True)
    frame.loc[1, "low"] = 4895.5
    row = replay_forward_path(_sample(anchor), {"M1": frame}, _entry(), _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert row["sl_20_hit"] is True
    assert row["sl_40_hit"] is True
    assert row["automatic_outcome_label"] == FAST_SL_20


def test_good_slow_reaction_is_not_fast():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    row = replay_forward_path(
        _sample(anchor),
        {"M1": _path_frame(anchor, direction="LONG", fast_100=False)},
        _entry(),
        _direction("LONG"),
        symbol="XAUUSD",
        pip_size=0.1,
    )
    assert row["automatic_outcome_label"] == GOOD_SLOW_REACTION
    assert row["fast_reaction_100pips_15m"] is False


def test_unknown_entry_level_handled_safely():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    entry = EntryHypothesis(UNKNOWN_ENTRY_LEVEL, None, None, True, "NO_ROUND_LEVEL_WITHIN_THRESHOLD")
    row = replay_forward_path(_sample(anchor), {"M1": _path_frame(anchor)}, entry, _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert row["automatic_outcome_label"] == UNKNOWN_ENTRY_LEVEL
    assert "NO_ROUND_LEVEL_WITHIN_THRESHOLD" in row["limitations"]


def test_unknown_direction_handled_safely():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    direction = DirectionInference(UNKNOWN_DIRECTION, None, None, None, None, "UNKNOWN", ("NO_CLEAR_SWEEP",))
    row = replay_forward_path(_sample(anchor), {"M1": _path_frame(anchor)}, _entry(), direction, symbol="XAUUSD", pip_size=0.1)
    assert row["automatic_outcome_label"] == UNKNOWN_DIRECTION


def test_missing_forward_candles_returns_unknown_insufficient_forward_data():
    anchor = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    short_frame = _path_frame(anchor).head(10)
    row = replay_forward_path(_sample(anchor), {"M1": short_frame}, _entry(), _direction("LONG"), symbol="XAUUSD", pip_size=0.1)
    assert row["automatic_outcome_label"] == UNKNOWN_INSUFFICIENT_FORWARD_DATA


def test_sweep_extreme_control_uses_only_pre_anchor_and_infers_short():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    pre = _frame(
        [
            (anchor - timedelta(minutes=20), 4900.0, 4901.0, 4899.8, 4900.5),
            (anchor - timedelta(minutes=15), 4900.5, 4902.0, 4900.2, 4901.5),
            (anchor - timedelta(minutes=10), 4901.5, 4904.0, 4901.4, 4903.5),
            (anchor - timedelta(minutes=5), 4903.5, 4903.6, 4903.0, 4903.1),
            (anchor, 4903.1, 4915.0, 4902.0, 4910.0),
        ]
    )
    detected = detect_pre_anchor_sweep_control({"M5": pre}, anchor, pip_size=0.1)
    assert detected is not None
    direction, entry = detected
    assert direction.direction_guess == "SHORT"
    assert direction.sweep_timestamp == anchor - timedelta(minutes=10)
    assert entry.entry_level_source == SWEEP_EXTREME
    assert entry.entry_price == 4904.0
    assert "ANCHOR_CANDLE_EXCLUDED" in direction.direction_reason_codes


def test_sweep_extreme_control_downward_sweep_infers_long():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    pre = _frame(
        [
            (anchor - timedelta(minutes=20), 4900.0, 4901.0, 4899.0, 4900.0),
            (anchor - timedelta(minutes=15), 4900.0, 4900.5, 4898.0, 4899.0),
            (anchor - timedelta(minutes=10), 4899.0, 4899.2, 4895.0, 4895.5),
            (anchor - timedelta(minutes=5), 4895.5, 4896.2, 4895.4, 4896.0),
        ]
    )
    detected = detect_pre_anchor_sweep_control({"M5": pre}, anchor, pip_size=0.1)
    assert detected is not None
    direction, entry = detected
    assert direction.direction_guess == "LONG"
    assert direction.sweep_type == "DOWNWARD_SWEEP"
    assert entry.entry_price == 4895.0


def test_sweep_detection_excludes_anchor_and_post_anchor_candles():
    anchor = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    anchor_only = _frame(
        [
            (anchor - timedelta(minutes=20), 4900.0, 4901.0, 4899.8, 4900.5),
            (anchor - timedelta(minutes=15), 4900.5, 4901.0, 4900.2, 4901.0),
            (anchor - timedelta(minutes=10), 4901.0, 4901.0, 4900.8, 4901.0),
            (anchor - timedelta(minutes=5), 4901.0, 4901.0, 4901.0, 4901.0),
            (anchor, 4901.2, 4905.0, 4901.0, 4901.5),
        ]
    )
    assert detect_pre_anchor_sweep_control({"M5": anchor_only}, anchor, pip_size=0.1) is None

    post_anchor_rejection = _frame(
        [
            (anchor - timedelta(minutes=20), 4900.0, 4901.0, 4899.8, 4900.5),
            (anchor - timedelta(minutes=15), 4900.5, 4901.0, 4900.2, 4901.0),
            (anchor - timedelta(minutes=10), 4901.0, 4904.0, 4901.4, 4903.9),
            (anchor - timedelta(minutes=5), 4903.9, 4904.0, 4903.7, 4904.0),
            (anchor + timedelta(minutes=1), 4904.0, 4904.1, 4902.0, 4902.5),
        ]
    )
    assert detect_pre_anchor_sweep_control({"M5": post_anchor_rejection}, anchor, pip_size=0.1) is None


def test_sweep_control_anchor_delay_is_required():
    anchor = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    frame = _frame(
        [
            (anchor - timedelta(minutes=9), 4900.0, 4901.0, 4899.8, 4900.5),
            (anchor - timedelta(minutes=8), 4900.5, 4901.2, 4900.2, 4901.0),
            (anchor - timedelta(minutes=1), 4901.0, 4904.0, 4900.8, 4901.2),
        ]
    )
    assert detect_pre_anchor_sweep_control({"M1": frame}, anchor, pip_size=0.1, min_anchor_delay_minutes=5) is None


def test_control_group_generation_creates_non_overlapping_rows(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    from dazro_trade.backtest.data_loader import load_csv_timeframes

    frames = load_csv_timeframes("XAUUSD", ["M1", "M5", "M15", "H1"], data_dir=str(data_dir))
    candidates = [
        _sample(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)),
        _sample(datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc), sample_id="sample_002"),
    ]
    result = generate_control_samples(candidates, frames, symbol="XAUUSD", requested=3, forward_hours=4)
    controls = result.samples
    assert len(controls) > 0
    assert all(control.row_type == "CONTROL" for control in controls)
    for control in controls:
        assert all(control.anchor_timestamp != candidate.anchor_timestamp for candidate in candidates)
    assert isinstance(result.limitations, list)
    assert "success_by_source" in result.stats


def test_entry_source_and_session_matching_defaults_and_seed_are_deterministic(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    from dazro_trade.backtest.data_loader import load_csv_timeframes

    frames = load_csv_timeframes("XAUUSD", ["M1", "M5", "M15", "H1"], data_dir=str(data_dir))
    anchor = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
    candidates = [_sample(anchor), _sample(datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc), sample_id="sample_002")]
    candidate_rows = [
        {
            "row_type": "CANDIDATE",
            "entry_level_source": ROUND_LEVEL,
            "session": classify_session_for_test(anchor),
            "anchor_timestamp": anchor.isoformat(),
        }
    ]
    cfg = ObjectiveReplayConfig(include_control_random=5, random_seed=7)
    first = generate_control_samples(candidates, frames, symbol="XAUUSD", requested=5, candidate_rows=candidate_rows, cfg=cfg)
    second = generate_control_samples(candidates, frames, symbol="XAUUSD", requested=5, candidate_rows=candidate_rows, cfg=cfg)
    assert cfg.control_match_entry_source is True
    assert cfg.control_match_session is True
    assert [sample.anchor_timestamp for sample in first.samples] == [sample.anchor_timestamp for sample in second.samples]
    assert all(sample.metadata["matched_control_for_entry_source"] is True for sample in first.samples)
    assert all(sample.metadata["matched_control_for_session"] is True for sample in first.samples)


def classify_session_for_test(ts: datetime) -> str:
    from dazro_trade.analytics.adelin_v2_objective_outcome_replay import classify_session

    return classify_session(ts)


def test_unmatched_session_controls_require_debug_flag(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    from dazro_trade.backtest.data_loader import load_csv_timeframes

    frames = load_csv_timeframes("XAUUSD", ["M1", "M5", "M15", "H1"], data_dir=str(data_dir))
    anchor = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
    candidates = [_sample(anchor), _sample(datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc), sample_id="sample_002")]
    candidate_rows = [{"row_type": "CANDIDATE", "entry_level_source": ROUND_LEVEL, "session": "IMPOSSIBLE_SESSION"}]
    strict = generate_control_samples(
        candidates,
        frames,
        symbol="XAUUSD",
        requested=3,
        candidate_rows=candidate_rows,
        cfg=ObjectiveReplayConfig(include_control_random=3, control_max_attempts_per_row=3),
    )
    assert strict.samples == []
    assert strict.stats["skip_reasons"].get("SESSION_MISMATCH", 0) > 0

    relaxed = generate_control_samples(
        candidates,
        frames,
        symbol="XAUUSD",
        requested=3,
        candidate_rows=candidate_rows,
        cfg=ObjectiveReplayConfig(include_control_random=3, allow_unmatched_session_controls=True, control_max_attempts_per_row=20),
    )
    assert relaxed.samples
    assert any(sample.metadata["matched_control_for_session"] is False for sample in relaxed.samples)


def test_unsupported_swept_liquidity_controls_report_limitation(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    from dazro_trade.backtest.data_loader import load_csv_timeframes

    frames = load_csv_timeframes("XAUUSD", ["M1", "M5", "M15", "H1"], data_dir=str(data_dir))
    anchor = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
    result = generate_control_samples(
        [_sample(anchor)],
        frames,
        symbol="XAUUSD",
        requested=5,
        candidate_rows=[{"row_type": "CANDIDATE", "entry_level_source": SWEPT_LIQUIDITY_LEVEL, "session": classify_session_for_test(anchor)}],
    )
    assert result.samples == []
    assert any("CONTROL_SOURCE_UNSUPPORTED_SWEPT_LIQUIDITY_LEVEL" in item for item in result.limitations)


def test_run_writes_outputs_summary_and_enriched_template(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    visual_pack_dir = _make_visual_pack(
        tmp_path,
        [
            datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc),
        ],
    )
    output_dir = tmp_path / "replay"
    summary = run_objective_replay(
        ObjectiveReplayConfig(
            data_dir=data_dir,
            visual_pack_dir=visual_pack_dir,
            output_dir=output_dir,
            include_control_random=3,
            dry_run=True,
        )
    )
    assert summary["total_candidate_samples_loaded"] == 2
    assert summary["candidate_samples_replayed"] == 2
    assert "candidate_vs_control" in summary
    assert "candidate_entry_level_source_counts" in summary
    assert "candidate_known_entry_count" in summary
    assert "candidate_vs_control_known_entry" in summary
    assert "candidate_fast_reaction_rate" in summary["candidate_vs_control_known_entry"]
    assert "candidate_outcome_counts_by_entry_level_source" in summary
    assert "entry_source_and_session_matched_metrics" in summary
    assert "source_metrics_with_confidence" in summary
    assert "pre_registered_verdict" in summary
    assert summary["pre_registered_verdict"] in {
        "CONTINUE_DETECTOR_REFINEMENT",
        "STOP_ARCHIVE_DETECTOR",
        "REPEAT_EXPANSION_ONCE",
        "INCONCLUSIVE",
    }
    assert "control_generation_method" in (output_dir / "objective_outcome_replay.csv").read_text(encoding="utf-8")
    assert "control_lookahead_safe" in (output_dir / "objective_outcome_replay.csv").read_text(encoding="utf-8")
    assert (output_dir / "objective_outcome_replay.csv").exists()
    assert (output_dir / "objective_outcome_replay_summary.json").exists()
    assert (output_dir / "objective_outcome_replay.md").exists()
    assert (output_dir / "index.html").exists()
    assert (output_dir / "enriched_manual_labels_template.csv").exists()
    saved_summary = json.loads((output_dir / "objective_outcome_replay_summary.json").read_text(encoding="utf-8"))
    assert "candidate_fast_reaction_rate" in saved_summary["candidate_vs_control"]
    assert "candidate_fast_reaction_rate" in saved_summary["candidate_vs_control_known_entry"]
    assert "ROUND_LEVEL" in saved_summary["candidate_entry_level_source_counts"]


def test_cli_writes_outputs(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    visual_pack_dir = _make_visual_pack(tmp_path, [datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)])
    output_dir = tmp_path / "cli_replay"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "analyze_adelin_v2_objective_outcome_replay.py"),
            "--symbol",
            "XAUUSD",
            "--data-dir",
            str(data_dir),
            "--visual-pack-dir",
            str(visual_pack_dir),
            "--output-dir",
            str(output_dir),
            "--forward-hours",
            "4",
            "--include-control-random",
            "1",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "candidate_outcome_label_counts" in result.stdout
    assert (output_dir / "objective_outcome_replay_summary.json").exists()


def test_temp_input_candle_csv_is_not_modified(tmp_path: Path):
    data_dir = _make_data_dir(tmp_path)
    visual_pack_dir = _make_visual_pack(tmp_path, [datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)])
    m1_path = data_dir / "XAUUSD" / "M1.csv"
    before = m1_path.read_bytes()
    run_objective_replay(
        ObjectiveReplayConfig(
            data_dir=data_dir,
            visual_pack_dir=visual_pack_dir,
            output_dir=tmp_path / "replay",
            include_control_random=0,
        )
    )
    assert m1_path.read_bytes() == before
