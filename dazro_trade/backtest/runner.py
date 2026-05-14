from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

import pandas as pd

from dazro_trade.analysis.liquidity_expansion import LiquidityExpansionSignal, evaluate_liquidity_expansion
from dazro_trade.backtest.data_loader import slice_market_data_up_to
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade, simulate_trade_outcome
from dazro_trade.core.config import Settings

log = logging.getLogger(__name__)

SignalEvaluator = Callable[[dict[str, pd.DataFrame], datetime, str, Settings], list[BacktestSignal]]


@dataclass
class BacktestConfig:
    symbol: str = "XAUUSD"
    timeframes: list[str] = field(default_factory=lambda: ["M1", "M5", "M15", "H1", "H4", "D1"])
    settings: Settings = field(default_factory=Settings)
    driver_timeframe: str = "H1"
    max_sim_bars: int = 480
    per_strategy_max_sl: dict[str, float] = field(default_factory=lambda: {"strategy_1_adelin": 5.0, "mtpc_range": 5.0})
    min_score_overrides: dict[str, int] = field(default_factory=dict)


def _session_label_for(ts: datetime) -> str:
    t = ts.astimezone(timezone.utc).time()
    if t.hour < 7:
        return "asia"
    if t.hour < 12:
        return "london"
    if t.hour < 21:
        return "ny"
    return "off_hours"


def _strategy_2_to_signal(lex: LiquidityExpansionSignal, symbol: str, when: datetime, session: str) -> BacktestSignal:
    return BacktestSignal(
        timestamp=when,
        symbol=symbol,
        strategy="strategy_2_liquidity_expansion",
        direction=lex.direction,
        entry=float(lex.entry),
        stop=float(lex.stop),
        tp1=float(lex.tp1),
        tp2=float(lex.tp2),
        tp3=float(lex.tp3),
        tp4=float(lex.tp4),
        rr_tp1=float(lex.rr_tp1),
        score=None,
        session=session,
        accepted=True,
        rejection_reasons=[],
        metadata={
            "candle_model": lex.candle_model,
            "trigger_kind": lex.trigger_kind,
            "tp1_basis": lex.tp1_basis,
            "h1_source": lex.reference.h1_source,
            "m15_source": lex.reference.m15_source,
            "samples": lex.stats.samples,
        },
    )


def _evaluate_strategy_2(
    market_data: dict[str, pd.DataFrame],
    when: datetime,
    session: str,
    settings: Settings,
) -> list[BacktestSignal]:
    m1 = market_data.get("M1")
    m5 = market_data.get("M5")
    m15 = market_data.get("M15")
    h1 = market_data.get("H1")
    if any(df is None or len(df) == 0 for df in (m1, m5, m15, h1)):
        return []
    last_price = float(m1["close"].iloc[-1]) if "close" in m1.columns else float(m1.iloc[-1]["c"]) if "c" in m1.columns else 0.0
    if last_price <= 0:
        return []
    try:
        lex = evaluate_liquidity_expansion(
            m1, m5, m15, h1,
            current_price=last_price,
            symbol=settings.mt5_symbol or "XAUUSD",
            lookback_h1=settings.liquidity_expansion_lookback_h1,
            range_in_range_max_pips=settings.liquidity_expansion_range_in_range_max_pips,
            m15_reference_timezone=settings.liquidity_expansion_m15_reference_timezone,
            now_utc=when,
            session=session,
            mae_engine_enabled=False,
            mae_db_path=None,
        )
    except Exception as exc:
        log.warning("strategy_2_eval_failed when=%s err=%s", when, exc)
        return []
    if lex is None:
        return []
    return [_strategy_2_to_signal(lex, settings.mt5_symbol or "XAUUSD", when, session)]


DEFAULT_EVALUATORS: dict[str, SignalEvaluator] = {
    "strategy_2_liquidity_expansion": _evaluate_strategy_2,
}


