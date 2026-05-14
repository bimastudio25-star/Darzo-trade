from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

import pandas as pd

from dazro_trade.adelin import run_adelin_scan
from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionDiagnostics,
    LiquidityExpansionSignal,
    evaluate_liquidity_expansion,
)
from dazro_trade.backtest.data_loader import slice_market_data_up_to
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade, simulate_trade_outcome
from dazro_trade.core.config import Settings
from dazro_trade.runtime.sessions import current_session_name

log = logging.getLogger(__name__)

SignalEvaluator = Callable[[dict[str, pd.DataFrame], datetime, str, Settings], list[BacktestSignal]]


@dataclass
class BacktestConfig:
    symbol: str = "XAUUSD"
    timeframes: list[str] = field(default_factory=lambda: ["M1", "M5", "M15", "H1", "H4", "D1"])
    settings: Settings = field(default_factory=Settings)
    driver_timeframe: str = "H1"
    max_sim_bars: int = 480
    per_strategy_max_sl: dict[str, float] = field(default_factory=lambda: {"strategy_1_adelin_scalp": 5.0, "mtpc_range": 5.0})
    min_score_overrides: dict[str, int] = field(default_factory=dict)
    strategy_diagnostics: dict[str, object] = field(default_factory=dict)
    evaluator_drivers: dict[str, str] = field(default_factory=lambda: {
        "strategy_2_liquidity_expansion": "H1",
        "strategy_1_adelin_scalp": "M5",
    })


def _session_label_for(ts: datetime) -> str:
    return current_session_name(ts.astimezone(timezone.utc) if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc))


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
    diagnostics: LiquidityExpansionDiagnostics | None = None,
) -> list[BacktestSignal]:
    m1 = market_data.get("M1")
    m5 = market_data.get("M5")
    m15 = market_data.get("M15")
    h1 = market_data.get("H1")
    if any(df is None or len(df) == 0 for df in (m1, m5, m15, h1)):
        if diagnostics is not None:
            diagnostics.total_calls += 1
            diagnostics.skip_missing_data += 1
        return []
    last_price = float(m1["close"].iloc[-1]) if "close" in m1.columns else float(m1.iloc[-1]["c"]) if "c" in m1.columns else 0.0
    if last_price <= 0:
        if diagnostics is not None:
            diagnostics.total_calls += 1
            diagnostics.skip_missing_data += 1
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
            diagnostics=diagnostics,
        )
    except Exception as exc:
        log.warning("strategy_2_eval_failed when=%s err=%s", when, exc)
        return []
    if lex is None:
        return []
    return [_strategy_2_to_signal(lex, settings.mt5_symbol or "XAUUSD", when, session)]


def _build_strategy_2_evaluator(diagnostics: LiquidityExpansionDiagnostics) -> "SignalEvaluator":
    def _wrapped(market_data, when, session, settings):
        return _evaluate_strategy_2(market_data, when, session, settings, diagnostics=diagnostics)
    return _wrapped


@dataclass
class AdelinDiagnostics:
    total_calls: int = 0
    skip_missing_data: int = 0
    no_signal_count: int = 0
    signals_emitted: int = 0
    setup_modes: dict[str, int] = field(default_factory=dict)
    rejected_reasons: dict[str, int] = field(default_factory=dict)
    long_signals: int = 0
    short_signals: int = 0

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "skip_missing_data": self.skip_missing_data,
            "no_signal_count": self.no_signal_count,
            "signals_emitted": self.signals_emitted,
            "setup_modes": dict(self.setup_modes),
            "rejected_reasons": dict(self.rejected_reasons),
            "long_signals": self.long_signals,
            "short_signals": self.short_signals,
        }


