from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd


DEFAULT_BOT_SOURCE = Path("backtests/reports/strategy_2_layer_b_reaction_quality/layer_b_reaction_features_per_sample.csv")
DEFAULT_OUTPUT_DIR = Path("backtests/reports/strategy_2_human_trade_alignment")
HUMAN_TRADES_TEMPLATE = "human_trades_template.csv"
VALID_DIRECTIONS = {"LONG", "SHORT"}
VALID_BOT_DESCRIPTORS = {"FAST_REENTRY", "CHOP_AFTER_SWEEP_CANDIDATE"}
VALID_BOT_STATES = {"VALID_LONG", "VALID_SHORT"}
HUMAN_TRADE_FIELDS = [
    "human_trade_id",
    "source",
    "symbol",
    "direction",
    "open_time",
    "close_time",
    "entry_price",
    "exit_price",
    "stop_loss",
    "take_profit",
    "volume",
    "result_optional",
    "screenshot_path_optional",
    "notes",
    "strategy_tag_optional",
]
DEFAULT_CONFIG = {
    "symbol": "XAUUSD",
    "max_signal_lead_minutes": 60,
    "max_signal_lag_minutes": 15,
    "near_entry_minutes": 5,
    "max_entry_price_distance_usd": 3.0,
    "tolerances_are_diagnostic_assumptions": True,
    "optimize_tolerances": False,
    "unmatched_bot_candidates_are_not_false_positives": True,
}
SAFETY = {
    "strategy_2_only": True,
    "layer_b_pipeline_rerun": False,
    "live_trading_enabled": False,
    "order_send_called": False,
    "broker_execution_called": False,
    "telegram_operational_signals_sent": False,
    "signals_generated": False,
    "parameters_optimized": False,
    "ml_used": False,
    "backtest_executed": False,
    "performance_claim_made": False,
    "wr_pf_r_claim_made": False,
    "automatic_rule_created": False,
    "market_data_written": False,
    "fabricated_human_trades": False,
}


@dataclass(frozen=True)
class HumanTradeAlignmentResult:
    human_template: pd.DataFrame
    config: dict[str, Any]
    summary: dict[str, Any]
    readme_markdown: str
    per_trade: pd.DataFrame | None
    per_bot_candidate: pd.DataFrame | None