def _apply_per_strategy_sl_filter(signal: BacktestSignal, max_sl_map: dict[str, float]) -> None:
    if signal.strategy not in max_sl_map:
        return
    max_sl = float(max_sl_map[signal.strategy])
    if max_sl <= 0:
        return
    if signal.sl_distance > max_sl:
        signal.accepted = False
        signal.rejection_reasons.append(f"SL_TOO_WIDE_for_{signal.strategy}_max={max_sl}_actual={round(signal.sl_distance, 2)}")


def _future_m1(m1_full: pd.DataFrame, start_time: datetime) -> pd.DataFrame:
    if "time" not in m1_full.columns:
        return pd.DataFrame()
    ts = pd.Timestamp(start_time)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return m1_full[m1_full["time"] > ts].reset_index(drop=True)


def run_backtest(
    market_data: dict[str, pd.DataFrame],
    *,
    config: BacktestConfig | None = None,
    evaluators: dict[str, SignalEvaluator] | None = None,
) -> tuple[list[BacktestSignal], list[BacktestTrade]]:
    cfg = config or BacktestConfig()
    evaluators = evaluators or DEFAULT_EVALUATORS

    driver = market_data.get(cfg.driver_timeframe)
    if driver is None or len(driver) == 0:
        log.warning("backtest_no_driver_data timeframe=%s", cfg.driver_timeframe)
        return [], []

    m1_full = market_data.get("M1")
    if m1_full is None or len(m1_full) == 0:
        m1_full = pd.DataFrame()
    if "time" in m1_full.columns:
        m1_full = m1_full.copy()
        m1_full["time"] = pd.to_datetime(m1_full["time"], utc=True)
    driver = driver.copy()
    if "time" in driver.columns:
        driver["time"] = pd.to_datetime(driver["time"], utc=True)

    signals: list[BacktestSignal] = []
    trades: list[BacktestTrade] = []
    dedup_keys: set[str] = set()

    for idx in range(len(driver)):
        candle = driver.iloc[idx]
        cutoff = candle["time"].to_pydatetime() if hasattr(candle["time"], "to_pydatetime") else candle["time"]
        sliced = slice_market_data_up_to(market_data, cutoff)
        session = _session_label_for(cutoff)
        for evaluator in evaluators.values():
            try:
                evaluated = evaluator(sliced, cutoff, session, cfg.settings) or []
            except Exception as exc:
                log.warning("evaluator_failed err=%s when=%s", exc, cutoff)
                continue
            for sig in evaluated:
                _apply_per_strategy_sl_filter(sig, cfg.per_strategy_max_sl)
                min_score = cfg.min_score_overrides.get(sig.strategy)
                if sig.accepted and min_score is not None and sig.score is not None and sig.score < min_score:
                    sig.accepted = False
                    sig.rejection_reasons.append(f"LOW_SCORE_for_{sig.strategy}_min={min_score}_actual={sig.score}")
                dedup_key = f"{sig.strategy}:{sig.direction}:{round(sig.entry, 1)}:{cutoff.date().isoformat()}:{session}"
                if dedup_key in dedup_keys:
                    sig.accepted = False
                    sig.rejection_reasons.append("duplicate_signal_same_session_day")
                signals.append(sig)
                if not sig.accepted:
                    continue
                dedup_keys.add(dedup_key)
                future_m1 = _future_m1(m1_full, cutoff)
                trade = simulate_trade_outcome(sig, future_m1, max_bars=cfg.max_sim_bars)
                trades.append(trade)
    log.info("backtest_complete signals=%s trades=%s", len(signals), len(trades))
    return signals, trades


def build_equity_curve(trades: Iterable[BacktestTrade]) -> list[tuple[str, float]]:
    cumulative = 0.0
    curve: list[tuple[str, float]] = []
    for t in trades:
        if t.outcome == "NO_DATA":
            continue
        cumulative += t.r_multiple
        when = t.exit_time.isoformat() if t.exit_time else (t.signal.timestamp.isoformat() if t.signal.timestamp else "")
        curve.append((when, round(cumulative, 4)))
    return curve


__all__ = ["BacktestConfig", "DEFAULT_EVALUATORS", "build_equity_curve", "run_backtest"]
