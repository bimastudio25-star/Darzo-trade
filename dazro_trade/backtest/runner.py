from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable, Iterable

import pandas as pd

from dazro_trade.adelin import run_adelin_scan
from dazro_trade.analysis.liquidity_expansion import (
    LiquidityExpansionDiagnostics,
    LiquidityExpansionSignal,
    evaluate_liquidity_expansion,
)
from dazro_trade.backtest.adelin_sl_policy import (
    AdelinSLDecision,
    AdelinSLPolicy,
    evaluate_adelin_sl_acceptance,
)
from dazro_trade.backtest.data_loader import BacktestDataSlicer
from dazro_trade.backtest.simulator import BacktestSignal, BacktestTrade, simulate_trade_outcome
from dazro_trade.core.config import Settings
from dazro_trade.runtime.sessions import current_session_name

log = logging.getLogger(__name__)

SignalEvaluator = Callable[[dict[str, pd.DataFrame], datetime, str, Settings], list[BacktestSignal]]
STRATEGY_1_NAME = "strategy_1_adelin_scalp"
STRATEGY_2_NAME = "strategy_2_liquidity_expansion"
ALL_STRATEGY_NAMES = (STRATEGY_2_NAME, STRATEGY_1_NAME)
STRATEGY_ALIASES = {
    "adelin": STRATEGY_1_NAME,
    STRATEGY_1_NAME: STRATEGY_1_NAME,
    "strategy_2_0": STRATEGY_2_NAME,
    "liquidity_expansion": STRATEGY_2_NAME,
    STRATEGY_2_NAME: STRATEGY_2_NAME,
}


@dataclass
class BacktestPerformanceConfig:
    progress_every_candles: int = 500
    max_candles: int | None = None
    fast_mode: bool = False
    lookback_by_timeframe: dict[str, int] = field(default_factory=lambda: {
        "M1": 2000,
        "M5": 2000,
        "M15": 1000,
        "H1": 1000,
        "H4": 500,
        "D1": 500,
    })
    liquidity_map_lookback_by_timeframe: dict[str, int] = field(default_factory=lambda: {
        "H4": 300,
        "H1": 500,
        "M15": 1000,
        "M5": 1500,
    })


class BacktestInterrupted(KeyboardInterrupt):
    def __init__(self, signals: list[BacktestSignal], trades: list[BacktestTrade], config: "BacktestConfig"):
        super().__init__("backtest_interrupted")
        self.signals = signals
        self.trades = trades
        self.config = config


def resolve_strategy_selection(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return list(ALL_STRATEGY_NAMES)
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",") if item.strip()]
    else:
        raw = []
        for item in value:
            raw.extend(part.strip() for part in str(item).split(",") if part.strip())
    if not raw or any(item.lower() == "all" for item in raw):
        return list(ALL_STRATEGY_NAMES)
    selected: list[str] = []
    for item in raw:
        key = item.lower()
        canonical = STRATEGY_ALIASES.get(key)
        if canonical is None:
            raise ValueError(f"unsupported_backtest_strategy={item}")
        if canonical not in selected:
            selected.append(canonical)
    return selected


@dataclass
class BacktestConfig:
    symbol: str = "XAUUSD"
    timeframes: list[str] = field(default_factory=lambda: ["M1", "M5", "M15", "H1", "H4", "D1"])
    settings: Settings = field(default_factory=Settings)
    driver_timeframe: str = "M15"
    max_sim_bars: int = 480
    per_strategy_max_sl: dict[str, float] = field(default_factory=lambda: {"strategy_1_adelin_scalp": 5.0, "mtpc_range": 5.0})
    min_score_overrides: dict[str, int] = field(default_factory=dict)
    strategy_diagnostics: dict[str, object] = field(default_factory=dict)
    evaluator_drivers: dict[str, str] = field(default_factory=lambda: {
        STRATEGY_2_NAME: "M15",
        STRATEGY_1_NAME: "M5",
    })
    strategies: list[str] = field(default_factory=lambda: ["all"])
    performance: BacktestPerformanceConfig = field(default_factory=BacktestPerformanceConfig)
    strategy_2_setup_tf: str = "M15"
    strategy_2_refinement_tf: str = "M5"
    strategy_2_trigger_tf: str = "M1"
    strategy_2_htf_context: list[str] = field(default_factory=lambda: ["D1", "H4", "H1"])
    adelin_scalp_driver: str = "M5"
    adelin_scalp_setup_tf: str = "M15"
    adelin_scalp_refinement_tf: str = "M5"
    adelin_scalp_trigger_tf: str = "M1"
    adelin_scalp_htf_context: list[str] = field(default_factory=lambda: ["D1", "H4", "H1"])
    adelin_sl_policy: AdelinSLPolicy | None = None