def _evaluate_adelin(
    market_data: dict[str, pd.DataFrame],
    when: datetime,
    session: str,
    settings: Settings,
    diagnostics: AdelinDiagnostics | None = None,
) -> list[BacktestSignal]:
    if diagnostics is not None:
        diagnostics.total_calls += 1
    m1 = market_data.get("M1")
    m5 = market_data.get("M5")
    if m1 is None or len(m1) == 0 or m5 is None or len(m5) == 0:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
        return []
    last_price = float(m5["close"].iloc[-1]) if "close" in m5.columns else 0.0
    if last_price <= 0:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
        return []
    try:
        result = run_adelin_scan(
            market_data=market_data,
            news_events=[],
            settings=settings,
            current_price=last_price,
            spread_pips=0.0,
            now_utc=when,
            session_name=session,
        )
    except Exception as exc:
        log.warning("adelin_eval_failed when=%s err=%s", when, exc)
        return []
    if diagnostics is not None:
        for reason in result.get("rejected", []) or []:
            diagnostics.rejected_reasons[reason] = diagnostics.rejected_reasons.get(reason, 0) + 1
        setup_mode = result.get("setup_mode", "NO_TRADE")
        diagnostics.setup_modes[setup_mode] = diagnostics.setup_modes.get(setup_mode, 0) + 1
    signal_data = result.get("signal")
    if not signal_data:
        if diagnostics is not None:
            diagnostics.no_signal_count += 1
        return []
    if signal_data.get("setup_mode") == "VWAP_STD_RESEARCH_1R":
        if diagnostics is not None:
            diagnostics.no_signal_count += 1
        return []
    tp1_payload = signal_data.get("tp1") or {}
    tp2_payload = signal_data.get("tp2") or {}
    direction = "LONG" if str(signal_data.get("direction", "")).upper() in {"LONG", "BUY"} else "SHORT"
    backtest_signal = BacktestSignal(
        timestamp=when,
        symbol=str(signal_data.get("symbol", "XAUUSD")),
        strategy="strategy_1_adelin_scalp",
        direction=direction,
        entry=float(signal_data["entry"]),
        stop=float(signal_data["sl"]),
        tp1=float(tp1_payload.get("price")),
        tp2=float(tp2_payload.get("price")) if tp2_payload.get("price") is not None else None,
        rr_tp1=float(tp1_payload.get("rr", 0) or 0),
        score=int(signal_data.get("score", 0) or 0),
        session=session,
        accepted=True,
        rejection_reasons=[],
        metadata={
            "setup_mode": signal_data.get("setup_mode"),
            "sl_pips": signal_data.get("sl_pips"),
            "sl_dollars": signal_data.get("sl_dollars"),
        },
    )
    if diagnostics is not None:
        diagnostics.signals_emitted += 1
        if direction == "LONG":
            diagnostics.long_signals += 1
        else:
            diagnostics.short_signals += 1
    return [backtest_signal]


def _build_adelin_evaluator(diagnostics: AdelinDiagnostics) -> "SignalEvaluator":
    def _wrapped(market_data, when, session, settings):
        return _evaluate_adelin(market_data, when, session, settings, diagnostics=diagnostics)
    return _wrapped


DEFAULT_EVALUATORS: dict[str, SignalEvaluator] = {
    "strategy_2_liquidity_expansion": _evaluate_strategy_2,
    "strategy_1_adelin_scalp": _evaluate_adelin,
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


def _ensure_default_diagnostics(cfg: BacktestConfig, name: str) -> object | None:
    if name == "strategy_2_liquidity_expansion":
        cfg.strategy_diagnostics.setdefault(name, LiquidityExpansionDiagnostics())
        return cfg.strategy_diagnostics[name]
    if name == "strategy_1_adelin_scalp":
        cfg.strategy_diagnostics.setdefault(name, AdelinDiagnostics())
        return cfg.strategy_diagnostics[name]
    return None


def _default_evaluators_with_diagnostics(cfg: BacktestConfig) -> dict[str, SignalEvaluator]:
    wired: dict[str, SignalEvaluator] = {}
    for name in DEFAULT_EVALUATORS:
        diag = _ensure_default_diagnostics(cfg, name)
        if name == "strategy_2_liquidity_expansion" and isinstance(diag, LiquidityExpansionDiagnostics):
            wired[name] = _build_strategy_2_evaluator(diag)
        elif name == "strategy_1_adelin_scalp" and isinstance(diag, AdelinDiagnostics):
            wired[name] = _build_adelin_evaluator(diag)
        else:
            wired[name] = DEFAULT_EVALUATORS[name]
    return wired


def run_backtest(
    market_data: dict[str, pd.DataFrame],
    *,
    config: BacktestConfig | None = None,
    evaluators: dict[str, SignalEvaluator] | None = None,
) -> tuple[list[BacktestSignal], list[BacktestTrade]]:
    cfg = config or BacktestConfig()
    if evaluators is None:
        evaluators = _default_evaluators_with_diagnostics(cfg)

    m1_full = market_data.get("M1")
    if m1_full is None or len(m1_full) == 0:
        m1_full = pd.DataFrame()
    if "time" in m1_full.columns:
        m1_full = m1_full.copy()
        m1_full["time"] = pd.to_datetime(m1_full["time"], utc=True)

    signals: list[BacktestSignal] = []
    trades: list[BacktestTrade] = []
    dedup_keys: set[str] = set()

    for evaluator_name, evaluator in evaluators.items():
        driver_tf = cfg.evaluator_drivers.get(evaluator_name, cfg.driver_timeframe)
        driver = market_data.get(driver_tf)
        if driver is None or len(driver) == 0:
            log.warning("backtest_no_driver_data evaluator=%s timeframe=%s", evaluator_name, driver_tf)
            continue
        driver = driver.copy()
        if "time" in driver.columns:
            driver["time"] = pd.to_datetime(driver["time"], utc=True)
        log.info("backtest_run evaluator=%s driver=%s candles=%s", evaluator_name, driver_tf, len(driver))
        for idx in range(len(driver)):
            candle = driver.iloc[idx]
            cutoff = candle["time"].to_pydatetime() if hasattr(candle["time"], "to_pydatetime") else candle["time"]
            sliced = slice_market_data_up_to(market_data, cutoff)
            session = _session_label_for(cutoff)
            try:
                evaluated = evaluator(sliced, cutoff, session, cfg.settings) or []
            except Exception as exc:
                log.warning("evaluator_failed name=%s err=%s when=%s", evaluator_name, exc, cutoff)
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