def load_bot_candidates(path: str | Path = DEFAULT_BOT_SOURCE, *, symbol: str = "XAUUSD") -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Strategy 2 Layer B source not found: {source}")
    frame = pd.read_csv(source)
    required = {"sample_id", "direction_candidate", "layer_a_state", "reaction_descriptor", "decision_time"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Layer B source missing required columns: {missing}")
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol
    frame["decision_time_parsed"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    mask = (
        frame["layer_a_state"].astype(str).isin(VALID_BOT_STATES)
        & frame["reaction_descriptor"].astype(str).isin(VALID_BOT_DESCRIPTORS)
        & frame["decision_time_parsed"].notna()
    )
    candidates = frame[mask].copy().reset_index(drop=True)
    candidates["bot_candidate_status"] = "UNMATCHED_BOT_CANDIDATE"
    return candidates


def write_human_trades_template(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / HUMAN_TRADES_TEMPLATE
    if not path.exists():
        pd.DataFrame(columns=HUMAN_TRADE_FIELDS).to_csv(path, index=False)
    return path


def load_human_trades(path: str | Path) -> tuple[pd.DataFrame, bool]:
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=HUMAN_TRADE_FIELDS), False
    frame = pd.read_csv(source, keep_default_na=False)
    missing = sorted(set(HUMAN_TRADE_FIELDS) - set(frame.columns))
    if missing:
        raise ValueError(f"human trades file missing required columns: {missing}")
    frame = frame[HUMAN_TRADE_FIELDS].copy()
    non_empty = frame.apply(lambda row: any(str(value).strip() for value in row), axis=1) if not frame.empty else pd.Series(dtype=bool)
    frame = frame[non_empty].copy() if not frame.empty else frame
    return frame.reset_index(drop=True), bool(not frame.empty)


def build_human_trade_alignment_pack(
    bot_source: str | Path = DEFAULT_BOT_SOURCE,
    *,
    human_trades_path: str | Path | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    config: dict[str, Any] | None = None,
) -> HumanTradeAlignmentResult:
    started = time.perf_counter()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = {**DEFAULT_CONFIG, **(config or {})}
    template_path = write_human_trades_template(output)
    human_path = Path(human_trades_path) if human_trades_path else template_path
    human_trades, real_trades_provided = load_human_trades(human_path)
    bot_candidates = load_bot_candidates(bot_source, symbol=str(config["symbol"]))

    per_trade: pd.DataFrame | None = None
    per_bot_candidate: pd.DataFrame | None = None
    if real_trades_provided:
        per_trade, per_bot_candidate = align_human_trades_to_bot_candidates(human_trades, bot_candidates, config=config)
        summary = summarize_with_real_trades(
            human_trades,
            bot_candidates,
            per_trade,
            per_bot_candidate,
            config=config,
            started=started,
            bot_source=bot_source,
            human_path=human_path,
        )
    else:
        summary = summarize_without_real_trades(
            bot_candidates,
            config=config,
            started=started,
            bot_source=bot_source,
            human_path=human_path,
            template_path=template_path,
        )
    return HumanTradeAlignmentResult(
        human_template=pd.DataFrame(columns=HUMAN_TRADE_FIELDS),
        config=config,
        summary=summary,
        readme_markdown=render_alignment_readme(summary),
        per_trade=per_trade,
        per_bot_candidate=per_bot_candidate,
    )


def align_human_trades_to_bot_candidates(
    human_trades: pd.DataFrame,
    bot_candidates: pd.DataFrame,
    *,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_human = normalize_human_trades(human_trades)
    per_trade_rows: list[dict[str, Any]] = []
    candidate_matches: dict[str, list[str]] = defaultdict(list)
    ambiguous_candidate_ids: set[str] = set()

    for _, trade in normalized_human.iterrows():
        if not bool(trade["valid_strategy_2_tagged_human_trade"]):
            per_trade_rows.append(build_insufficient_trade_row(trade, reason=trade["validation_error"]))
            continue
        matches = find_matching_candidates(trade, bot_candidates, config=config)
        if matches.empty:
            per_trade_rows.append(build_missed_trade_row(trade))
            continue
        match_ids = matches["sample_id"].astype(str).tolist()
        if len(matches) > 1:
            ambiguous_candidate_ids.update(match_ids)
            for sample_id in match_ids:
                candidate_matches[sample_id].append(str(trade["human_trade_id"]))
            per_trade_rows.append(build_ambiguous_trade_row(trade, matches))
            continue
        match = matches.iloc[0]
        classification = classify_time_match(float(match["signal_delta_minutes"]), config=config)
        candidate_matches[str(match["sample_id"])].append(str(trade["human_trade_id"]))
        per_trade_rows.append(build_matched_trade_row(trade, match, classification))

    per_trade = pd.DataFrame(per_trade_rows)
    bot_rows: list[dict[str, Any]] = []
    for _, bot in bot_candidates.iterrows():
        sample_id = str(bot["sample_id"])
        matched_trade_ids = candidate_matches.get(sample_id, [])
        status = "UNMATCHED_BOT_CANDIDATE"
        if sample_id in ambiguous_candidate_ids or len(matched_trade_ids) > 1:
            status = "AMBIGUOUS_MATCH"
        elif matched_trade_ids:
            status = "MATCHED_HUMAN_TRADE"
        bot_rows.append(
            {
                "sample_id": sample_id,
                "symbol": _clean(bot.get("symbol")),
                "direction_candidate": _clean(bot.get("direction_candidate")).upper(),
                "decision_time": _clean(bot.get("decision_time")),
                "reaction_descriptor": _clean(bot.get("reaction_descriptor")),
                "h1_context_id": _clean(bot.get("h1_context_id")),
                "bot_candidate_alignment_status": status,
                "matched_human_trade_ids": ";".join(matched_trade_ids),
                "unmatched_bot_candidates_are_false_positives": False,
                "notes": "Pending forward/shadow validation" if status == "UNMATCHED_BOT_CANDIDATE" else "",
            }
        )
    return per_trade, pd.DataFrame(bot_rows)


def normalize_human_trades(human_trades: pd.DataFrame) -> pd.DataFrame:
    frame = human_trades.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["direction"] = frame["direction"].astype(str).str.strip().str.upper()
    frame["open_time_parsed"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    frame["entry_price_numeric"] = pd.to_numeric(frame["entry_price"], errors="coerce")
    frame["strategy_tag_normalized"] = frame["strategy_tag_optional"].astype(str).str.strip().str.lower()
    frame["valid_strategy_tag"] = frame["strategy_tag_normalized"].eq("") | frame["strategy_tag_normalized"].str.contains("strategy_2")
    frame["valid_strategy_2_tagged_human_trade"] = (
        frame["symbol"].ne("")
        & frame["direction"].isin(VALID_DIRECTIONS)
        & frame["open_time_parsed"].notna()
        & frame["valid_strategy_tag"]
    )
    frame["validation_error"] = frame.apply(human_trade_validation_error, axis=1)
    return frame


def human_trade_validation_error(row: pd.Series) -> str:
    errors: list[str] = []
    if not str(row.get("symbol", "")).strip():
        errors.append("MISSING_SYMBOL")
    if str(row.get("direction", "")).strip().upper() not in VALID_DIRECTIONS:
        errors.append("INVALID_DIRECTION")
    if pd.isna(row.get("open_time_parsed")):
        errors.append("INVALID_OPEN_TIME")
    if not bool(row.get("valid_strategy_tag")):
        errors.append("NOT_STRATEGY_2_TAGGED")
    return ";".join(errors)


def find_matching_candidates(trade: pd.Series, bot_candidates: pd.DataFrame, *, config: dict[str, Any]) -> pd.DataFrame:
    symbol = str(trade["symbol"]).upper()
    direction = str(trade["direction"]).upper()
    open_time = trade["open_time_parsed"]
    if pd.isna(open_time):
        return pd.DataFrame(columns=list(bot_candidates.columns))
    subset = bot_candidates[
        bot_candidates["symbol"].astype(str).str.upper().eq(symbol)
        & bot_candidates["direction_candidate"].astype(str).str.upper().eq(direction)
    ].copy()
    if subset.empty:
        return subset
    subset["signal_delta_minutes"] = (subset["decision_time_parsed"] - open_time).dt.total_seconds() / 60.0
    subset = subset[
        subset["signal_delta_minutes"].between(
            -float(config["max_signal_lead_minutes"]),
            float(config["max_signal_lag_minutes"]),
            inclusive="both",
        )
    ].copy()
    if subset.empty:
        return subset
    entry_price = _to_float(trade.get("entry_price"))
    subset["bot_price_for_match"] = subset.apply(extract_bot_entry_price, axis=1)
    subset["entry_price_distance_usd"] = subset["bot_price_for_match"].apply(
        lambda value: abs(float(value) - entry_price) if value is not None and entry_price is not None else None
    )
    if entry_price is not None and subset["bot_price_for_match"].notna().any():
        subset = subset[
            subset["entry_price_distance_usd"].isna()
            | subset["entry_price_distance_usd"].le(float(config["max_entry_price_distance_usd"]))
        ].copy()
    subset["time_abs_sort"] = subset["signal_delta_minutes"].abs()
    subset["price_sort"] = subset["entry_price_distance_usd"].fillna(999999.0)
    return subset.sort_values(["time_abs_sort", "price_sort", "sample_id"]).reset_index(drop=True)


def extract_bot_entry_price(row: pd.Series) -> float | None:
    for column in ["entry_price", "reentry_price", "range_reentry_price", "bot_entry_price"]:
        if column in row.index:
            value = _to_float(row.get(column))
            if value is not None:
                return value
    return None


def classify_time_match(delta_minutes: float, *, config: dict[str, Any]) -> str:
    near = float(config["near_entry_minutes"])
    if abs(delta_minutes) <= near:
        return "BOT_MATCHED_NEAR_ENTRY"
    if delta_minutes < 0:
        return "BOT_MATCHED_BEFORE_ENTRY"
    return "BOT_MATCHED_AFTER_ENTRY"


def build_matched_trade_row(trade: pd.Series, match: pd.Series, classification: str) -> dict[str, Any]:
    return {
        **human_trade_identity(trade),
        "alignment_classification": classification,
        "matched_bot_sample_ids": str(match["sample_id"]),
        "match_count": 1,
        "best_bot_decision_time": _clean(match.get("decision_time")),
        "best_signal_delta_minutes": round(float(match.get("signal_delta_minutes")), 4),
        "entry_price_distance_usd": _clean(match.get("entry_price_distance_usd")),
        "bot_reaction_descriptor": _clean(match.get("reaction_descriptor")),
        "alignment_notes": "Diagnostic match only; not performance validation.",
    }


def build_ambiguous_trade_row(trade: pd.Series, matches: pd.DataFrame) -> dict[str, Any]:
    best = matches.iloc[0]
    return {
        **human_trade_identity(trade),
        "alignment_classification": "AMBIGUOUS_MULTIPLE_MATCHES",
        "matched_bot_sample_ids": ";".join(matches["sample_id"].astype(str).tolist()),
        "match_count": int(len(matches)),
        "best_bot_decision_time": _clean(best.get("decision_time")),
        "best_signal_delta_minutes": round(float(best.get("signal_delta_minutes")), 4),
        "entry_price_distance_usd": _clean(best.get("entry_price_distance_usd")),
        "bot_reaction_descriptor": _clean(best.get("reaction_descriptor")),
        "alignment_notes": "Multiple bot candidates satisfy diagnostic tolerances.",
    }


def build_missed_trade_row(trade: pd.Series) -> dict[str, Any]:
    return {
        **human_trade_identity(trade),
        "alignment_classification": "BOT_MISSED",
        "matched_bot_sample_ids": "",
        "match_count": 0,
        "best_bot_decision_time": "",
        "best_signal_delta_minutes": "",
        "entry_price_distance_usd": "",
        "bot_reaction_descriptor": "",
        "alignment_notes": "No Strategy 2 candidate matched fixed diagnostic tolerances.",
    }


def build_insufficient_trade_row(trade: pd.Series, *, reason: str) -> dict[str, Any]:
    return {
        **human_trade_identity(trade),
        "alignment_classification": "INSUFFICIENT_DATA",
        "matched_bot_sample_ids": "",
        "match_count": 0,
        "best_bot_decision_time": "",
        "best_signal_delta_minutes": "",
        "entry_price_distance_usd": "",
        "bot_reaction_descriptor": "",
        "alignment_notes": reason,
    }


def human_trade_identity(trade: pd.Series) -> dict[str, Any]:
    return {
        "human_trade_id": _clean(trade.get("human_trade_id")),
        "source": _clean(trade.get("source")),
        "symbol": _clean(trade.get("symbol")).upper(),
        "direction": _clean(trade.get("direction")).upper(),
        "open_time": _clean(trade.get("open_time")),
        "entry_price": _clean(trade.get("entry_price")),
        "strategy_tag_optional": _clean(trade.get("strategy_tag_optional")),
    }


def summarize_without_real_trades(
    bot_candidates: pd.DataFrame,
    *,
    config: dict[str, Any],
    started: float,
    bot_source: str | Path,
    human_path: Path,
    template_path: Path,
) -> dict[str, Any]:
    return {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "bot_source": str(Path(bot_source)),
        "human_trades_path": str(human_path),
        "human_trades_template_path": str(template_path),
        "real_human_trades_provided": False,
        "status": "HUMAN_TRADES_NOT_PROVIDED_YET",
        "bot_candidates_loaded": int(len(bot_candidates)),
        "template_created": True,
        "alignment_metrics_generated": False,
        "no_fake_trades_used_as_evidence": True,
        "config": config,
        "safety": SAFETY,
        "verdict_flags": [
            "HUMAN_TRADES_NOT_PROVIDED_YET",
            "TEMPLATE_CREATED",
            "NO_FABRICATED_EVIDENCE",
            "STRATEGY_2_REMAINS_RESEARCH_ONLY",
            "NO_DEPLOYMENT_DECISION",
        ],
    }


def summarize_with_real_trades(
    human_trades: pd.DataFrame,
    bot_candidates: pd.DataFrame,
    per_trade: pd.DataFrame,
    per_bot_candidate: pd.DataFrame,
    *,
    config: dict[str, Any],
    started: float,
    bot_source: str | Path,
    human_path: Path,
) -> dict[str, Any]:
    matched_statuses = {"BOT_MATCHED_BEFORE_ENTRY", "BOT_MATCHED_NEAR_ENTRY", "BOT_MATCHED_AFTER_ENTRY"}
    valid_count = int(per_trade[~per_trade["alignment_classification"].eq("INSUFFICIENT_DATA")].shape[0])
    matched_count = int(per_trade["alignment_classification"].isin(matched_statuses).sum())
    missed_count = int(per_trade["alignment_classification"].eq("BOT_MISSED").sum())
    ambiguous_count = int(per_trade["alignment_classification"].eq("AMBIGUOUS_MULTIPLE_MATCHES").sum())
    matched_rows = per_trade[per_trade["alignment_classification"].isin(matched_statuses)].copy()
    price_distances = pd.to_numeric(matched_rows["entry_price_distance_usd"], errors="coerce").dropna().tolist()
    signal_deltas = pd.to_numeric(matched_rows["best_signal_delta_minutes"], errors="coerce").dropna().tolist()
    matched_bot = per_bot_candidate[per_bot_candidate["bot_candidate_alignment_status"].eq("MATCHED_HUMAN_TRADE")]
    unmatched_bot = per_bot_candidate[per_bot_candidate["bot_candidate_alignment_status"].eq("UNMATCHED_BOT_CANDIDATE")]
    return {
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "bot_source": str(Path(bot_source)),
        "human_trades_path": str(human_path),
        "real_human_trades_provided": True,
        "total_human_trades_loaded": int(len(human_trades)),
        "valid_strategy_2_tagged_human_trades": valid_count,
        "matched_human_trades": matched_count,
        "missed_human_trades": missed_count,
        "ambiguous_human_trades": ambiguous_count,
        "human_trade_recall": round(matched_count / valid_count, 6) if valid_count else None,
        "median_signal_lead_lag_minutes": round(median(signal_deltas), 6) if signal_deltas else None,
        "median_entry_price_distance_usd": round(median(price_distances), 6) if price_distances else None,
        "bot_candidates_loaded": int(len(bot_candidates)),
        "bot_candidates_matched_to_human_trades": int(len(matched_bot)),
        "bot_candidates_unmatched": int(len(unmatched_bot)),
        "unmatched_bot_candidates_are_false_positives": False,
        "descriptor_distribution_matched_candidates": dict(sorted(Counter(matched_bot["reaction_descriptor"]).items())),
        "descriptor_distribution_unmatched_candidates": dict(sorted(Counter(unmatched_bot["reaction_descriptor"]).items())),
        "alignment_metrics_generated": True,
        "no_fake_trades_used_as_evidence": True,
        "config": config,
        "safety": SAFETY,
        "verdict_flags": [
            "HUMAN_TRADE_ALIGNMENT_COMPLETE",
            "UNMATCHED_BOT_CANDIDATES_NOT_FALSE_POSITIVES",
            "NO_FABRICATED_EVIDENCE",
            "STRATEGY_2_REMAINS_RESEARCH_ONLY",
            "NO_DEPLOYMENT_DECISION",
        ],
    }


def write_human_trade_alignment_outputs(result: HumanTradeAlignmentResult, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "human_trades_template": output / HUMAN_TRADES_TEMPLATE,
        "readme": output / "README_human_trade_alignment.md",
        "config": output / "human_trade_alignment_config.json",
        "summary": output / "human_trade_alignment_summary.json",
    }
    if not paths["human_trades_template"].exists():
        pd.DataFrame(columns=HUMAN_TRADE_FIELDS).to_csv(paths["human_trades_template"], index=False)
    paths["readme"].write_text(result.readme_markdown, encoding="utf-8")
    paths["config"].write_text(json.dumps(result.config, indent=2, sort_keys=True), encoding="utf-8")
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    if result.per_trade is not None:
        paths["per_trade"] = output / "human_trade_alignment_per_trade.csv"
        result.per_trade.to_csv(paths["per_trade"], index=False)
    if result.per_bot_candidate is not None:
        paths["per_bot_candidate"] = output / "human_trade_alignment_per_bot_candidate.csv"
        result.per_bot_candidate.to_csv(paths["per_bot_candidate"], index=False)
    return {key: str(path) for key, path in paths.items()}


def render_alignment_readme(summary: dict[str, Any]) -> str:
    lines = [
        "# Strategy 2 Human Trade Alignment",
        "",
        "This pack is for comparing Strategy 2 bot candidates against trades Adelin actually entered manually.",
        "It is not a backtest, signal generator, optimization pass, or deployment artifact.",
        "",
        "## How To Use",
        "",
        "Fill or export real human trades into `human_trades_template.csv` using the required columns.",
        "Do not fabricate trades. Empty templates are not evidence.",
        "",
        "Required direction values: LONG or SHORT.",
        "",
        "## Matching Logic",
        "",
        f"- Symbol must match.",
        f"- Direction must match.",
        f"- Bot decision time must be between {summary['config']['max_signal_lead_minutes']} minutes before and {summary['config']['max_signal_lag_minutes']} minutes after human open time.",
        f"- Entry price distance is checked only if a bot entry/reentry price is available; default tolerance is {summary['config']['max_entry_price_distance_usd']} USD.",
        "- Same H1 context can be compared later if it is exported in the human trade file.",
        "",
        "The tolerances are diagnostic assumptions, not optimized parameters.",
        "",
        "## Interpretation",
        "",
        "Human trade recall can be measured from real human trades.",
        "Bot precision cannot be fully measured from human trades alone.",
        "Unmatched bot candidates are not false positives automatically; they remain `UNMATCHED_BOT_CANDIDATE` pending forward/shadow validation.",
        "",
        "## Current Status",
        "",
        f"- Real human trades provided: {summary['real_human_trades_provided']}",
        f"- Status: {summary.get('status', 'REAL_HUMAN_TRADES_ANALYZED')}",
        f"- Bot candidates loaded: {summary['bot_candidates_loaded']}",
        "",
        "## Safety",
        "",
        "- Strategy 2 only.",
        "- No Strategy 3 or Adelin v2 files are touched.",
        "- No live trading, order_send, broker execution, Telegram operational signals, optimization, ML, or performance claim.",
    ]
    return "\n".join(lines) + "\n"


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