def _classify_adelin_rejection_layer(reason: str) -> str:
    r = reason.lower()
    if r in {"no_candle_data", "no_tick_price"}:
        return "DATA"
    if "session" in r or "news_gate" in r:
        return "HTF_FILTER"
    if "liquidity_sweep" in r:
        return "TRIGGER_M1"
    if any(k in r for k in ("score", "spread", "rr", "scalp_target", "min_stop", "max_stop")):
        return "SCORE_RR"
    return "OTHER"


def _signals_per_day(signals_emitted: int, first_ts: datetime | None, last_ts: datetime | None) -> float:
    if signals_emitted <= 0 or first_ts is None or last_ts is None:
        return 0.0
    delta_days = (last_ts - first_ts).total_seconds() / 86400.0
    if delta_days <= 0:
        return 0.0
    return round(signals_emitted / delta_days, 4)


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
            "risk_label": lex.risk_label,
            "enable_be_after_tp1": True,
        },
    )


def _evaluate_strategy_2(
    market_data: dict[str, pd.DataFrame],
    when: datetime,
    session: str,
    settings: Settings,
    diagnostics: LiquidityExpansionDiagnostics | None = None,
) -> list[BacktestSignal]:
    if diagnostics is not None and hasattr(diagnostics, "first_eval_time"):
        if diagnostics.first_eval_time is None:
            diagnostics.first_eval_time = when
        diagnostics.last_eval_time = when
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
    rejections_by_layer: dict[str, int] = field(default_factory=dict)
    long_signals: int = 0
    short_signals: int = 0
    driver_timeframe: str = "M5"
    setup_timeframe: str = "M15"
    refinement_timeframe: str = "M5"
    trigger_timeframe: str = "M1"
    htf_context_timeframes: list[str] = field(default_factory=lambda: ["D1", "H4", "H1"])
    first_eval_time: datetime | None = None
    last_eval_time: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "evaluation_count": self.total_calls,
            "driver_timeframe": self.driver_timeframe,
            "setup_timeframe": self.setup_timeframe,
            "refinement_timeframe": self.refinement_timeframe,
            "trigger_timeframe": self.trigger_timeframe,
            "htf_context_timeframes": list(self.htf_context_timeframes),
            "skip_missing_data": self.skip_missing_data,
            "no_signal_count": self.no_signal_count,
            "signals_emitted": self.signals_emitted,
            "signals_per_day": _signals_per_day(self.signals_emitted, self.first_eval_time, self.last_eval_time),
            "setup_modes": dict(self.setup_modes),
            "rejected_reasons": dict(self.rejected_reasons),
            "rejections_by_layer": dict(self.rejections_by_layer),
            "long_signals": self.long_signals,
            "short_signals": self.short_signals,
            "first_eval_time": self.first_eval_time.isoformat() if self.first_eval_time else None,
            "last_eval_time": self.last_eval_time.isoformat() if self.last_eval_time else None,
        }


def _evaluate_adelin(
    market_data: dict[str, pd.DataFrame],
    when: datetime,
    session: str,
    settings: Settings,
    diagnostics: AdelinDiagnostics | None = None,
    liquidity_map_cache: dict[tuple[object, ...], list[dict]] | None = None,
    liquidity_map_lookback_by_timeframe: dict[str, int] | None = None,
) -> list[BacktestSignal]:
    if diagnostics is not None:
        diagnostics.total_calls += 1
        if diagnostics.first_eval_time is None:
            diagnostics.first_eval_time = when
        diagnostics.last_eval_time = when
    m1 = market_data.get("M1")
    m5 = market_data.get("M5")
    if m1 is None or len(m1) == 0 or m5 is None or len(m5) == 0:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
            diagnostics.rejections_by_layer["DATA"] = diagnostics.rejections_by_layer.get("DATA", 0) + 1
        return []
    last_price = float(m5["close"].iloc[-1]) if "close" in m5.columns else 0.0
    if last_price <= 0:
        if diagnostics is not None:
            diagnostics.skip_missing_data += 1
            diagnostics.rejections_by_layer["DATA"] = diagnostics.rejections_by_layer.get("DATA", 0) + 1
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
            liquidity_map_cache=liquidity_map_cache,
            liquidity_map_lookback_by_timeframe=liquidity_map_lookback_by_timeframe,
        )
    except Exception as exc:
        log.warning("adelin_eval_failed when=%s err=%s", when, exc)
        return []
    if diagnostics is not None:
        for reason in result.get("rejected", []) or []:
            diagnostics.rejected_reasons[reason] = diagnostics.rejected_reasons.get(reason, 0) + 1
            layer = _classify_adelin_rejection_layer(reason)
            diagnostics.rejections_by_layer[layer] = diagnostics.rejections_by_layer.get(layer, 0) + 1
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
            "micro_confluence": signal_data.get("micro_confluence"),
        },
    )
    if diagnostics is not None:
        diagnostics.signals_emitted += 1
        if direction == "LONG":
            diagnostics.long_signals += 1
        else:
            diagnostics.short_signals += 1
    return [backtest_signal]


def _build_adelin_evaluator(diagnostics: AdelinDiagnostics, cfg: BacktestConfig) -> "SignalEvaluator":
    liquidity_map_cache: dict[tuple[object, ...], list[dict]] = {}

    def _wrapped(market_data, when, session, settings):
        return _evaluate_adelin(
            market_data,
            when,
            session,
            settings,
            diagnostics=diagnostics,
            liquidity_map_cache=liquidity_map_cache,
            liquidity_map_lookback_by_timeframe=cfg.performance.liquidity_map_lookback_by_timeframe,
        )
    return _wrapped


DEFAULT_EVALUATORS: dict[str, SignalEvaluator] = {
    STRATEGY_2_NAME: _evaluate_strategy_2,
    STRATEGY_1_NAME: _evaluate_adelin,
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


def _apply_adelin_sl_policy(signal: BacktestSignal, policy: AdelinSLPolicy) -> AdelinSLDecision:
    """Evaluate Adelin signal against the dynamic SL policy and mutate
    `signal.accepted` / `rejection_reasons` accordingly.

    Returns the AdelinSLDecision so the caller can record diagnostics
    (tier counters, ex-rejected recovery, etc.).
    """
    decision = evaluate_adelin_sl_acceptance(
        sl_usd=signal.sl_distance,
        score=signal.score,
        setup_mode=(signal.metadata or {}).get("setup_mode"),
        micro_confluence=(signal.metadata or {}).get("micro_confluence"),
        policy=policy,
    )
    if not decision.accepted:
        signal.accepted = False
        code = decision.rejection_code()
        if code:
            signal.rejection_reasons.append(code)
    return decision


def _future_m1(m1_full: pd.DataFrame, start_time: datetime) -> pd.DataFrame:
    if "time" not in m1_full.columns:
        return pd.DataFrame()
    frame = m1_full
    if "time" in frame.columns and not pd.api.types.is_datetime64_any_dtype(frame["time"]):
        frame = frame.copy()
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
    ts = pd.Timestamp(start_time)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    idx = frame["time"].searchsorted(ts, side="right")
    return frame.iloc[int(idx):]


def _ensure_default_diagnostics(cfg: BacktestConfig, name: str) -> object | None:
    if name == STRATEGY_2_NAME:
        if name not in cfg.strategy_diagnostics:
            diag = LiquidityExpansionDiagnostics()
            diag.driver_timeframe = cfg.evaluator_drivers.get(name, "M15")
            diag.setup_timeframe = cfg.strategy_2_setup_tf
            diag.refinement_timeframe = cfg.strategy_2_refinement_tf
            diag.trigger_timeframe = cfg.strategy_2_trigger_tf
            diag.htf_context_timeframes = list(cfg.strategy_2_htf_context)
            cfg.strategy_diagnostics[name] = diag
        return cfg.strategy_diagnostics[name]
    if name == STRATEGY_1_NAME:
        if name not in cfg.strategy_diagnostics:
            diag = AdelinDiagnostics()
            diag.driver_timeframe = cfg.evaluator_drivers.get(name, cfg.adelin_scalp_driver)
            diag.setup_timeframe = cfg.adelin_scalp_setup_tf
            diag.refinement_timeframe = cfg.adelin_scalp_refinement_tf
            diag.trigger_timeframe = cfg.adelin_scalp_trigger_tf
            diag.htf_context_timeframes = list(cfg.adelin_scalp_htf_context)
            cfg.strategy_diagnostics[name] = diag
        return cfg.strategy_diagnostics[name]
    return None


def _default_evaluators_with_diagnostics(cfg: BacktestConfig) -> dict[str, SignalEvaluator]:
    wired: dict[str, SignalEvaluator] = {}
    selected = set(resolve_strategy_selection(cfg.strategies))
    for name in DEFAULT_EVALUATORS:
        if name not in selected:
            continue
        diag = _ensure_default_diagnostics(cfg, name)
        if name == STRATEGY_2_NAME and isinstance(diag, LiquidityExpansionDiagnostics):
            wired[name] = _build_strategy_2_evaluator(diag)
        elif name == STRATEGY_1_NAME and isinstance(diag, AdelinDiagnostics):
            wired[name] = _build_adelin_evaluator(diag, cfg)
        else:
            wired[name] = DEFAULT_EVALUATORS[name]
    return wired


def _display_strategy_name(name: str) -> str:
    if name == STRATEGY_1_NAME:
        return "Adelin"
    if name == STRATEGY_2_NAME:
        return "Strategy 2.0"
    return name


def _format_duration(seconds: float) -> str:
    seconds_i = max(0, int(seconds))
    hours, rem = divmod(seconds_i, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _log_progress(
    *,
    evaluator_name: str,
    driver_tf: str,
    processed: int,
    total: int,
    started: float,
    signals_found: int,
    rejected: int,
    trades: int,
) -> None:
    elapsed = perf_counter() - started
    pct = (processed / total * 100.0) if total else 100.0
    remaining = (elapsed / processed * (total - processed)) if processed > 0 else 0.0
    log.info(
        "[%s] %s %s/%s %.1f%% elapsed=%s ETA=%s signals=%s trades=%s rejected=%s",
        _display_strategy_name(evaluator_name),
        driver_tf,
        processed,
        total,
        pct,
        _format_duration(elapsed),
        _format_duration(remaining),
        signals_found,
        trades,
        rejected,
    )


def run_backtest(
    market_data: dict[str, pd.DataFrame],
    *,
    config: BacktestConfig | None = None,
    evaluators: dict[str, SignalEvaluator] | None = None,
) -> tuple[list[BacktestSignal], list[BacktestTrade]]:
    cfg = config or BacktestConfig()
    if evaluators is None:
        evaluators = _default_evaluators_with_diagnostics(cfg)

    slicer = BacktestDataSlicer(
        market_data,
        fast_mode=cfg.performance.fast_mode,
        lookback_by_timeframe=cfg.performance.lookback_by_timeframe,
    )
    m1_full = slicer.frame("M1")

    signals: list[BacktestSignal] = []
    trades: list[BacktestTrade] = []
    dedup_keys: set[str] = set()

    try:
        for evaluator_name, evaluator in evaluators.items():
            driver_tf = cfg.evaluator_drivers.get(evaluator_name, cfg.driver_timeframe)
            driver = slicer.frame(driver_tf)
            if driver is None or len(driver) == 0:
                log.warning("backtest_no_driver_data evaluator=%s timeframe=%s", evaluator_name, driver_tf)
                continue
            total = len(driver)
            if cfg.performance.max_candles is not None:
                total = min(total, max(0, int(cfg.performance.max_candles)))
            progress_every = max(1, int(cfg.performance.progress_every_candles or 500))
            eval_signals = 0
            eval_rejected = 0
            eval_trades = 0
            started = perf_counter()
            log.info(
                "backtest_run evaluator=%s driver=%s candles=%s fast=%s",
                evaluator_name,
                driver_tf,
                total,
                cfg.performance.fast_mode,
            )
            for idx in range(total):
                candle = driver.iloc[idx]
                cutoff = candle["time"].to_pydatetime() if hasattr(candle["time"], "to_pydatetime") else candle["time"]
                sliced = slicer.slice_up_to(cutoff)
                session = _session_label_for(cutoff)
                try:
                    evaluated = evaluator(sliced, cutoff, session, cfg.settings) or []
                except Exception as exc:
                    log.warning("evaluator_failed name=%s err=%s when=%s", evaluator_name, exc, cutoff)
                    continue
                eval_signals += len(evaluated)
                for sig in evaluated:
                    if sig.strategy == STRATEGY_1_NAME and cfg.adelin_sl_policy is not None:
                        _apply_adelin_sl_policy(sig, cfg.adelin_sl_policy)
                    else:
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
                        eval_rejected += 1
                        continue
                    dedup_keys.add(dedup_key)
                    future_m1 = slicer.slice_after("M1", cutoff, max_rows=cfg.max_sim_bars)
                    if future_m1.empty:
                        future_m1 = _future_m1(m1_full, cutoff).head(cfg.max_sim_bars)
                    trade = simulate_trade_outcome(sig, future_m1, max_bars=cfg.max_sim_bars)
                    trades.append(trade)
                    if trade.outcome != "NO_DATA":
                        eval_trades += 1
                processed = idx + 1
                if processed % progress_every == 0 or processed == total:
                    _log_progress(
                        evaluator_name=evaluator_name,
                        driver_tf=driver_tf,
                        processed=processed,
                        total=total,
                        started=started,
                        signals_found=eval_signals,
                        rejected=eval_rejected,
                        trades=eval_trades,
                    )
    except KeyboardInterrupt as exc:
        log.warning("backtest_interrupted saving_partial signals=%s trades=%s", len(signals), len(trades))
        raise BacktestInterrupted(signals, trades, cfg) from exc
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


__all__ = [
    "BacktestConfig",
    "BacktestInterrupted",
    "BacktestPerformanceConfig",
    "DEFAULT_EVALUATORS",
    "build_equity_curve",
    "resolve_strategy_selection",
    "run_backtest",
]
